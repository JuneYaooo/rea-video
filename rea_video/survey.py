"""Survey: look at the whole video once, then look closer only where it needs it.

Round 1 lays frames of the whole video on one overview sheet of small tiles (index, how much the picture changes in
each gap, the cut detector's cuts marked): its only job is to find the shots, which small tiles do as well as large
ones. The tiles are placed by the change curve, half evenly and half where the picture changes, so a slow morph is
seen through and a still stretch costs few tiles. Every gap between two tiles gets a typed question. Gaps answered "transition" or "unsure" get a zoom
block in the next round, at a larger tile size: frames picked where the picture changes most, about every frame
through a transition; a transition the overview already showed closely, and a gap between two neighbouring frames
(nothing more to see), are not zoomed. Blocks are packed onto as few sheets as fit; sheets of a round are independent, so they can be
answered in parallel. At most three rounds. Then every shot is shown once at the closer size: its key frames are
picked and named, and how its picture was made is judged there, where the texture can be seen.

Every sheet is filled up to the size a model reads without shrinking it (SHEET_SIDE, SHEET_PIX): an image costs
about its pixel count, so the tile size, not the number of images, sets what a look costs.

Questions and answers follow the JEV shape: `state` holds the material, each question has `type`, `instructions`
and `criteria`; an answer is the chosen option and its probabilities (`"cut .9"`), no prose. Gaps that are plain
continuations and shots that need no change are left out of the answer, so an answer stays a few dozen tokens.

The result, survey/timeline.json, holds the scene changes (time, frame, kind, span of the transition, who found
it, probability), the stretches where a lot happens inside one shot, each shot's key frames and look, and the change
curve of the whole video (the rhythm). decompose reads it to split the shots and to pick each shot's key frames."""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .media import VideoInfo, iter_frames, video_info
from .shots import FrameTrack, Shot
from .util import fmt_time, read_json, write_json
from .visual import _font, _to_pil

VERSION = 4
# One sheet is one image a model takes in without shrinking it (Claude: 1568 px on the long side, about 1.15 MP; other
# readers are close). The image costs about its pixel count, so a sheet is filled to that size and no further, and
# what changes is how many tiles share it.
SHEET_SIDE, SHEET_PIX = 1568, 1_150_000
# Tile size per look, as an area (a portrait video gets tall tiles of the same area). The overview only has to tell
# one scene from the next, which small tiles do as well as large ones (120 px wide found every scene change of a fast
# 30 s edit, as 240 px did, at under half the cost; 64-80 px still found them, with the reader guessing); the closer
# looks judge how a transition is made and which frames are key, so their tiles are larger.
TILE_AREA = {"overview": 120 * 68, "zoom": 144 * 81, "detail": 144 * 81}
OVERVIEW_TILES = 240       # overview tiles at most; a longer video gets wider spacing
OVERVIEW_MIN, OVERVIEW_MAX = 0.33, 3.0  # overview spacing (s), set by how often the video changes (overview_every)
OVERVIEW_ACTIVE = 0.5      # share of the overview tiles placed by how much the picture changes (the rest evenly)
FINE_GAP = 0.25            # an overview gap this short is already a close look: a transition in it is not zoomed again
ZOOM_MAX = 18              # frames for one stretch looked at closer (two rows of zoom tiles)
ZOOM_SPAN = 4.0            # longest stretch one zoom block covers
MAX_ROUNDS = 3
RHYTHM_STEP = 0.25         # seconds per value of the change curve
SPEED_GRID = (12, 8)       # blocks the frame change is measured in (see speed())
KEY_MOVING = 0.025         # speed (see speed()) above which the picture counts as moving
KEY_MOVING_BUSY = 0.015    # ... inside stretches answered "busy"
KEY_LONG_MOVE = 0.5        # inside a long move, a key frame this often (s)
KEY_MAX = 12               # key frames per shot at most
DROP_TOOL_CUT_P = 0.85     # a detector cut is dropped only when its gap is explicitly answered "same" this sure

GAP_CRITERIA = {
    "same": "同一个镜头在继续：画面延续，只有小幅运动",
    "busy": "还是同一个主体 / 场景，只是变化多：动了、变大变小、变形、多了或少了小元素、镜头推近拉远但还是那个东西",
    "cut": "一刀硬切成了另一个主体 / 场景",
    "transition": "逐渐变成了另一个主体 / 场景（不是硬切）：A 形变成 B、推进到某处出现新场景、叠化、划像、甩镜等",
    "unsure": "看不出来，要在这段加密抽帧再看",
}
KEY_ROLES = {
    "first": "镜头 / 场景的第一帧",
    "last": "镜头的最后一帧（和下一镜衔接的样子）",
    "move_start": "动作或运镜开始",
    "move_end": "动作或运镜停下、到位",
    "extreme": "动作的转折 / 极值：反向、最远、最高、落地、最歪的那一下",
    "enter": "新元素（图形、人、物、文字、贴纸）出现，或刚完全展开",
    "exit": "元素离开 / 消失",
    "framing": "构图或景别变了（推近 / 拉远到位、主体换位置）",
    "expression": "表情或姿态的峰值",
    "transition_mid": "转场 / 形变进行到一半的样子",
    "light": "颜色、光线、底色突变（闪白、换底色、亮起）",
    "beat": "卡在节拍 / 音效上的画面变化",
}
DETAIL_INSTRUCTIONS = """你是动画原画师，在挑关键帧。图里每一块是一个镜头（标题写着 shot 编号和时间），格子是它的候选帧，左上角是格子编号（时间在 state 里）。
关键帧 = 用最少的帧把这段画面定下来，其余帧都能从它们插值出来：状态的起点、终点和转折点，不是"变了多少就取一张"。
格子多的镜头是工具认为动作多、要挑的；只有一两格的镜头一般直接接受。

按 JEV 格式回答，只回 JSON，不写解释：{"look": "code_render .9", "shots": {"shot_001": {...}, ...}}
- look：这张图上多数镜头的底层画面是怎么做出来的，从 looks 里选，写一次；个别镜头不一样，在那个镜头里写 "look": "ai_video .7"。
  这一步格子比总览大，看清楚质感：手绘描边是否逐帧抖动、纹理是否闪烁、物理是否合理、是不是同一套矢量风格。
- 候选帧已经够用、look 也和整张一样的镜头不用写（等于接受）。
- 要改的镜头写 frames 和 missing：frames 只写是关键帧的格子，"格子编号": "角色 概率"，例如 {"02": "extreme .8", "05": "enter"}，
  角色从 roles 里选；missing 写漏了关键帧的相邻两格，例如 ["03-04"]（动作在两格之间转折了、有元素一闪而过）。
- 第一格一般是 first；动作的转折和极值最重要，宁多勿漏。"""
ZOOM_INSTRUCTIONS = """你是视频节奏审阅员，这一轮是放大细看：图里每一块（标题写着段编号和时间范围）是上一轮要细看的地方，按变化最大的帧密集抽取，
转场里基本逐帧。格子左上角是编号（时间在 state 里），底部橙色条是到下一格画面变化多大，右边红色竖线是切镜检测器的切点。
gap 编号写成 段编号.NN，例如 r2_01.03 是这一段第 03 格和第 04 格之间。
先按顺序数清每一块里出现了哪几个主体 / 场景，写进 scenes：每一块一行，"格子编号 名称"，逗号分开，格子编号是这个东西第一次完整出现的那格，
例如 {"r2_03": "00 螺旋, 05 粒子圈, 11 向日葵"}；只有一个场景就写一个。再按它填 gaps：每换一次东西，换的那几个 gap 写 cut / transition。

"""
SOURCE_CRITERIA = {
    "live_action": "真实摄像机 / 手机实拍", "ai_video": "AI 生成视频（形变、纹理闪烁、物理不合理）", "avatar": "数字人口播",
    "cg_3d": "3D 渲染（Blender / C4D / UE，几何干净、光影一致）",
    "code_render": "代码 / 模板渲染：MG 动效、矢量图形、粒子、图表、按参数生成的动画（含手绘质感的矢量动画）",
    "screen_capture": "录屏 / 截图", "still_motion": "一张静图推拉", "static_hold": "静帧", "anim_2d": "2D 逐帧手绘 / 骨骼动画",
    "stop_motion": "定格动画（实物逐帧拍）", "film_footage": "剪进来的影视片段",
}
KINDS = {"cut": "硬切", "dissolve": "叠化", "morph": "形变：上一画面的图形直接变成下一画面", "zoom": "推进 / 拉出进入新画面",
         "wipe": "划像", "slide": "推移", "whip": "甩镜", "fade": "经黑场 / 白场", "match": "匹配剪辑（形状或动作接上）",
         "effect": "其他转场特效"}

