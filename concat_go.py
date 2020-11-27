#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GoPro stores video files split into smaller files.
Sort the videos into order and merge them into a single mp4.
This assumes all vieos in the directory are part of the same video.
Ensure you use python >= 3.5 and have ffmpeg installed.
"""
from curses import wrapper
import argparse
import datetime
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

UPDATE_URL = "https://raw.githubusercontent.com/starcraftman/gopro-merge/master/concat_go.py"
OUT_TEMPLATE = 'merged_{}.mp4'
FFMPEG_CMD = 'ffmpeg -f concat -safe 0 -i {} -c copy {}'
PROGRESS_MSG = """Merge MP4 Status
----------------

Output File: {}
Log File: /tmp/merge.log
Size (MB): {:10,}/{:,}
Completion: {:3.2f}%
Estimated Time Remaining: {}

Cancel at any time with Ctrl + C
"""
RENAME_TEST = re.compile(r'(\d{3}__)?(.*)')
INFO = """Target output file for merge: {}
Will merge these videos together: {}\n\n\nContinue? Y/n """
try:
    input = raw_input
except NameError:
    pass
try:
    assert sys.version_info[0:2] >= (3, 5)
except AssertionError:
    print("This entire program must be run with python >= 3.5")
    print("You ran with python version: {}.{}".format(*sys.version_info[0:2]))
    sys.exit(1)


class RateEstimator(object):
    """
    Rate estimate based on progress over a window.
    """
    def __init__(self, expected_size, *, window=7):
        self.data = []
        self.expected_size = expected_size
        self.window = window

    def add_data(self, new_size):
        """
        Add a single new size to the data set.
        Maintain only the most recent window data points.
        Regardless of how often called, only add data with a big enough gap.
        """
        now = datetime.datetime.now()
        self.data += [(new_size, now)]
        self.data = self.data[-self.window:]

    def new_estimate(self):
        """
        Calculate a new estimate based on existing data.

        Returns: A datetime.timedelta of the time remaining until video merge complete.
        """
        size_delta = self.data[-1][0] - self.data[0][0]
        if size_delta == 0:
            return 'N/A'

        time_delta = (self.data[-1][1] - self.data[0][1]).total_seconds()
        size_left = self.expected_size - self.data[-1][0]
        secs_left = max(0, (size_left / size_delta)) * time_delta

        return datetime.timedelta(seconds=secs_left)


class CursesUI(object):
    """
    Curses manager to update user via cuses ui on merging progress.
    Blocking since I don't need to run more than the one command.
    """
    def __init__(self, expected_bytes, output_file, proc, *, time_sleep=0.05):
        self.expected_bytes = expected_bytes
        self.expected_mb = expected_bytes / (1024 ** 2)
        self.output_file = output_file
        self.proc = proc
        self.estimator = RateEstimator(expected_bytes)
        self.time_sleep = time_sleep

    def __call__(self, stdscr):
        """
        The function that gets called to update curses ui.
        """
        stdscr.clear()
        stdscr.addstr(self.check_file())

        self.proc.poll()
        while self.proc.returncode is None:
            stdscr.clear()
            stdscr.addstr(self.check_file())
            stdscr.refresh()

            time.sleep(self.time_sleep)
            self.proc.poll()

    def check_file(self):
        """
        Check the current file and return the text block describing it with estimate.

        Returns: A string to put in the curses ui.
        """
        try:
            cur_bytes = os.stat(self.output_file).st_size
        except OSError:
            cur_bytes = 0

        cur_mb = cur_bytes / (1024 ** 2)
        percent = 100 * float(cur_bytes) / float(self.expected_bytes)
        self.estimator.add_data(cur_bytes)

        msg = PROGRESS_MSG.format(self.output_file, int(cur_mb),
                                  int(self.expected_mb), percent,
                                  self.estimator.new_estimate())
        msg += draw_progress(percent)

        return msg


def draw_progress(percent, symbol='=', ticks=50):
    """
    Draw a simple ascii bar in percent.
    """
    done = int(math.floor((percent / 100) * ticks))
    not_done = ticks - done

    return '[{}{}]'.format(symbol * done, ' ' * not_done)


def total_files_size(files):
    """
    Simply return the size in bytes of all files in list.
    """
    total = 0
    for fname in files:
        total += os.stat(fname).st_size

    return total


# FIXME: Not sure why spaces in tempfile crash ffmpeg.
def merge_vids(vids, out_file):
    """
    Merge all videos into a single mp4 file.

    Args:
        vids: List of input mp4s to merge.
        out_file: The file to output the merged video to.
    """
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as fout:
        for vid in vids:
            fout.write("file '{}'\n".format(vid.replace("'", "\\\\'")))
        fout.flush()

        args = FFMPEG_CMD.format(fout.name, out_file).split(' ')
        stdout = open('/tmp/merge.log', 'w')
        proc = subprocess.Popen(args, stdout=stdout,
                                stderr=subprocess.STDOUT)
        proc.poll()

        return proc, fout.name


def make_parser():
    """
    Make the simple argparser.
    """
    parser = argparse.ArgumentParser(description='Manage gopro vids.')
    parser.add_argument('inputs', nargs='*', help='The input videos to concatenate, must be mp4s.')
    parser.add_argument('-o', '--output', nargs='?', help='The output merged video.')
    parser.add_argument('-r', '--rename', action='store_true',
                        help='Only rename the files in order.')
    parser.add_argument('-u', '--update', action='store_true',
                        help='Update this script and exit.')

    return parser


def validate_paths(inputs, path_out):
    """
    Validate the input directory has videos
    and that the output directory is writable.

    Returns:
        (vids, merge_file)
            vids: The list of videos from input.
            merge_file: The output file to merge to.

    Raises:
        OSError - Any of a handful of conditions fail, see message.
    """
    if not inputs:
        raise OSError("No videos provided to concatenate.")

    try:
        inputs = [os.path.abspath(x) for x in inputs]
        for input in inputs:
            assert os.path.exists(input)
            assert input[-3:].lower() == 'mp4'
            if ' ' in input:
                print("Space detected in [{}], remove all spaces in video path.".format(input))
    except AssertionError:
        raise OSError("One or more of the inputs were bad. Please check.")

    vids = sorted(inputs, key=lambda x: os.stat(x).st_mtime)

    path_out = os.path.abspath(path_out)
    if not os.path.isdir(path_out):
        raise OSError("Path provided is not a directory or does not exist."
                      "    Output Path: " + path_out)

    short_date = datetime.datetime.now().strftime('%d_%m_%Y_%H%M%S')
    out_file = os.path.join(path_out, OUT_TEMPLATE.format(short_date))
    try:
        with open(out_file, 'w') as fout:
            fout.write("Test")
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass

    return vids, out_file


def main():
    args = make_parser().parse_args()

    if args.update:
        print("Updating the script ..... ", end="")
        resp = urllib.request.urlopen(UPDATE_URL)
        with open(os.path.abspath(__file__), 'wb') as fout:
            fout.write(resp.read())
        print("Done!")
        sys.exit(0)

    if args.output is None:
        print("Selecting current directory for merged file.")
        args.output = os.path.abspath(os.path.curdir)

    vids, out_file = validate_paths(args.inputs, args.output)
    expected_bytes = total_files_size(vids)

    resp = input(INFO.format(out_file, "\n    " + "\n    ".join(vids)))
    if not resp or resp.lower()[0] != 'y':
        print("Aborting merge now.")
        sys.exit(1)

    if args.rename:
        for cnt, vid in enumerate(vids):
            match = RENAME_TEST.match(os.path.basename(vid))
            vid_rename = os.path.join(os.path.dirname(vid),
                                      "{:03}__{}".format(cnt, match.group(2)))
            os.rename(vid, vid_rename)

        return

    # Default merge case
    try:
        proc = None
        proc, tfile = merge_vids(vids, out_file)
        wrapper(CursesUI(expected_bytes, out_file, proc))
    except KeyboardInterrupt:
        proc.kill()
        proc.returncode = 'kb'
        print("Merge aborted, deleting partial merge file.")
        try:
            os.remove(out_file)
        except OSError:
            pass
    finally:
        if proc and proc.returncode not in [0, 'kb']:
            print("For details on error please see: /tmp/merge.log")
        try:
            os.remove(tfile)
        except OSError:
            pass


if __name__ == "__main__":
    main()
