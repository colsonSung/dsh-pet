#!/usr/bin/env python3
"""Run the plugin's own material chain over the generated clips.

  video/*.mp4 -> step01/ -> step02/ (transparent) -> step03/ (2160x1215) -> step04/ (640x360)

step01 (watermark removal) is skipped: the MiniMax clips carry no watermark,
so the videos are copied into step01/ unchanged and the rest of the chain runs
exactly as the project defines it.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# The repository is wherever this file lives: the chain must run on any
# machine, not on the one that wrote it.
REPO = Path(__file__).resolve().parent.parent
# The clips to process: the first argument, or the green-fix folder below.
VIDEOS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/pokesprites/greenfix')


def run(cmd, label):
    print('--- %s' % label, flush=True)
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    tail = (r.stdout or '')[-900:]
    if r.returncode != 0:
        print('    FAILED rc=%s' % r.returncode)
        print((r.stderr or tail)[-1400:])
        return False
    print(tail.strip()[-700:] if tail.strip() else '    (ok, no output)')
    return True


def main():
    clips = sorted(VIDEOS.glob('*.mp4'))
    if not clips:
        print('no clips to process')
        return 1
    print('clips:', [c.stem for c in clips])

    video = REPO / 'video'
    step01 = REPO / 'step01'
    video.mkdir(exist_ok=True)
    if step01.exists():
        shutil.rmtree(step01)
    step01.mkdir(exist_ok=True)
    for c in clips:
        shutil.copy2(c, video / c.name)
        shutil.copy2(c, step01 / c.name)
    print('staged %d files into video/ and step01/' % len(clips))

    ok = run(['python3', 'scripts/chroma_step02.py'], 'chroma_step02 (green screen -> transparent)')
    if not ok:
        return 1
    ok = run(['python3', 'scripts/normalize_step03.py'], 'normalize_step03 (-> 2160x1215)')
    if not ok:
        return 1
    ok = run(['python3', 'scripts/encode_thumbs.py'], 'encode_thumbs (-> 640x360 webm)')
    if not ok:
        return 1

    out = REPO / 'step04'
    files = sorted(out.glob('*.webm'))
    print()
    print('produced %d webm in step04/' % len(files))
    for f in files:
        print('  %-28s %d KB' % (f.name, f.stat().st_size // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