INSTRUCTIONS = """你是视频节奏审阅员。这一步只找镜头怎么切分：有多少个镜头 / 场景、在哪里换、怎么换；不判断画面是怎么做出来的（后面逐镜细看时再判断）。
图里是按时间排开的帧，格子故意很小，够分辨场景就行；每格左上角是编号（时间在 state.times 里）。格子不是等距的：画面变化多的地方密，
平稳的地方稀。格子之间叫 gap，
编号 gNN 表示第 NN 格和下一格之间。格子底部的橙色条是这段里画面变化有多大（越长越大），右边红色竖线表示切镜检测器在这段里找到了切点。

按 JEV 格式回答：只回 JSON，不写解释。
- gaps：每个 gap 从 criteria 里选一项，简写成 "选项 [kind] 概率"，例如 {"g06": "transition zoom .85", "g09": "cut", "g12": "busy .7"}；
  是 "same" 的 gap 不用写，但画了红线的 gap 必须写。选 cut / transition 的，kind 从 kinds 里选（太小看不出是哪种就写 unsure，下一轮放大看）。
  一个转场跨几个 gap 时，这几个 gap 的 kind 写成一样；紧接着又是另一个转场（A 变成 B，B 马上又变成 C），换一个 kind，或者在 B 停留的那格写 busy。
- busy 还是 transition，只问一句：这段结束时画面的主体或场景，还是开始时那个东西吗？还是同一个（只是动了、变大、变形、多了点东西）→ busy；
  变成了另一个东西（向日葵变成鸟群、地球变成细胞、人物换成产品）→ transition。连着几次变成新东西，每次都算一次。
- 拿不准就选 unsure，会在那里逐帧放大再看一轮；不要猜。
- 宁可多报 transition / unsure，也不要漏掉换场景的地方：每个场景的第一帧都是关键帧。"""
GAP_RULES = INSTRUCTIONS[INSTRUCTIONS.index("按 JEV 格式回答"):].replace("（太小看不出是哪种就写 unsure，下一轮放大看）", "")


# ------------------------------------------------------------------ measurements -----------------------------------

def change_score(track: FrameTrack) -> np.ndarray:
    """Per-frame change from the previous frame, 0-1 (the cut detector's score)."""
    s = 0.6 * track.hist_dist + 0.4 * np.clip(track.pix_diff * 4.0, 0, 1)
    if len(s):
        s[0] = 0.0
    return s


def _t(track: FrameTrack, i: int) -> float:
    if track.times is not None and 0 <= i < len(track.times):
        return float(track.times[i])
    return i / track.fps


def frame_at(track: FrameTrack, t: float) -> int:
    if track.times is not None and len(track.times):
        return int(min(len(track.times) - 1, max(0, np.searchsorted(track.times, t - 1e-6))))
    return int(min(track.n - 1, max(0, round(t * track.fps))))


def speed(track: FrameTrack, a: int, z: int) -> np.ndarray:
    """How fast the picture moves at each frame of [a, z), 0-1: the change in the most-changed block of a 12 x 8 grid
    (a small subject moving counts as much as the whole frame), held over the animation's steps (drawings on twos or
    threes repeat frames) and smoothed."""
    T = track.thumbs

    def block_max(i: int) -> float:
        d = np.abs(T[i].astype(np.float32) - T[i - 1].astype(np.float32))
        return float(cv2.resize(d, SPEED_GRID, interpolation=cv2.INTER_AREA).max()) / 255.0
    raw = np.array([0.0] + [block_max(i) for i in range(a + 1, z)])
    hold = max(1, int(round(track.fps * 0.12)))
    held = np.array([raw[max(0, i - hold + 1):i + 1].max() for i in range(len(raw))])
    return np.convolve(held, np.ones(3) / 3, mode="same") if len(held) >= 3 else held


