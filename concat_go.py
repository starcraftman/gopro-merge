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

OUT_TEMPLATE = 'merged_{}.mp4'
FFMPEG_CMD = 'ffmpeg -f concat -safe 0 -i {} -c copy {}'
CACHE_FILE = os.path.expanduser('~/.config/concat_gorc')
PROGRESS_MSG = """Merge MP4 Status
----------------

Output File: {}
Size (MB): {:10,}/{:,}
Completion: {:3.2f}%
Time to Completion: {}
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
        secs_left = (size_left / size_change) * delta_time
        if secs_left < 0:
            secs_left = 0

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

            time.sleep(0.5)
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


def save_last_dir(cache, last_dir):
    try:
        os.makedirs(os.path.dirname(cache))
    except OSError:
        pass
    with open(cache, 'w') as fout:
        fout.write(last_dir)


def get_last_dir(cache):
    try:
        with open(cache) as fin:
            return fin.readline()
    except IOError:
        return None


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
        dnull = open('/tmp/merge.log', 'w')
        proc = subprocess.Popen(args, stdout=dnull,
                                stderr=subprocess.STDOUT)
        proc.poll()

        return proc, fout.name


def main():
    if len(sys.argv) != 2 and not get_last_dir(CACHE_FILE):
        print('Only argument is path to video files to concatenate')
        print('The last used dir is cached after first run. No args will use cache.')
        sys.exit(1)

    if len(sys.argv) == 2:
        full_path = os.path.abspath(sys.argv[1])
    else:
        full_path = get_last_dir(CACHE_FILE)

    if not os.path.exists(full_path) or not os.path.isdir(full_path):
        print("Path provided is not a directory or does not exist.")
        sys.exit(1)

    short_date = datetime.datetime.now().strftime('%d_%m_%Y_%H%M%S')
    out_file = OUT_TEMPLATE.format(short_date)
    print('Combined mp4 will be written to: ' + out_file)

    vids = find_vids(full_path)
    if not vids:
        print('Found no videos in: ' + full_path)
        sys.exit(1)
    expected_bytes = total_files_size(vids)

    try:
        proc, tfile = merge_vids(vids, out_file)
        wrapper(CursesUI(expected_bytes, out_file, proc))
        save_last_dir(CACHE_FILE, full_path)
    except KeyboardInterrupt:
        proc.kill()
        proc.returncode = -1
        print("Merge aborted, deleting partial merge file.")
    finally:
        if proc.returncode != 0:
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
