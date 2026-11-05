"""Unify character size across step02 videos into step03.

整帧等比缩放 + overlay 平移到 2160x1215（16:9）透明画布：
- 站立高度 900（按首尾站立帧的平均高度计算缩放比例）
- 水平居中，脚底对齐（按全帧内容最低点对齐，保证动画不裁剪）
- 不裁剪人物/动作内容，底部超出的透明空白直接裁掉
- 画布 2160x1215 与原始视频同为 16:9，宽度容纳最宽动作（2015px）
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "step02"
OUT = ROOT / "step03"
# 统一使用工作区自带的 ffmpeg（素材处理链零第三方依赖）

# 素材处理链的 ffmpeg 定位：优先用仓库自带的构建，缺失时回落到 PATH 上的 ffmpeg。
# 原先这里写死了 Windows 构建路径，在 macOS/Linux 上仓库没有 .tools/ 就完全跑不起来。
def _tool(name: str) -> str:
    bundled = ROOT / '.tools' / 'ffmpeg-9.0.1-essentials_build' / 'bin' / (name + '.exe')
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    return found if found else str(bundled)


FFMPEG = _tool('ffmpeg')
FFPROBE = _tool('ffprobe')

PARALLEL = 4
CANVAS_W = 2160  # 16:9：2160 = 1215 * 16/9，与原始视频同比例
CANVAS_H = 1215
TARGET_HEIGHT = 900
FEET_Y = CANVAS_H - 100  # 距底 100
EDGE_MARGIN = 0.02  # 内容离画幅边缘的安全余量（占画幅比例）

SRC_W = 1280
SRC_H = 720
FPS = 24
HEAD_FRAMES = 5
TAIL_SEEK = -0.2  # 从末尾取帧，避免取到收尾动作

_BBOX_RE = re.compile(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)")


def scan_bbox(video: Path, seek: float | None = None, frames: int | None = None,
                min_val: int = 64) -> list[tuple[int, int, int, int]]:
    """用 alphaextract,bbox 滤镜扫描帧内容边界，返回 [(x1, x2, y1, y2)] 列表。

    min_val 是 alpha 的可见门槛。默认 64（= alpha>63，「看得见」）：
    抠像后画幅边缘常留一层极淡的残边，用滤镜自带的默认值（16）会把残边也算进内容范围，
    于是并集被撑满整个画幅、缩放被过度压缩，角色在不同动作之间大小不一致
    （实测 idle-march 的并集被撑到 0..1279，角色缩到只剩正常的一半大）。
    """
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "info", "-c:v", "libvpx-vp9"]
    if seek is not None:
        cmd += ["-sseof", str(seek)]
    cmd += ["-i", str(video)]
    if frames is not None:
        cmd += ["-frames:v", str(frames)]
    cmd += ["-vf", f"alphaextract,bbox=min_val={min_val}", "-f", "null", "-"]
    # text=True 时显式指定 UTF-8 解码（Windows 默认 GBK 会解不了 ffmpeg 的 UTF-8 输出）
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return [tuple(int(g) for g in m.groups()) for m in _BBOX_RE.finditer(result.stderr)]


def read_alpha_frames(video: Path, seek: float | None = None, frames: int | None = None) -> list[np.ndarray]:
    """解码指定帧的 alpha 通道（每帧 H×W uint8 数组）。"""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-c:v", "libvpx-vp9"]
    if seek is not None:
        cmd += ["-sseof", str(seek)]
    cmd += ["-i", str(video)]
    if frames is not None:
        cmd += ["-frames:v", str(frames)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    frame_size = SRC_W * SRC_H * 4
    out: list[np.ndarray] = []
    while True:
        buf = b""
        while len(buf) < frame_size:
            chunk = p.stdout.read(frame_size - len(buf))
            if not chunk:
                break
            buf += chunk
        if len(buf) < frame_size:
            break
        out.append(np.frombuffer(buf, np.uint8).reshape(SRC_H, SRC_W, 4)[..., 3])
    p.stdout.close()
    p.wait()
    return out


def measure_standing(video: Path) -> dict:
    """首尾各 HEAD_FRAMES 帧站立姿态。

    水平中心用非透明像素 x 的中位数（防手/零食等扩展物把 bbox 中心拉偏），
    垂直基准用 bbox（y 方向扩展物干扰小，bbox 本身可靠）。
    """
    alphas = read_alpha_frames(video, frames=HEAD_FRAMES) + read_alpha_frames(video, seek=TAIL_SEEK, frames=HEAD_FRAMES)
    med_xs, heights, max_ys = [], [], []
    for a in alphas:
        ys, xs = np.where(a > 10)
        if len(xs) == 0:
            continue
        med_xs.append(float(np.median(xs)))
        heights.append(int(ys.max() - ys.min() + 1))
        max_ys.append(int(ys.max()))
    if not med_xs:
        raise RuntimeError(f"No opaque pixels found in {video.name}")
    return {
        "height": sum(heights) / len(heights),
        "max_y": sum(max_ys) / len(max_ys),
        "center_x": sum(med_xs) / len(med_xs),
    }


def measure_content_union(video: Path) -> tuple[int, int, int, int]:
    """全帧扫描内容范围并集 (x1, y1, x2, y2)，用于校验动画内容是否被裁。

    只算「实体内容」，不算残留：
    - alpha >= 64 才是看得见的；
    - 开运算去掉 1-2 像素宽的残留线（画幅边缘常有一圈极淡的残边）；
    - 连通块面积小于画幅 0.5% 的碎片忽略（噪点）。

    为什么不用 ffmpeg 的 bbox 滤镜（min_val 已经调到 64 仍然不够）：
    残留线的像素够亮，min_val 滤不掉；并集被撑满整幅 -> 缩放被过度压缩，
    角色在不同动作之间大小不一致（实测 idle-march / act-spin 被压到只有正常的一半大）。
    """
    w, h = SRC_W, SRC_H
    cmd = [
        FFMPEG, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(video),
        "-f", "rawvideo", "-pix_fmt", "rgba", "-",
    ]
    raw = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    size = w * h * 4
    if not raw or len(raw) < size:
        raise RuntimeError(f"Cannot decode frames from {video.name}")
    frames = len(raw) // size
    x1, y1, x2, y2 = w, h, -1, -1
    min_area = w * h * 0.005
    for i in range(frames):
        buf = raw[i * size:(i + 1) * size]
        alpha = np.frombuffer(buf, dtype=np.uint8)[3::4].reshape(h, w)
        vis = alpha >= 64
        if not vis.any():
            continue
        vis = ndimage.binary_opening(vis, structure=np.ones((3, 3)))
        labelled, count = ndimage.label(vis)
        if count == 0:
            continue
        for idx, sl in enumerate(ndimage.find_objects(labelled), start=1):
            if sl is None:
                continue
            ys, xs = sl
            area = int((labelled[sl] == idx).sum())
            if area < min_area:
                continue
            x1 = min(x1, xs.start)
            y1 = min(y1, ys.start)
            x2 = max(x2, xs.stop - 1)
            y2 = max(y2, ys.stop - 1)
    if x2 < 0:
        raise RuntimeError(f"No opaque pixels found in {video.name}")
    return (x1, y1, x2, y2)


def fit_scale(standing: dict, union: tuple[int, int, int, int]) -> float:
    """求一个「任何一帧都不出画幅」的缩放系数。

    原来的缩放只看首尾的站立帧（measure_standing），于是**动作里比站立更高的那些帧
    （举手过头、跳跃、歪头）会溢出画幅顶部被切掉**——角色缺耳朵、头顶的特效被切一半。
    实测 12 段素材里 7 段中招，而且裁切是间歇性的（只在某些帧出现），看缩略图很容易漏掉。

    做法：把「所有帧的内容并集」也当作约束。缩放 s 时，并集在画布上的位置是
      X = CANVAS_W/2 + (union_x - center_x) * s     （站立角色水平居中）
      Y = FEET_Y      + (union_y - max_y)  * s     （站立脚底贴 FEET_Y）
    要求这四个边界都在画布内，反解出 s 的上限，取最小值。
    """
    scale = TARGET_HEIGHT / standing["height"]
    cx = standing["center_x"]
    my = standing["max_y"]
    x1, y1, x2, y2 = union
    limits = []
    # 安全余量：内容不只要「在画幅内」，还要离边缘有一段距离——
    # 正好压在 y=0 上时，任何一次缩放取整都会再削掉一行像素。
    margin_x = CANVAS_W * EDGE_MARGIN
    margin_y = CANVAS_H * EDGE_MARGIN
    # 水平：并集左右两侧都要留在画幅内
    for span in (cx - x1, x2 - cx):
        if span > 0:
            limits.append((CANVAS_W / 2 - margin_x) / span)
    # 垂直向上：最高点不能越过上沿
    up = my - y1
    if up > 0:
        limits.append((FEET_Y - margin_y) / up)
    # 垂直向下：最低点不能越过下沿
    down = y2 - my
    if down > 0:
        limits.append((CANVAS_H - FEET_Y - margin_y) / down)
    for limit in limits:
        if limit < scale:
            scale = limit
    return scale


def build_filter(scale: float, standing: dict) -> str:
    """整帧缩放 + overlay 平移到透明画布，站立水平居中、脚底对齐 FEET_Y。"""
    scaled_w = int(SRC_W * scale) // 2 * 2
    scaled_h = int(SRC_H * scale) // 2 * 2
    overlay_x = CANVAS_W / 2 - standing["center_x"] * scale
    overlay_y = FEET_Y - standing["max_y"] * scale
    return (
        f"color=c=black@0:s={CANVAS_W}x{CANVAS_H}:r={FPS}[bg];"
        f"[0:v]scale={scaled_w}:{scaled_h}[sc];"
        f"[bg][sc]overlay={overlay_x:.1f}:{overlay_y:.1f}:shortest=1,format=yuva420p[v]"
    )


def convert_video(src: Path, dst: Path, filter_complex: str) -> None:
    cmd = [
        FFMPEG,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-c:v",
        "libvpx-vp9",  # 关键：libvpx 解码才能保留 VP9 alpha
        "-i",
        str(src),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libvpx-vp9",
        "-crf",
        "30",
        "-b:v",
        "0",
        "-auto-alt-ref",
        "0",
        "-deadline",
        "good",
        "-cpu-used",
        "4",
        "-c:a",
        "libopus",
        "-b:a",
        "128k",
        str(dst),
    ]
    result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())


def _is_valid(dst: Path, src: Path, min_size: int = 50_000) -> bool:
    """断点续跑完整性检查：存在、够大、不比源旧、且能被 ffprobe 读到视频流。"""
    if not dst.exists() or dst.stat().st_size <= min_size:
        return False
    if dst.stat().st_mtime < src.stat().st_mtime:
        return False
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_name",
                        "-of", "csv=p=0", str(dst)], capture_output=True)
    return bool(r.stdout.strip())


def _process_one(video: Path) -> tuple[dict, bool]:
    """处理单个视频（worker 函数）：测量 + 转码（或跳过转码），返回 entry。

    注意：entry 必须可 JSON 序列化（params.json 由主进程汇总写入）。
    """
    dst = OUT / (video.stem + ".webm")
    # 断点续跑：完整输出已存在 → 跳过转码（但仍测量，保证 params.json 完整）
    skip = _is_valid(dst, video)
    standing = measure_standing(video)
    union = measure_content_union(video)
    # 缩放必须同时满足「站立姿态的比例」与「全帧内容并集不出画幅」——
    # 只按站立帧算，动作里更高的帧（举手/跳跃/歪头）会溢出顶部被切掉。
    scale = fit_scale(standing, union)
    entry = {
        "file": video.name,
        "standing": {k: round(v, 1) for k, v in standing.items()},
        "content_union": {"x1": union[0], "y1": union[1], "x2": union[2], "y2": union[3]},
        "scale": round(scale, 6),
    }
    if not skip:
        filter_complex = build_filter(scale, standing)
        convert_video(video, dst, filter_complex)
    return entry, skip


def main() -> int:
    OUT.mkdir(exist_ok=True)
    videos = sorted(SRC.glob("*.webm"))
    if not videos:
        print(f"No WebM files found in {SRC}")
        return 1

    payload = {"canvas": f"{CANVAS_W}x{CANVAS_H}", "target_height": TARGET_HEIGHT, "feet_y": FEET_Y, "videos": []}
    total = len(videos)
    with ProcessPoolExecutor(max_workers=PARALLEL) as ex:
        for index, (entry, skip) in enumerate(ex.map(_process_one, videos), start=1):
            payload["videos"].append(entry)
            status = "SKIP" if skip else "OK"
            print(f"[{index}/{total}] {entry['file']} {status} (scale={entry['scale']})", flush=True)

    (OUT / "params.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Done. {total} videos written to {OUT} (parallel={PARALLEL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