def key_frames(track: FrameTrack, a: int, z: int, busy: list[tuple[float, float]] | None = None, max_n: int = KEY_MAX,
               moving: float = KEY_MOVING, moving_busy: float = KEY_MOVING_BUSY) -> list[int]:
    """Key frames of [a, z): the frames that fix the motion, from which the rest can be in-betweened. The first and
    last frame; where each move starts and ends (the rest pose before, the pose it settles in); inside a move, the
    dips in speed (a turn, an extreme, a reversal); inside a long move, a frame every KEY_LONG_MOVE seconds. A still
    shot gets its first frame, a steady pan its two ends. Past max_n the least important go: small moves before
    big ones, the frames inside a move before its ends."""
    z = max(a + 1, min(z, track.n))
    if z - a <= 2:
        return list(range(a, z))
    sp = speed(track, a, z)
    hold = max(1, int(round(track.fps * 0.12)))
    busy = busy or []
    thr = np.array([moving_busy if any(b0 <= _t(track, a + i) < b1 for b0, b1 in busy) else moving for i in range(len(sp))])
    on = sp > thr
    cand: dict[int, float] = {a: 1e9}  # frame -> importance
    i = 0
    while i < len(on):
        if not on[i]:
            i += 1
            continue
        j = i
        while j < len(on) and on[j]:
            j += 1
        peak = float(sp[i:j].max())
        cand[a + max(0, i - 1)] = max(cand.get(a + max(0, i - 1), 0), peak)  # rest pose before the move
        end = min(len(on) - 1, max(i, j - hold + 1))  # where it settles (speed() holds each change for `hold` frames)
        cand[a + end] = max(cand.get(a + end, 0), peak)
        seg = sp[i:j]
        for k in range(1, len(seg) - 1):  # dips: the move turns or reaches an extreme
            lo, hi = max(0, k - 4), min(len(seg), k + 5)
            if seg[k] == seg[lo:hi].min() and seg[k] < 0.6 * min(seg[lo:k].max(initial=0), seg[k + 1:hi].max(initial=0)):
                cand[a + i + k] = max(cand.get(a + i + k, 0), 0.5 * peak)
        step = max(2, int(round(KEY_LONG_MOVE * track.fps)))
        for k in range(i + step, j - step // 2, step):  # a long move: its in-between poses every KEY_LONG_MOVE
            cand.setdefault(a + k, 0.3 * peak)
        i = j
    last = z - 1
    cand[last] = max(cand.get(last, 0), 1e8 if len(cand) > 1 else 0)
    out = sorted(f for f in cand if a <= f < z)
    if len(out) > max_n:
        # drop, one at a time, the frame that loses least: low importance and crowded by its neighbours, so the key
        # frames stay spread over the shot instead of piling up in its busiest second
        order = sorted(out, key=lambda f: cand[f])
        rank = {f: 0.3 + 0.7 * k / max(1, len(order) - 1) for k, f in enumerate(order)}
        while len(out) > max_n:
            w = [(rank[f] * min(out[k] - out[k - 1], out[k + 1] - out[k]), f) for k, f in enumerate(out) if 0 < k < len(out) - 1]
            out.remove(min(w)[1])
    if len(out) == 2 and float(sp.max()) <= float(thr.min()):  # nothing moves: the first frame says it all
        out = out[:1]
    return out


def rhythm(track: FrameTrack, step: float = RHYTHM_STEP) -> list[float]:
    """The change curve: the largest per-frame change in each `step` seconds (0-1)."""
    s = change_score(track)
    dur = _t(track, track.n - 1) + 1 / track.fps if track.n else 0.0
    out = []
    for k in range(int(math.ceil(dur / step))):
        a, z = frame_at(track, k * step), frame_at(track, (k + 1) * step)
        seg = s[a:max(a + 1, z)]
        out.append(round(float(seg.max()), 2) if len(seg) else 0.0)
    return out


# ------------------------------------------------------------------ sheets -----------------------------------------

def _grab(video: str, info: VideoInfo, times: list[float], width: int = 160) -> list[np.ndarray]:
    """Frames at the given times, one decode pass over the span they cover, keeping only the frame nearest each time
    (a whole video's overview never holds more than its tiles in memory)."""
    if not times:
        return []
    order = sorted(range(len(times)), key=lambda k: times[k])
    t0, t1 = times[order[0]], times[order[-1]]
    step = 1.0 / max(info.fps, 1)
    best: dict[int, tuple[float, np.ndarray]] = {}
    for i, f in enumerate(iter_frames(video, info, width, start=t0, duration=t1 - t0 + 2 * step)):
        ft = t0 + i * step
        for k in order:
            d = abs(ft - times[k])
            if d <= step and (k not in best or d < best[k][0]):
                best[k] = (d, f)
    if not best:
        return []
    got = [best.get(k, (0, None))[1] for k in range(len(times))]
    fill = next(f for f in got if f is not None)
    return [f if f is not None else fill for f in got]


def tile_size(info: VideoInfo, look: str) -> tuple[int, int]:
    """Tile width and height for a look (TILE_AREA), in the video's shape."""
    aspect = info.width / info.height if info.width and info.height else 16 / 9
    w = max(40, int(round(math.sqrt(TILE_AREA[look] * aspect))))
    return w, max(24, int(round(w / aspect)))


def _cols(tile_w: int, n: int) -> int:
    return max(1, min(n, (SHEET_SIDE + 2) // (tile_w + 2)))


def _grid(frames: list[np.ndarray], labels: list[str], bars: list[float], cuts: list[bool], cols: int,
          tile_w: int) -> Image.Image:
    """Tiles in rows; under each tile a bar for the change in the gap after it; a red edge for detector cuts."""
    font = _font(15 if tile_w >= 200 else (13 if tile_w >= 110 else 11))
    cells = []
    for f, lab, bar, cut in zip(frames, labels, bars, cuts):
        im = _to_pil(f)
        im = im.resize((tile_w, max(1, int(round(im.height * tile_w / im.width)))))
        cell = Image.new("RGB", (tile_w, im.height + 8), (24, 24, 24))
        cell.paste(im, (0, 0))
        d = ImageDraw.Draw(cell)
        w = int(d.textlength(lab, font=font)) + 6
        d.rectangle([0, 0, w, font.size + 3], fill=(0, 0, 0))
        d.text((3, 1), lab, fill=(255, 255, 255), font=font)
        if bar > 0:
            d.rectangle([0, im.height + 2, int((tile_w - 2) * min(1.0, bar)), im.height + 6], fill=(245, 158, 11))
        if cut:
            d.rectangle([tile_w - 4, 0, tile_w - 1, im.height + 7], fill=(230, 30, 30))
        cells.append(cell)
    ch = max(c.height for c in cells)
    n = min(cols, len(cells))
    sheet = Image.new("RGB", (tile_w * n + 2 * (n - 1), int(math.ceil(len(cells) / cols)) * (ch + 2) - 2), (255, 255, 255))
    for k, c in enumerate(cells):
        sheet.paste(c, ((k % cols) * (tile_w + 2), (k // cols) * (ch + 2)))
    return sheet


def _save(img: Image.Image, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=85)
    return out


TITLE_H = 20


def _pack(blocks: list[Image.Image]) -> list[list[list[int]]]:
    """Blocks (each a grid under a title) laid left to right in rows, rows top to bottom, as many on one sheet as fit
    SHEET_SIDE x SHEET_PIX: [[row of block indexes, ...] per sheet]. Short shots share a row instead of each taking one."""
    rows: list[list[int]] = []
    width = 0
    for k, im in enumerate(blocks):
        if rows and width + 6 + im.width <= SHEET_SIDE:
            rows[-1].append(k)
            width += 6 + im.width
        else:
            rows.append([k])
            width = im.width
    sheets: list[list[list[int]]] = []
    w = h = 0
    for r in rows:
        rw = sum(blocks[k].width for k in r) + 6 * (len(r) - 1)
        rh = max(blocks[k].height for k in r) + TITLE_H + 4
        nw = max(w, rw)
        if sheets and h + rh <= min(SHEET_SIDE, SHEET_PIX / nw):
            sheets[-1].append(r)
            w, h = nw, h + rh
        else:
            sheets.append([r])
            w, h = rw, rh
    return sheets


def _sheet(rows: list[list[tuple[str, Image.Image]]], out: Path) -> Path:
    """Rows of titled blocks on one image."""
    font = _font(14)
    w = max(sum(im.width for _, im in r) + 6 * (len(r) - 1) for r in rows)
    h = sum(max(im.height for _, im in r) + TITLE_H + 4 for r in rows)
    sheet = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    y = 0
    for r in rows:
        x = 0
        for title, im in r:
            d.rectangle([x, y, x + im.width - 1, y + TITLE_H - 1], fill=(40, 70, 160))
            d.text((x + 4, y + 2), title, fill=(255, 255, 255), font=font)
            sheet.paste(im, (x, y + TITLE_H))
            x += im.width + 6
        y += max(im.height for _, im in r) + TITLE_H + 4
    return _save(sheet, out)


def _gap_bars(track: FrameTrack, times: list[float], score: np.ndarray, cut_frames: list[int]) -> tuple[list[float], list[bool]]:
    bars, cuts = [], []
    for k, t in enumerate(times):
        nxt = times[k + 1] if k + 1 < len(times) else _t(track, track.n - 1)
        a, z = frame_at(track, t) + 1, frame_at(track, nxt) + 1
        bars.append(float(score[a:z].max()) if z > a else 0.0)
        cuts.append(any(a <= c < z for c in cut_frames) and k + 1 < len(times))
    return bars, cuts


# ------------------------------------------------------------------ rounds -----------------------------------------

def _source(video: str, info: VideoInfo) -> dict:
    return {"path": str(video), "duration": round(info.duration, 3), "size": [info.width, info.height], "fps": round(info.fps, 3)}


def overview_every(track: FrameTrack, shots: list[Shot], dur: float) -> float:
    """Spacing of the overview tiles, from how often this video changes: about two tiles between two sudden changes
    (the detector's cuts or the change curve's spikes, whichever finds more), within OVERVIEW_MIN-OVERVIEW_MAX s and
    at most OVERVIEW_TILES tiles. A fast edit gets a dense overview, a slow talk a sparse one."""
    events = max(len(shots) - 1, spikes(track, 0.0, dur))
    every = min(OVERVIEW_MAX, max(OVERVIEW_MIN, dur / (events + 1) / 2))
    return max(every, dur / OVERVIEW_TILES)


def overview_times(track: FrameTrack, dur: float, n: int) -> list[float]:
    """Where the n overview tiles go, from the change curve (no AI needed): OVERVIEW_ACTIVE of them where the picture
    changes (a slow morph or dissolve gets tiles all through it, back-to-back cuts get a tile between them), the
    rest evenly (a still stretch is still seen)."""
    score = change_score(track)
    nf = len(score)
    if nf < 2:
        return [round((k + 0.5) * dur / n, 3) for k in range(n)]
    w = max(1, int(round(0.1 * track.fps)))  # the change spread over 0.1 s, so all of a transition counts
    act = np.array([score[max(0, i - w):i + w + 1].max() for i in range(nf)])
    act = np.clip(act - 0.03, 0, None)       # noise and slow drifts are not activity
    dens = np.full(nf, (1 - OVERVIEW_ACTIVE) / nf)
    dens += OVERVIEW_ACTIVE * (act / act.sum() if act.sum() > 0 else 1.0 / nf)
    cdf = np.cumsum(dens)
    idx = sorted({int(min(nf - 1, np.searchsorted(cdf, q))) for q in (np.arange(n) + 0.5) / n * cdf[-1]})
    return [round(_t(track, i), 3) for i in idx]


def overview_task(video: str, info: VideoInfo, track: FrameTrack, shots: list[Shot], sdir: Path) -> dict:
    dur = info.duration or _t(track, track.n - 1)
    n = max(8, int(round(dur / overview_every(track, shots, dur))))
    times = overview_times(track, dur, n)
    n = len(times)
    every = dur / n
    score = change_score(track)
    tw, th = tile_size(info, "overview")
    frames = _grab(video, info, times, width=tw)
    bars, cuts = _gap_bars(track, times, score, [s.start_frame for s in shots[1:]])
    labels = [f"{k:02d}" for k in range(n)]
    cols = _cols(tw, n)
    per = cols * max(1, int(min(SHEET_SIDE, SHEET_PIX / (cols * (tw + 2))) // (th + 10)))  # tiles on one sheet
    images = []
    for p in range(int(math.ceil(n / per))):
        sl = slice(p * per, (p + 1) * per)
        name = f"overview_{p + 1}.jpg" if n > per else "overview.jpg"
        _save(_grid(frames[sl], labels[sl], bars[sl], cuts[sl], cols=cols, tile_w=tw), sdir / name)
        images.append(f"survey/{name}")
    gaps = {f"g{k:02d}": [times[k], times[k + 1]] for k in range(n - 1)}
    return {
        "id": "overview", "round": 1, "images": images, "instructions": INSTRUCTIONS,
        "state": {"duration": round(dur, 3), "tiles": n, "every": round(every, 3), "times": times,
                  "tool_cuts": [round(s.start, 3) for s in shots[1:]],
                  "tool_cut_gaps": [g for g, c in zip(gaps, cuts) if c]},
        "questions": {
            "shots_estimate": {"type": "integer", "instructions": "整条视频大约有多少个镜头 / 场景（数换场景的次数 + 1）；同时给 range"},
            "gaps": {"type": "choice", "per": "gap", "ids": list(gaps), "criteria": GAP_CRITERIA, "kinds": KINDS},
        },
        "answer_template": {"shots_estimate": {"answer": None, "range": [None, None]}, "gaps": {}},
        "_gaps": gaps,
    }


def _zoom_frames(track: FrameTrack, a: int, z: int, score: np.ndarray, cap: int = ZOOM_MAX) -> list[int]:
    """Frames to show for [a, z]: every frame when few; otherwise the ends, the peaks of change (a transition's key
    moments) and frames where the picture has become something new, then the widest holes split until the cap: a slow
    morph with no single big change still gets frames through it."""
    z = min(z, track.n - 1)
    if z - a + 1 <= cap:
        return list(range(a, z + 1))
    keep = {a, z}
    seg = score[a:z + 1]
    for i in np.argsort(-seg)[:cap // 3]:  # biggest changes: the frame before and the frame of each
        if seg[i] > 0.05:
            keep.update({a + int(i) - 1, a + int(i)})
    keep.update(key_frames(track, a, z + 1, busy=[(-1e9, 1e9)], max_n=cap))
    keep = sorted(k for k in keep if a <= k <= z)
    room = cap - cap // 4  # a quarter of the frames is kept for the holes
    if len(keep) > room:
        rest = [k for k in keep if k not in (a, z)]
        idx = np.unique(np.linspace(0, len(rest) - 1, num=room - 2).round().astype(int))
        keep = sorted({a, z} | {rest[i] for i in idx})
    while len(keep) < cap:
        j = max(range(len(keep) - 1), key=lambda i: keep[i + 1] - keep[i])
        if keep[j + 1] - keep[j] < 2:
            break
        keep.insert(j + 1, (keep[j] + keep[j + 1]) // 2)
    return keep


def zoom_tasks(video: str, info: VideoInfo, track: FrameTrack, shots: list[Shot], sdir: Path, windows: list[tuple[float, float, str]],
               rnd: int) -> list[dict]:
    """The stretches to look at closer, as many stacked on one image as fit (one look, one answer file); each
    stretch's gaps are named <stretch>.<NN>."""
    score = change_score(track)
    cut_frames = [s.start_frame for s in shots[1:]]
    tw, _ = tile_size(info, "zoom")
    blocks: list[tuple[str, Image.Image]] = []
    meta: list[tuple[dict, dict]] = []
    for k, (t0, t1, why) in enumerate(windows):
        wid = f"r{rnd}_{k + 1:02d}"
        idx = _zoom_frames(track, frame_at(track, t0), frame_at(track, t1), score)
        times = [round(_t(track, i), 3) for i in idx]
        bars, cuts = _gap_bars(track, times, score, cut_frames)
        grid = _grid(_grab(video, info, times, width=tw), [f"{j:02d}" for j in range(len(times))], bars, cuts,
                     cols=_cols(tw, len(times)), tile_w=tw)
        blocks.append((f"{wid}  {fmt_time(t0)} – {fmt_time(t1)}", grid))
        wg = {f"{wid}.{j:02d}": [times[j], times[j + 1]] for j in range(len(times) - 1)}
        meta.append((wg, {"id": wid, "why": why, "span": [round(t0, 3), round(t1, 3)], "times": times,
                          "tool_cut_gaps": [g for g, c in zip(wg, cuts) if c]}))
    tasks = []
    for p, rows in enumerate(_pack([im for _, im in blocks]), start=1):
        tid = f"r{rnd}_s{p:02d}"
        _sheet([[blocks[k] for k in r] for r in rows], sdir / "zoom" / f"{tid}.jpg")
        ks = [k for r in rows for k in r]
        gaps = {g: v for k in ks for g, v in meta[k][0].items()}
        tasks.append({
            "id": tid, "round": rnd, "images": [f"survey/zoom/{tid}.jpg"], "instructions": ZOOM_INSTRUCTIONS + GAP_RULES,
            "state": {"windows": [meta[k][1] for k in ks]},
            "questions": {"scenes": {"type": "list", "per": "block", "ids": [meta[k][1]["id"] for k in ks],
                                     "instructions": "每块里按顺序出现的主体 / 场景：\"格子编号 名称, ...\""},
                          "gaps": {"type": "choice", "per": "gap", "ids": list(gaps), "criteria": GAP_CRITERIA, "kinds": KINDS}},
            "answer_template": {"scenes": {}, "gaps": {}}, "_gaps": gaps,
        })
    return tasks


DETAIL_CANDIDATES = 10     # candidate frames of a shot worth asking about (one row of detail tiles)
DETAIL_PLAIN = 2           # frames shown of the other shots (first and last change): enough to judge how they were made
DETAIL_MIN_S = 1.5         # shorter shots keep the tool's key frames: shown, not asked about
DETAIL_MIN_KEYS = 4        # ... and so do shots where the tool finds fewer key frames (little happens)


def _candidates(track: FrameTrack, a: int, z: int, busy: list[list[float]]) -> list[int] | None:
    """A shot's candidate key frames for the AI (more than the tool would keep), or None when the shot is short or
    little happens in it: the tool's key frames stand."""
    if _t(track, z - 1) - _t(track, a) < DETAIL_MIN_S:
        return None
    b = [tuple(x) for x in busy]
    if len(key_frames(track, a, z, b)) < DETAIL_MIN_KEYS:
        return None
    idx = key_frames(track, a, z, b, max_n=DETAIL_CANDIDATES, moving=KEY_MOVING * 0.8, moving_busy=KEY_MOVING_BUSY * 0.8)
    if len(idx) < DETAIL_CANDIDATES // 2:  # few changes: top up evenly so a quick blink between two picks is still seen
        idx = sorted(set(idx) | set(np.linspace(a, z - 1, num=DETAIL_CANDIDATES // 2).round().astype(int).tolist()))
    return idx


def detail_tasks(video: str, info: VideoInfo, track: FrameTrack, sdir: Path, spans: list[tuple[int, int]],
                 busy: list[list[float]]) -> list[dict]:
    """Every shot once, at the closer tile size: the candidate key frames of the shots worth asking about, a few key
    frames of the others; short shots share a row. One answer per sheet: the key frames, and how the picture was made
    (the sheet's usual look once, shots that differ on their own)."""
    tw, _ = tile_size(info, "detail")
    blocks: list[tuple[str, Image.Image]] = []
    rows_meta: list[tuple[str, list[float], list[int], bool]] = []
    for k, (a, z) in enumerate(spans, start=1):
        idx = _candidates(track, a, z, busy)
        ask = idx is not None
        if not ask:
            idx = key_frames(track, a, z, [tuple(x) for x in busy], max_n=DETAIL_PLAIN)
        times = [round(_t(track, i), 3) for i in idx]
        sid = f"shot_{k:03d}"
        grid = _grid(_grab(video, info, times, width=tw), [f"{j:02d}" for j in range(len(times))],
                     [0.0] * len(times), [False] * len(times), cols=_cols(tw, len(times)), tile_w=tw)
        blocks.append((f"{sid} {fmt_time(times[0])}", grid))
        rows_meta.append((sid, times, idx, ask))
    tasks = []
    for p, rows in enumerate(_pack([im for _, im in blocks]), start=1):
        tid = f"kf_{p:02d}"
        _sheet([[blocks[k] for k in r] for r in rows], sdir / "detail" / f"{tid}.jpg")
        ks = [k for r in rows for k in r]
        tasks.append({"id": tid, "stage": "detail", "images": [f"survey/detail/{tid}.jpg"], "instructions": DETAIL_INSTRUCTIONS,
                      "state": {"shots": {rows_meta[k][0]: rows_meta[k][1] for k in ks},
                                "pick_key_frames": [rows_meta[k][0] for k in ks if rows_meta[k][3]]},
                      "questions": {"look": {"type": "choice", "per": "sheet, a shot may differ", "criteria": SOURCE_CRITERIA},
                                    "shots": {"type": "per_shot", "frames": {"type": "choice", "per": "tile", "criteria": KEY_ROLES},
                                              "missing": {"type": "multi_choice", "instructions": "漏了关键帧的相邻两格，写成 \"03-04\""}}},
                      "answer_template": {"look": None, "shots": {}},
                      "_frames": {rows_meta[k][0]: rows_meta[k][2] for k in ks}})
    return tasks


def _look(v) -> dict | None:
    """"code_render .9" or {"answer", "p"} -> {"answer", "p"}; None when it is not one of the looks."""
    if isinstance(v, str):
        ans, _, p = _short(v, SOURCE_CRITERIA)
        return {"answer": ans, "p": {ans: p}} if ans else None
    if isinstance(v, dict) and v.get("answer") in SOURCE_CRITERIA:
        p = {k: float(x) for k, x in (v.get("p") or {}).items() if k in SOURCE_CRITERIA and isinstance(x, (int, float))}
        tot = sum(p.values())
        return {"answer": v["answer"], "p": {k: round(x / max(tot, 1.0), 3) for k, x in p.items()} if tot > 0 else {v["answer"]: 1.0}}
    return None


def _clean_shot(v) -> dict:
    """One shot's answer: "accept" (or nothing) = the tool's key frames; else frames {tile: role}, missing ["03-04"]
    and look (when it differs from the sheet's). Roles and looks may be written short: "extreme .7", "ai_video .6"."""
    keep = {"accept": True, "frames": {}, "missing": []}
    if isinstance(v, str):
        lk = _look(v)
        return {**keep, **({"look": lk} if lk else {})}
    if not isinstance(v, dict) or v.get("accept"):
        return keep
    frames = {}
    for k, x in (v.get("frames") or {}).items():
        if isinstance(x, str):
            ans, _, p = _short(x, KEY_ROLES)
            x = {"answer": ans, "p": {ans: p}} if ans else None
        if isinstance(x, dict) and x.get("answer") in KEY_ROLES and str(k).isdigit():
            p = {r: float(y) for r, y in (x.get("p") or {}).items() if r in KEY_ROLES and isinstance(y, (int, float))}
            frames[int(k)] = {"answer": x["answer"], "p": p or {x["answer"]: 1.0}}
    missing = []
    for m in v.get("missing") or []:
        try:
            i, j = (int(y) for y in str(m).split("-"))
            missing.append((min(i, j), max(i, j)))
        except ValueError:
            continue
    lk = _look(v.get("look"))
    return {"accept": not frames and not missing, "frames": frames, "missing": missing, **({"look": lk} if lk else {})}


def read_detail(path: Path) -> dict | None:
    """{"look": the sheet's look or None, "shots": {shot id: answer}} from a filled detail answer; shots left out keep
    the tool's key frames and the sheet's look."""
    if not path.is_file():
        return None
    try:
        got = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(got, dict) or not (got.get("filled") or got.get("shots") or got.get("look")):
        return None
    return {"look": _look(got.get("look")), "by": got.get("by") or "",
            "shots": {sid: _clean_shot(v) for sid, v in (got.get("shots") or {}).items()}}


def _short(text: str, options: dict, kinds: dict | None = None) -> tuple[str | None, str | None, float]:
    """A short answer "transition zoom .85" -> (answer, kind, p). Options may be shortened to a unique prefix."""
    ans = kind = None
    p = 1.0
    for tok in str(text).replace(",", " ").split():
        try:
            p = float(tok)
            continue
        except ValueError:
            pass
        if ans is None:
            hits = [o for o in options if o == tok] or [o for o in options if o.startswith(tok)]
            ans = hits[0] if len(hits) == 1 else None
        elif kinds and tok in kinds:
            kind = tok
    return ans, kind, max(0.0, min(1.0, p))


def _clean_gap(v) -> dict | None:
    """One gap answer -> {"answer", "p", "kind"?}; None when unusable."""
    if isinstance(v, str):
        ans, kind, p = _short(v, GAP_CRITERIA, KINDS)
        v = {"answer": ans, "p": {ans: p}, **({"kind": kind} if kind else {})} if ans else None
    if not isinstance(v, dict):
        return None
    ans = v.get("answer")
    if ans not in GAP_CRITERIA:
        return None
    p = v.get("p") if isinstance(v.get("p"), dict) else {}
    p = {k: float(x) for k, x in p.items() if k in GAP_CRITERIA and isinstance(x, (int, float))}
    tot = sum(p.values())  # probabilities over 1 in total are scaled down; a lone "cut .85" keeps its .85
    p = {k: round(x / max(tot, 1.0), 3) for k, x in p.items()} if tot > 0 else {ans: 1.0}
    out = {"answer": ans, "p": p}
    if v.get("kind") in KINDS:
        out["kind"] = v["kind"]
    return out


def read_answer(path: Path) -> dict | None:
    """A filled answer file, or None when it is missing or still the empty template."""
    if not path.is_file():
        return None
    try:
        got = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(got, dict):
        return None
    gaps = {k: g for k, v in (got.get("gaps") or {}).items() if (g := _clean_gap(v))}
    est = got.get("shots_estimate")
    if not (got.get("filled") or gaps or (isinstance(est, dict) and est.get("answer"))):
        return None  # the empty template: "filled": true marks an answer where every gap is a plain continuation
    scenes = {}
    for blk, v in (got.get("scenes") or {}).items():
        rows = []
        for part in (v if isinstance(v, list) else str(v).split(",")):
            tok = str(part).strip().split(None, 1)
            if tok and tok[0].isdigit():
                rows.append((int(tok[0]), tok[1].strip() if len(tok) > 1 else ""))
        if rows:
            scenes[blk] = sorted(rows)
    return {"gaps": gaps, "by": got.get("by") or "", **({"scenes": scenes} if scenes else {}),
            **({"shots_estimate": est} if isinstance(est, dict) and est.get("answer") else {})}


def scene_fix(task: dict, ans: dict, track: FrameTrack) -> list[dict]:
    """A zoom answer's scene list is the reader saying what it saw; a new scene with no cut / transition answered
    before it (the reader called the change busy) gets a transition at the gap that changes most. Returns the scenes
    with their times."""
    score = change_score(track)
    out = []
    for w in task["state"].get("windows", []):
        rows = [(k, n) for k, n in ans.get("scenes", {}).get(w["id"], []) if 0 <= k < len(w["times"])]
        for (p, _), (k, name) in zip(rows, rows[1:]):
            ids = [f"{w['id']}.{j:02d}" for j in range(p, k)]
            if not ids or any((ans["gaps"].get(g) or {}).get("answer") in ("cut", "transition") for g in ids):
                continue
            def peak(g):
                a, z = frame_at(track, task["_gaps"][g][0]) + 1, frame_at(track, task["_gaps"][g][1]) + 1
                return float(score[a:max(a + 1, z)].max()) if z > a else 0.0
            g = max(ids, key=peak)
            ans["gaps"][g] = {"answer": "transition", "p": {"transition": 0.6}, "by_scenes": True}
        out += [{"t": w["times"][k], "name": n} for k, n in rows if n]
    return out


def spikes(track: FrameTrack, t0: float, t1: float, level: float = 0.25) -> int:
    """How many separate sudden changes (frames changing by `level` or more, two frames apart) lie in [t0, t1]."""
    s = change_score(track)
    a, z = frame_at(track, t0) + 1, frame_at(track, t1) + 1
    hits = [i for i in range(a, min(z, len(s))) if s[i] >= level]
    return sum(1 for k, i in enumerate(hits) if k == 0 or i - hits[k - 1] > 2)


def _windows(task: dict, gaps: dict, rnd: int = 1, track: FrameTrack | None = None) -> list[tuple[float, float, str]]:
    """Stretches to zoom into next: runs of neighbouring gaps answered transition / unsure on the overview (and cut,
    when the gap holds more than one sudden change: one answer can only place one cut), unsure on a zoom sheet (a
    transition there has been looked at closely already), split to ZOOM_SPAN."""
    ids = list(task["_gaps"])
    first = task["id"] == "overview"
    want = ("transition", "unsure") if first else ("unsure",)
    one = 2.5 / track.fps if track is not None else 0.0

    def zoom(g: str) -> bool:
        ans = (gaps.get(g) or {}).get("answer")
        t0, t1 = task["_gaps"][g]
        if t1 - t0 <= one:
            return False  # neighbouring frames: nothing more to see, the change curve decides (build_timeline)
        if ans == "transition" and first and t1 - t0 <= FINE_GAP:
            return False  # the overview already showed it closely
        return ans in want or (first and ans == "cut" and track is not None and spikes(track, t0, t1) > 1)
    pick = [g for g in ids if zoom(g)]
    runs: list[list[str]] = []
    for g in pick:
        if runs and ids.index(g) == ids.index(runs[-1][-1]) + 1:
            runs[-1].append(g)
        else:
            runs.append([g])
    out = []
    for r in runs:
        t0, t1 = task["_gaps"][r[0]][0], task["_gaps"][r[-1]][1]
        why = "unsure" if all(gaps[g]["answer"] == "unsure" for g in r) else ("cuts" if all(gaps[g]["answer"] == "cut" for g in r) else "transition")
        n = max(1, int(math.ceil((t1 - t0) / ZOOM_SPAN)))
        for k in range(n):
            out.append((t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n, why))
    return out


# ------------------------------------------------------------------ run ------------------------------------------

Asker = Callable[[dict, list[Path]], dict]


def _public(task: dict) -> dict:
    return {k: v for k, v in task.items() if not k.startswith("_")}


def _task_paths(sdir: Path, tid: str) -> tuple[Path, Path]:
    base = sdir if tid == "overview" else sdir / ("detail" if tid.startswith("kf_") else "zoom")
    return base / f"{tid}.task.json", base / f"{tid}.answer.json"


def _write_task(sdir: Path, task: dict) -> None:
    tp, ap = _task_paths(sdir, task["id"])
    write_json(tp, {**_public(task), "gap_times": task.get("_gaps"), "frame_index": task.get("_frames")})
    if not ap.exists():
        write_json(ap, {"filled": False, **task["answer_template"]})


def _load_task(sdir: Path, tid: str) -> dict | None:
    tp, _ = _task_paths(sdir, tid)
    if not tp.is_file():
        return None
    t = read_json(tp)
    t["_gaps"] = t.pop("gap_times", None) or {}
    t["_frames"] = t.pop("frame_index", None) or {}
    return t


def _reset(sdir: Path) -> None:
    for d in (sdir, sdir / "zoom", sdir / "detail"):
        for p in [*d.glob("*.json"), *d.glob("*.jpg")]:
            p.unlink()


def run(video: str | Path, out: Path, track: FrameTrack, shots: list[Shot], info: VideoInfo | None = None,
        asker: Asker | None = None, workers: int = 4, detail: bool = True) -> dict:
    """Advance the survey as far as the answers allow. Stage 1 finds the scene changes (overview, then zoom rounds);
    stage 2 picks each shot's key frames (one detail sheet per shot). With `asker` (a VLM) every task is answered
    right away, the tasks of a round in parallel; without it the tasks waiting for an answer are returned, an agent
    fills their answer files (they are independent: several agents can work at once) and runs this again.
    Returns {"status": "done" | "waiting", "stage", "round", "waiting": [answer files], ...}."""
    video = str(video)
    info = info or video_info(video)
    sdir = Path(out) / "survey"
    sdir.mkdir(parents=True, exist_ok=True)
    src = _source(video, info)
    meta_p = sdir / "survey.json"
    meta = read_json(meta_p) if meta_p.is_file() else {}
    if meta.get("source") != src or meta.get("version") != VERSION:
        _reset(sdir)
        meta = {"version": VERSION, "source": src, "rounds": [["overview"]]}
        _write_task(sdir, overview_task(video, info, track, shots, sdir))
        write_json(meta_p, meta)

    def answer(tasks: list[dict], reader) -> None:
        if asker is None:
            return

        def one(t: dict) -> None:
            _, ap = _task_paths(sdir, t["id"])
            if reader(ap) is None:
                got = asker(_public(t), [Path(out) / im for im in t["images"]])
                write_json(ap, {"filled": True, "by": "vlm", **(got or {})})
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(one, tasks))

    def waiting(tasks: list[dict], reader, stage: str, rnd: int) -> dict | None:
        left = [t for t in tasks if reader(_task_paths(sdir, t["id"])[1]) is None]
        if not left:
            return None
        return {"status": "waiting", "stage": stage, "round": rnd, "waiting": [str(_task_paths(sdir, t["id"])[1]) for t in left],
                "tasks": [str(_task_paths(sdir, t["id"])[0]) for t in left],
                "images": [str(Path(out) / im) for t in left for im in t["images"]]}

    # ---- stage 1: scene changes
    found: dict[str, dict] = {}
    for rnd, ids in enumerate(meta["rounds"], start=1):
        tasks = [t for tid in ids if (t := _load_task(sdir, tid))]
        answer(tasks, read_answer)
        if (w := waiting(tasks, read_answer, "cuts", rnd)):
            return w
        nxt: list[tuple[float, float, str]] = []
        zoomed = [(w["span"][0], w["span"][1]) for t in tasks for w in t["state"].get("windows", [])]
        for t in tasks:
            ans = read_answer(_task_paths(sdir, t["id"])[1]) or {"gaps": {}}
            if ans.get("scenes"):
                meta.setdefault("scene_names", {})[t["id"]] = scene_fix(t, ans, track)
            lvl = rnd if t["id"] == "overview" else rnd + 1  # how close the look was: a zoom beats the overview
            for g, span in t["_gaps"].items():
                if g in ans["gaps"]:
                    found[g] = {"t": span, "round": lvl, **ans["gaps"][g]}
                elif t["id"] != "overview":  # a zoomed stretch: gaps left out are continuations, and replace the coarser answer
                    found[g] = {"t": span, "round": lvl, "answer": "same", "p": {"same": 1.0}, "implicit": True}
            if rnd == 1 and ans.get("shots_estimate"):
                meta["shots_estimate"] = ans["shots_estimate"]
            if rnd < MAX_ROUNDS:
                # stretches zoomed in this round already are not zoomed again for the overview's sake
                nxt += [w for w in _windows(t, ans["gaps"], rnd, track)
                        if t["id"] != "overview" or sum(max(0.0, min(w[1], z) - max(w[0], a)) for a, z in zoomed) < 0.8 * (w[1] - w[0])]
        if rnd == len(meta["rounds"]) and nxt:
            new = []
            for t in zoom_tasks(video, info, track, shots, sdir, nxt, rnd + 1):
                _write_task(sdir, t)
                new.append(t["id"])
            meta["rounds"].append(new)
            write_json(meta_p, meta)
            return run(video, out, track, shots, info, asker, workers, detail)
    timeline = build_timeline(track, shots, found, meta)

    # ---- stage 2: key frames of every shot
    bounds = [0, *[c["frame"] for c in timeline["cuts"]], track.n]
    spans = list(zip(bounds[:-1], bounds[1:]))
    if detail:
        if meta.get("detail_for") != [c["frame"] for c in timeline["cuts"]]:
            for p in [*(sdir / "detail").glob("*")]:
                p.unlink()
            ids = []
            for t in detail_tasks(video, info, track, sdir, spans, timeline["busy"]):
                _write_task(sdir, t)
                ids.append(t["id"])
            meta.update(detail=ids, detail_for=[c["frame"] for c in timeline["cuts"]])
            write_json(meta_p, meta)
        tasks = [t for tid in meta.get("detail", []) if (t := _load_task(sdir, tid))]
        answer(tasks, read_detail)
        if (w := waiting(tasks, read_detail, "keyframes", 1)):
            write_json(sdir / "timeline.json", timeline)  # the cuts are settled already
            return w
    timeline["keyframes"] = keyframe_list(track, spans, timeline["busy"], sdir if detail else None, meta.get("detail", []))
    if detail and (looks := look_list(track, spans, sdir, meta.get("detail", []))):
        timeline["looks"] = looks
    write_json(sdir / "timeline.json", timeline)
    return {"status": "done", "rounds": len(meta["rounds"]), "timeline": str(sdir / "timeline.json"),
            "shots": timeline["shots"], "cuts": len(timeline["cuts"]),
            "keyframes": sum(len(v) for v in timeline["keyframes"].values())}


def keyframe_list(track: FrameTrack, spans: list[tuple[int, int]], busy: list[list[float]], sdir: Path | None,
                  detail_ids: list[str] | None = None) -> dict:
    """{shot number: [{t, frame, role, p?, by}]}: the AI's picks and names where a detail answer changed them (plus
    the frame farthest from the in-between in every gap it said misses one), the tool's key frames elsewhere."""
    asked: dict[str, tuple[list[int], dict]] = {}  # shot id -> (candidate frames, answer)
    for tid in detail_ids or []:
        t = _load_task(sdir, tid) if sdir else None
        got = read_detail(_task_paths(sdir, tid)[1]) if t else None
        for sid, idx in ((t or {}).get("_frames") or {}).items():
            asked[sid] = (idx, (got or {}).get("shots", {}).get(sid) or {"accept": True})
    out: dict[str, list[dict]] = {}
    for k, (a, z) in enumerate(spans, start=1):
        rows: list[dict] = []
        idx, ans = asked.get(f"shot_{k:03d}", ([], {"accept": True}))
        if idx and not ans.get("accept"):
            for j, v in ans["frames"].items():
                if 0 <= j < len(idx):
                    rows.append({"frame": idx[j], "role": v["answer"], "p": round(max(v["p"].values()), 3), "by": "ai"})
            for i, j in ans["missing"]:
                if 0 <= i < j < len(idx) and idx[j] - idx[i] >= 2:
                    got = key_frames(track, idx[i], idx[j] + 1, max_n=3, moving=KEY_MOVING * 0.4, moving_busy=KEY_MOVING_BUSY * 0.4)
                    rows += [{"frame": f, "role": "missed", "by": "ai+tool"} for f in got if idx[i] < f < idx[j]][:1]
            if not any(r["frame"] == a for r in rows):
                rows.append({"frame": a, "role": "first", "by": "tool"})
        else:
            got = key_frames(track, a, z, [tuple(b) for b in busy])
            rows = [{"frame": f, "role": "first" if f == a else ("last" if f == z - 1 else "change"), "by": "tool"} for f in got]
        seen = set()
        rows = [r for r in sorted(rows, key=lambda r: r["frame"]) if not (r["frame"] in seen or seen.add(r["frame"]))]
        for r in rows:
            r["t"] = round(_t(track, r["frame"]), 3)
        out[str(k)] = rows
    return out


def look_list(track: FrameTrack, spans: list[tuple[int, int]], sdir: Path, detail_ids: list[str]) -> list[dict]:
    """How the picture was made, from the detail answers: [{span, answer, p, by, shots}], neighbouring shots with the
    same answer merged. A shot takes its own answer, else its sheet's."""
    per: dict[str, tuple[dict, str]] = {}
    for tid in detail_ids:
        t = _load_task(sdir, tid)
        got = read_detail(_task_paths(sdir, tid)[1]) if t else None
        if not got:
            continue
        for sid in (t.get("_frames") or {}):
            lk = (got["shots"].get(sid) or {}).get("look") or got["look"]
            if lk:
                per[sid] = (lk, got.get("by") or "")
    out: list[dict] = []
    for k, (a, z) in enumerate(spans, start=1):
        if f"shot_{k:03d}" not in per:
            continue
        lk, by = per[f"shot_{k:03d}"]
        t0, t1 = round(_t(track, a), 3), round(_t(track, z - 1) + 1 / track.fps, 3)
        if out and out[-1]["answer"] == lk["answer"] and out[-1]["shots"][-1] == k - 1:
            out[-1]["span"][1] = t1
            out[-1]["shots"].append(k)
            out[-1]["p"] = {x: round(max(out[-1]["p"].get(x, 0.0), y), 3) for x, y in {**out[-1]["p"], **lk["p"]}.items()}
            continue
        out.append({"span": [t0, t1], "answer": lk["answer"], "p": dict(lk["p"]), "by": by, "shots": [k]})
    return out


def _finest(found: dict) -> dict:
    """Keep, for every stretch, the answers of the round that looked closest: a gap that later rounds' gaps cover (90%
    of it; their tiles need not line up with its ends) is replaced by them."""
    out = {}
    for g, v in found.items():
        t0, t1 = v["t"]
        later = sorted((max(t0, w["t"][0]), min(t1, w["t"][1])) for w in found.values()
                       if w["round"] > v["round"] and w["t"][0] < t1 and w["t"][1] > t0)  # only what overlaps it
        covered, end = 0.0, t0
        for a, z in later:
            if z > end:
                covered += z - max(a, end)
                end = z
        if t1 > t0 and covered >= 0.9 * (t1 - t0):
            continue
        out[g] = v
    return out


def build_timeline(track: FrameTrack, shots: list[Shot], found: dict, meta: dict) -> dict:
    score = change_score(track)
    fin = _finest(found)
    cuts: list[dict] = []
    busy: list[list[float]] = []
    # runs of neighbouring transition gaps are one transition: the boundary in its middle, the run as its span
    items = sorted(fin.items(), key=lambda kv: kv[1]["t"][0])
    k = 0
    while k < len(items):
        g, v = items[k]
        ans = v["answer"]
        if ans == "busy":
            busy.append([round(v["t"][0], 3), round(v["t"][1], 3)])
        elif ans == "cut" or (ans == "unsure"):
            a, z = frame_at(track, v["t"][0]) + 1, frame_at(track, v["t"][1]) + 1
            b = a + int(np.argmax(score[a:max(a + 1, z)]))
            if ans == "unsure" and z - a <= 2 and score[b] < 0.25:
                k += 1
                continue  # neighbouring frames nobody could tell apart, and no sudden change between them
            tb = round(_t(track, b), 3)
            cuts.append({"t": tb, "frame": int(b), "kind": v.get("kind", "cut") if ans == "cut" else "cut",
                         "span": [tb, tb], "p": v["p"].get(ans, 0.5) if ans == "cut" else 0.5,
                         "by": "survey", "round": v["round"], **({"unsure": True} if ans == "unsure" else {})})
        elif ans == "transition":
            run_ = [v]
            # one transition = neighbouring gaps of the same kind; a new kind right after is the next transition
            while (k + 1 < len(items) and items[k + 1][1]["answer"] == "transition" and abs(items[k + 1][1]["t"][0] - run_[-1]["t"][1]) < 1e-3
                   and items[k + 1][1].get("kind") == run_[0].get("kind")):
                k += 1
                run_.append(items[k][1])
            t0, t1 = run_[0]["t"][0], run_[-1]["t"][1]
            a, z = frame_at(track, t0) + 1, frame_at(track, t1) + 1
            # the boundary: the biggest single change inside the transition (away from its first and last frames, which
            # may be the cuts before and after it), else its middle
            m = 2 if z - a > 6 else 0
            seg = score[a + m:max(a + m + 1, z - m)]
            b = a + m + int(np.argmax(seg)) if len(seg) and seg.max() > 0.15 else (a + z) // 2
            kinds = [r.get("kind") for r in run_ if r.get("kind")]
            cuts.append({"t": round(_t(track, b), 3), "frame": int(b), "kind": max(set(kinds), key=kinds.count) if kinds else "effect",
                         "span": [round(t0, 3), round(t1, 3)], "p": round(float(np.mean([r["p"].get("transition", 0.5) for r in run_])), 3),
                         "by": "survey", "round": max(r["round"] for r in run_)})
        k += 1
    # the detector's cuts: kept unless their gap was answered "same" with high probability
    same = [v for v in fin.values() if v["answer"] == "same" and not v.get("implicit") and v["p"].get("same", 0) >= DROP_TOOL_CUT_P]
    dropped = []
    near = 0.25  # a detector cut this close to a transition the survey found is that transition
    edge = 2.5 / track.fps  # ... unless it sits on the transition's first or last frames: a separate cut next to it
    for s in shots[1:]:
        t = s.start
        inside = [c for c in cuts if c["span"][1] - c["span"][0] > 2 * edge and c["span"][0] + edge < t < c["span"][1] - edge]
        at_edge = [c for c in cuts if c not in inside and c["span"][0] - edge <= t <= c["span"][1] + edge and c["span"][1] > c["span"][0]]
        if inside or (not at_edge and any(c["span"][0] - near <= t <= c["span"][1] + near for c in cuts)):
            for c in inside:  # the survey found the same change: take the detector's exact frame
                c.update(frame=s.start_frame, t=round(t, 3), by="survey+tool")
                if c["kind"] in ("cut", "effect") and s.transition_in not in ("cut", "start"):
                    c["kind"] = s.transition_in
            continue
        if any(v["t"][0] <= t <= v["t"][1] for v in same):
            dropped.append(round(t, 3))
            continue
        cuts.append({"t": round(t, 3), "frame": s.start_frame, "kind": s.transition_in or "cut", "span": [round(t, 3), round(t, 3)],
                     "p": round(float(min(1.0, s.boundary_score)) or 0.6, 3), "by": "tool"})
    cuts.sort(key=lambda c: c["frame"])
    dedup: list[dict] = []
    tool_gap = max(2, int(round(0.12 * track.fps)))
    for c in cuts:
        # two changes the AI saw may be two frames apart (a flash frame); the detector's are kept 0.12 s apart
        gap = 2 if c["by"] != "tool" and dedup and dedup[-1]["by"] != "tool" else tool_gap
        if dedup and c["frame"] - dedup[-1]["frame"] < gap:
            if c["by"] != "tool" and dedup[-1]["by"] == "tool":
                dedup[-1] = c
            continue
        dedup.append(c)
    cuts = [c for c in dedup if 0 < c["frame"] < track.n - 1]
    edges = [0.0, *[c["t"] for c in cuts], _t(track, track.n - 1) + 1 / track.fps]
    lengths = [round(b - a, 3) for a, b in zip(edges[:-1], edges[1:])]
    dur = edges[-1]
    return {
        "version": VERSION, "source": meta.get("source"), "rounds": len(meta.get("rounds", [])),
        "shots_estimate": meta.get("shots_estimate"), "shots": len(cuts) + 1, "cuts": cuts,
        **({"dropped_tool_cuts": dropped} if dropped else {}), "busy": busy,
        **({"scene_names": sorted((x for v in meta["scene_names"].values() for x in v), key=lambda x: x["t"])}
           if meta.get("scene_names") else {}),
        "rhythm": {"shot_lengths": lengths, "mean_shot_s": round(float(np.mean(lengths)), 3) if lengths else 0.0,
                   "cuts_per_min": round(len(cuts) / dur * 60, 1) if dur else 0.0,
                   "change_step_s": RHYTHM_STEP, "change": rhythm(track)},
    }


def source_at(timeline: dict, t0: float, t1: float) -> dict | None:
    """The survey's opinion on how [t0, t1] was made (from the closer look at each shot): the segment holding most of it."""
    best, cover = None, 0.0
    for sg in timeline.get("looks") or []:
        c = min(t1, sg["span"][1]) - max(t0, sg["span"][0])
        if c > cover:
            best, cover = sg, c
    return best


def load_timeline(out: Path, video: str | Path, info: VideoInfo) -> dict | None:
    """survey/timeline.json when it was made for this video."""
    p = Path(out) / "survey" / "timeline.json"
    if not p.is_file():
        return None
    try:
        tl = read_json(p)
    except (OSError, ValueError):
        return None
    return tl if tl.get("source") == _source(str(video), info) and tl.get("version") == VERSION else None


# ------------------------------------------------------------------ VLM ------------------------------------------

def vlm_asker(client, lang_note: str = "") -> Asker:
    def ask(task: dict, images: list[Path]) -> dict:
        q = {k: task[k] for k in ("state", "questions")}
        prompt = (f"{task['instructions']}\n\n{lang_note}\n请求：\n{json.dumps(q, ensure_ascii=False)}\n\n"
                  f"只输出 JSON，形如 {json.dumps(task['answer_template'], ensure_ascii=False)}，gaps 里按 gap 编号填。")
        got = client.ask_json(prompt, [(p, "image/jpeg") for p in images], max_tokens=2048)
        return got if isinstance(got, dict) else {}
    return ask
