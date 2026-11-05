#!/usr/bin/env python3
"""去绿边 + 补破洞 + 删残线：把抠像后的素材修到能直接上屏。

三个缺陷，各自对应一类像素：

1. **绿溢色（edge fringe）**：抠像判「是不是绿色色相」，落在绿区边缘的混合像素被判成不透明，
   颜色里却还留着绿分量；再加上 VP9 的 yuva420p 会二次采样色度，绿幕颜色渗进角色边缘 1-2 像素。
   → 做法：**边缘颜色外推**——把整帧的 RGB 换成最近的「干净像素」（实心且不是绿得过头）的颜色。
   连完全透明的背景区域也要换：4:2:0 会在 2x2 块上平均色度，透明区域里残留的绿色会渗进柔光边缘。

2. **角色身上的破洞**：模型偶尔在角色身上画出一块绿（实测皮卡丘的胸口），抠像后那块变成透明洞，
   在浅色页面上看起来就是「身上有个白斑」。
   → 做法：**填内部空洞**——把轮廓内部被透明像素围起来的区域，按最近的干净像素颜色补上。

3. **画幅边缘的残线**：抠像没抠干净的绿幕边条（右边 x=635..637 的竖线、底边 y=358..360 的横线），
   缩放后变成 1-3 像素的细线飘在宠物旁边。
   → 做法：**删掉贴着画幅边的细长连通块**（角色本身永远不贴边，删掉的都是残渣）。

用法：
  python3 despill_step.py <输入目录> <输出目录> [--keep-thin]

  --keep-thin：带道具的片子用（鱼竿、眼镜框本身是细长的独立块，默认规则会删掉它们）。
  这时只删「绿得过头的」或「贴着画幅边的」细块，画面中部的细道具保留。
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

W, H = 640, 360
ALPHA_MIN = 64         # 「看得见」的 alpha 下限
GREEN_MARGIN = 18      # 绿色通道要高出红蓝这么多才算「绿得过头」
HOLE_MAX_RATIO = 0.35  # 空洞面积 / 轮廓面积：超过这个就不填（那多半是真的缝，不是破洞）
THIN_MAX = 4           # 连通块的最短边 ≤ 这个算「细线」（残线）
NEAR_PX = 4            # 角色周围多少像素内算「近」（道具边缘的绿晕要盖住，2 不够）
BORDER_PX = 12         # 离画幅边缘多少像素内算「贴边」（残线所在）
BRIDGE_K = 13          # 细长道具的碎段桥接：向外的膨胀核大小


def decode(path):
    cmd = ['ffmpeg', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(path),
           '-f', 'rawvideo', '-pix_fmt', 'rgba', '-']
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    size = W * H * 4
    n = len(raw) // size
    return np.frombuffer(raw[:n * size], dtype=np.uint8).reshape(n, H, W, 4)


def despill_frame(buf, keep_thin: bool = False):
    rgb = buf[..., :3].astype(np.float32)
    alpha = buf[..., 3].astype(np.float32)
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    greenish = (G > R + GREEN_MARGIN) & (G > B + GREEN_MARGIN)

    opaque = alpha >= ALPHA_MIN
    if not opaque.any():
        return buf
    clean = opaque & ~greenish
    if not clean.any():
        clean = opaque

    # 最近的干净像素（EDT 直接给出它的坐标）
    _, indices = ndimage.distance_transform_edt(~clean, return_indices=True)
    iy, ix = indices[0], indices[1]
    near_rgb = rgb[iy, ix]

    # 1) 边缘颜色外推：只把**角色周围 2 像素内**的像素换成最近干净像素的颜色，远处保持原样。
    #    为什么是 2 像素：VP9 的 yuva420p 把色度按 2x2 块平均，角色边缘像素所在的块
    #    最多带 1 个背景像素。把角色周围 2 像素都换成角色本色，块里就不再有绿，
    #    色度二次采样也渗不进来。
    #    为什么远处不换：远处全是透明背景，渲不出来；而整帧换成角色色会让透明区域带着
    #    角色的颜色，编码体积翻几倍（实测 189KB → 888KB）。
    dist = ndimage.distance_transform_edt(~clean)
    near_region = dist <= NEAR_PX
    out_rgb = np.where(near_region[..., None], near_rgb, rgb)

    # 2) 填内部空洞：轮廓内部被透明像素围起来的区域（模型在角色身上画了绿）
    filled = ndimage.binary_fill_holes(opaque)
    holes = filled & ~opaque
    if holes.any():
        labels, count = ndimage.label(holes)
        solid_area = int(opaque.sum())
        keep = np.zeros_like(holes)
        for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
            if sl is None:
                continue
            region = labels[sl] == idx
            area = int(region.sum())
            if solid_area > 0 and area <= solid_area * HOLE_MAX_RATIO:
                keep[sl] |= region
        if keep.any():
            out_rgb = np.where(keep[..., None], near_rgb, out_rgb)
            alpha = np.where(keep, 255.0, alpha)

    # 3) 删掉细长连通块（残线）。
    #    默认「最短边 <= 4px 的独立块一律删」——残线就是这么来的，删干净最省心。
    #    但道具（鱼竿、眼镜框）本身就是细长的独立块，一刀切会把它们也删掉；
    #    这种片子用 keep_thin=True：改成只删「绿得过头的」或「贴着画幅边的」。
    labels, count = ndimage.label(opaque)
    thin_union = np.zeros_like(opaque)
    if count and not keep_thin:
        drop = np.zeros_like(opaque)
        for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
            if sl is None:
                continue
            ys, xs = sl
            if min(ys.stop - ys.start, xs.stop - xs.start) <= THIN_MAX:
                drop[sl] |= labels[sl] == idx
        if drop.any():
            alpha = np.where(drop, 0.0, alpha)
    elif count:
        drop = np.zeros_like(opaque)
        for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
            if sl is None:
                continue
            ys, xs = sl
            if min(ys.stop - ys.start, xs.stop - xs.start) > THIN_MAX:
                continue
            region = labels[sl] == idx
            is_green = bool(greenish[sl][region].any())
            near_border = (
                ys.start <= BORDER_PX
                or xs.start <= BORDER_PX
                or ys.stop >= H - BORDER_PX
                or xs.stop >= W - BORDER_PX
            )
            if is_green or near_border:
                drop[sl] |= region
            else:
                # 画面中部的细长道具（鱼竿、眼镜框）：先留着，
                # 下面再把它们的碎段桥接成连续的一根。
                thin_union[sl] |= region
        if drop.any():
            alpha = np.where(drop, 0.0, alpha)
        if thin_union.any():
            # 桥接：模型画的鱼竿只有 1-2 像素宽，抠像与 4:2:0 色度二次采样之后
            # 整根杆是「实心段 + 半透明段」交替，看着像断成一节节。
            # 把碎段向外扩一圈，把这一片区域里所有**非全透明**的像素都提为不透明，
            # 杆就连续了（只动道具那片区域，角色本体一点不碰）。
            near = ndimage.binary_dilation(thin_union, structure=np.ones((BRIDGE_K, BRIDGE_K)))
            alpha = np.where(near & (alpha > 0), 255.0, alpha)
    elif count:
        drop = np.zeros_like(opaque)
        for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
            if sl is None:
                continue
            ys, xs = sl
            if min(ys.stop - ys.start, xs.stop - xs.start) > THIN_MAX:
                continue
            region = labels[sl] == idx
            is_green = bool(greenish[sl][region].any())
            near_border = (
                ys.start <= BORDER_PX
                or xs.start <= BORDER_PX
                or ys.stop >= H - BORDER_PX
                or xs.stop >= W - BORDER_PX
            )
            if is_green or near_border:
                drop[sl] |= region
        if drop.any():
            alpha = np.where(drop, 0.0, alpha)

    out = buf.copy()
    out[..., :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    return out


def process(path, out_dir, keep_thin: bool = False):
    frames = decode(path)
    out = np.stack([despill_frame(f, keep_thin) for f in frames])
    dest = Path(out_dir) / path.name
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba',
           '-s', f'{W}x{H}', '-r', '24', '-i', '-',
           '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', '40', '-b:v', '0',
           '-row-mt', '1', '-auto-alt-ref', '0', '-deadline', 'good', '-cpu-used', '4', str(dest)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    p.communicate(out.tobytes())
    return frames.shape[0]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[0]).expanduser()
    out_dir = Path(argv[1]).expanduser()
    keep_thin = '--keep-thin' in argv
    out_dir.mkdir(parents=True, exist_ok=True)
    clips = sorted(src.glob('*.webm'))
    if not clips:
        print('no webm in', src)
        return 1
    for clip in clips:
        n = process(clip, out_dir, keep_thin)
        print('  %-28s %3d frames -> %s' % (clip.name, n, out_dir / clip.name), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
