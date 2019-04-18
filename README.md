# GoPro Merge Program

A friend recently bought a GoPro to record bike rides.
He uses linux and didn't like their app to stitch the videos together and put them on his computer.
This program scans for mp4s in a folder and merges them in the correct order (by last modification).

## How To Use

- Download and put `concat_go.py` on your `$PATH`.
- You can `chmod u+x` it or just run it with python.
- The only argument is the path to where you put the mp4 files.

    i.e. `concat_go.py ./path/to/vids`

- The merged video will be placed in the current working directory.
- The program will rmember the last used directory so on subsequent
  runs you can just invoke it with `concat_go.py`.

## Requirements

- Python 2.7+
- ffmpeg
- curses (for simple progress UI)
