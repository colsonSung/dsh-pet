#!/usr/bin/env python3
"""Normalise each clip's backdrop to a single pure green before keying.

The model does not paint the same green every time: one clip comes back with a
flat #00FF00 field, another with a teal, another with a washed-out pale green,
and sometimes it drops a shadow under the character. The plugin's keyer judges a
fixed HSV hue band (70-170), so only the flattest one keys cleanly. This rewrites
whatever the backdrop actually is into strict #00FF00.

The backdrop is estimated per frame from the border. A pixel counts as backdrop
when it is close to its row's edge colour, close to its column's edge colour, or
a darker shade of the same hue (that is the shadow).
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

VIDEOS = Path('/tmp/pokesprites/videos')
OUT = Path('/tmp/pokesprites/greenfix')
W, H = 1280, 720
CLOSE = 5
TOL = 62
HUE_COS = 0.90


def decode(path):
    cmd = ['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    out = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    n = len(out) // (W * H * 3)
    return np.frombuffer(out[:n * W * H * 3], dtype=np.uint8).reshape(n, H, W, 3)


def background_mask(frame):
    f = frame.astype(np.float32)
    row_bg = np.median(np.stack([f[:, 0], f[:, -1]], axis=1), axis=1)   # (H, 3)
    col_bg = np.median(np.stack([f[0], f[-1]], axis=0), axis=0)           # (W, 3)

    d_row = np.abs(f - row_bg[:, None, :]).max(axis=2)
    d_col = np.abs(f - col_bg[None, :, :]).max(axis=2)

    # Same hue but darker: that is the cast shadow the model paints.
    eps = 1e-3
    p_norm = f / (np.linalg.norm(f, axis=2, keepdims=True) + eps)
    b_norm = row_bg / (np.linalg.norm(row_bg, axis=1, keepdims=True) + eps)
    cos = (p_norm * b_norm[:, None, :]).sum(axis=2)
    hue_ok = cos > HUE_COS
    not_brighter = f.max(axis=2) < (row_bg.max(axis=1)[:, None] * 1.15)
    shadow = hue_ok & not_brighter

    mask = (d_row < TOL) | (d_col < TOL) | shadow
    # Keep only the regions that touch the border, so a colour inside the
    # character is never swallowed. This has to run before the closing:
    # closing erodes the outermost pixels, which would disconnect the
    # backdrop from the border samples and drop the whole thing.
    labelled, count = ndimage.label(mask)
    if count:
        border = set(np.unique(np.concatenate([labelled[0], labelled[-1], labelled[:, 0], labelled[:, -1]])))
        border.discard(0)
        mask = np.isin(labelled, list(border))
    # Close small holes so the backdrop is solid.
    mask = ndimage.binary_closing(mask, structure=np.ones((CLOSE, CLOSE)))
    return mask


def process(path):
    frames = decode(path)
    out = frames.copy()
    for i in range(frames.shape[0]):
        out[i][background_mask(frames[i])] = (0, 255, 0)
    dest = OUT / path.name
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-i', '-', '-c:v', 'libx264', '-crf', '16',
           '-pix_fmt', 'yuv420p', '-r', '25', str(dest)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    p.communicate(out.tobytes())
    return dest, frames.shape[0]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clips = sorted(VIDEOS.glob('*.mp4'))
    if not clips:
        print('  no clips')
        return 1
    for c in clips:
        dest, n = process(c)
        print('  %-24s %3d frames -> %s' % (c.name, n, dest.name), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
