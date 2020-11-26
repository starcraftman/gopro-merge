#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GoPro stores video files split into smaller files.
Sort the videos into order and merge them into a single mp4.
This assumes all vieos in the directory are part of the same video.
"""
from __future__ import print_function

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


class RateEstimator(object):
    """
    Rate estimate based on progress over a window.
    """
    def __init__(self, expected_size, window=3):
        self.data = []
        self.expected_size = expected_size
        self.window = window

    def add_data(self, new_size):
        self.data += [(new_size, datetime.datetime.now())]
        while len(self.data) > self.window:
            self.data = self.data[1:]

    def new_estimate(self):
        old = self.data[0]
        latest = self.data[-1]
        size_change = latest[0] - old[0]
        if size_change <= 0:
            return 'N/A'

        delta_time = (latest[1] - old[1]).total_seconds()
        size_left = self.expected_size - latest[0]
        secs_left = max(0, (size_left / size_change)) * delta_time

        return datetime.timedelta(seconds=secs_left)


class CursesUI(object):
    """
    Curses manager to update user via cuses ui on merging progress.
    Blocking since I don't need to run more than the one command.
    """
    def __init__(self, expected_bytes, output_file, proc):
        self.expected_bytes = expected_bytes
        self.expected_mb = expected_bytes / (1024 ** 2)
        self.output_file = output_file
        self.proc = proc
        self.estimator = RateEstimator(expected_bytes)

    def __call__(self, stdscr):
        stdscr.clear()
        stdscr.addstr(self.check_file())

        self.proc.poll()
        while self.proc.returncode is None:
            stdscr.clear()
            stdscr.addstr(self.check_file())
            stdscr.refresh()

            time.sleep(0.15)
            self.proc.poll()

    def check_file(self):
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
    done = int(math.floor((percent / 100) * ticks))
    not_done = ticks - done

    return '[{}{}]'.format(symbol * done, ' ' * not_done)


def total_files_size(files):
    total = 0
    for fname in files:
        total += os.stat(fname).st_size

    return total


# FIXME: Not sure why spaces in tempfile crash ffmpeg.
def merge_vids(vids, out_file):
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
    parser.add_argument('inputs', nargs='+', help='The input files to concatenate.')
    parser.add_argument('-o', '--output', nargs='?', help='The output directory to store merged file. Defaults to current dir.')
    parser.add_argument('-r', '--rename', action='store_true',
                        help='Only rename the files.')

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
    parser = make_parser()
    args = parser.parse_args()
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

    else:
        try:
            proc = None
            proc, tfile = merge_vids(vids, out_file)
            wrapper(CursesUI(expected_bytes, out_file, proc))
        except KeyboardInterrupt:
            proc.kill()
            proc.returncode = 'kb'
            print("Merge aborted, deleting partial merge file.")
        finally:
            if proc and proc.returncode not in [0, 'kb']:
                print("For details on error please see: /tmp/merge.log")
                try:
                    os.remove(out_file)
                except OSError:
                    pass
            try:
                os.remove(tfile)
            except OSError:
                pass


if __name__ == "__main__":
    main()
