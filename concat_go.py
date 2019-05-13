#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GoPro stores video files split into smaller files.
Sort the videos into order and merge them into a single mp4.
This assumes all vieos in the directory are part of the same video.

Stores last used dir in: $HOME/.config/concat_gorc
"""
from __future__ import print_function

from curses import wrapper
import datetime
import glob
import math
import os
import subprocess
import sys
import tempfile
import time

USAGE = """
Usage: {} INPUT_DIR [OUTPUT_DIR]

    INPUT_DIR: A path to a folder with mp4 videos to combine, will scan inside.
    OUTPUT_DIR: The optional folder where the merged video will be written to.
                If omitted, the merged file will be in the current directory.
"""
OUT_TEMPLATE = 'merged_{}.mp4'
FFMPEG_CMD = 'ffmpeg -f concat -safe 0 -i {} -c copy {}'
PROGRESS_MSG = """Merge MP4 Status
----------------

Output File: {}
Size (MB): {:10,}/{:,}
Completion: {:3.2f}%
Estimated Time Remaining: {}
"""


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
        self.data = list(reversed(list(reversed(self.data))[:self.window]))

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
        estimate = 'N/A'
        self.estimator.add_data(cur_bytes)
        estimate = self.estimator.new_estimate()

        msg = PROGRESS_MSG.format(self.output_file, cur_mb,
                                  self.expected_mb, percent, estimate)
        msg += draw_progress(percent)

        return msg


def draw_progress(percent, symbol='=', ticks=50):
    done = int(math.floor((percent / 100) * ticks))
    not_done = ticks - done

    return '[{}{}]'.format(symbol * done, ' ' * not_done)


def cmp_vids(vid1, vid2):
    stat1 = os.stat(vid1).st_mtime * 1000000
    stat2 = os.stat(vid2).st_mtime * 1000000

    return int(stat1 - stat2)


def find_vids(full_path):
    """ Matches any mp4 vids in the directory. Sorted by last modification. """
    vids = []
    for ext in ['mp', 'Mp', 'mP', 'MP']:
        vids += glob.glob(os.path.join(full_path, '*.{}4'.format(ext)))

    return sorted(vids, cmp_vids)


def total_files_size(files):
    total = 0
    for fname in files:
        total += os.stat(fname).st_size

    return total


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


def main():
    if len(sys.argv) < 2:
        print(USAGE.format(sys.argv[0]))
        sys.exit(1)

    in_dir = os.path.abspath(sys.argv[1])
    if not os.path.isdir(in_dir):
        print("Path provided is not a directory or does not exist.")
        print("    Input Path: " + in_dir)
        sys.exit(1)

    short_date = datetime.datetime.now().strftime('%d_%m_%Y_%H%M%S')
    out_file = OUT_TEMPLATE.format(short_date)
    try:
        out_dir = os.path.abspath(sys.argv[2])
        if not os.path.isdir(os.path.join(os.path.abspath(sys.argv[2]))):
            print("Path provided is not a directory or does not exist.")
            print("    Output Path: " + out_dir)
            sys.exit(1)
        out_file = os.path.join(out_dir, out_file)
    except IndexError:
        print("Selecting current directory for merged file.")
    print('Combined mp4 will be written to: ' + out_file)

    vids = find_vids(in_dir)
    if not vids:
        print('Found no videos in: ' + in_dir)
        sys.exit(1)
    expected_bytes = total_files_size(vids)

    try:
        proc = None
        proc, tfile = merge_vids(vids, out_file)
        wrapper(CursesUI(expected_bytes, out_file, proc))
    except KeyboardInterrupt:
        proc.kill()
        proc.returncode = -1
        print("Merge aborted, deleting partial merge file.")
    finally:
        if proc and proc.returncode != 0:
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
