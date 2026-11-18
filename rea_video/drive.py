"""Drive clips for motion-led shots (dance, fights, workouts): the source motion, cleaned and cut, ready to feed a
motion-transfer or reference-video model, and the way back onto the original timeline.

  drive(out)  for each motion-drive unit of the production plan (or the shots given):
              - erase the post-production text and stickers frame by frame (a model learns them as part of the picture)
              - cut the motion into short segments at calm moments near a beat, or at the source's own cuts
                (hands, feet and turns hold up better in short segments; the seams fall where the dancer is still)
              - write drive/seg_XX.mp4 (no sound), seg_XX_first.jpg (frame the character image is matched to),
                seg_XX_music.wav (the track under it), optional seg_XX_depth.mp4, segments.jpg, drive.json, README.md
  join(out)   the generated segments (drive/results.json: {"seg_01": path}) fitted to their lengths, joined, cut per
              shot and written into remake/mine.json, so `rea-video remake` places them on the original timeline

Calm moments are measured, not guessed: the mean frame-to-frame change (overlay boxes masked out) at 12 fps, smoothed
over a quarter second; a cut is scored by that motion, the distance to the nearest beat and how far it lands from
the preferred segment length.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import dance
from .i18n import T, semi, shot_ids
from .media import iter_frames, scaled_size, video_info
from .util import LOG, read_json, write_image, write_json

CURVE_FPS = 12.0
CURVE_W = 160
PAD = 0.012  # share of the frame added around an overlay box before erasing
# what is erased: lines laid on in the edit. Labels and counters follow things in the picture, and in a dance that
# is the lettering on the dancer's clothes; erasing it smears the body the model has to learn the moves from
ERASE_KINDS = ("subtitle", "title", "huazi")
MIN_SAMPLES = 3  # OCR reads a real overlay again and again; text on a moving body turns up in one or two samples
SUB_HOLD = 0.8  # seconds a subtitle may outlive its OCR end time
T_PAD = 0.25  # seconds added before / after an overlay: OCR samples a few times a second, so its in / out times are coarse


def _ff(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", *args], check=True)


def overlays(b: dict, persistent: bool = False) -> list[dict]:
    """Post-production boxes to erase: subtitles, titles and styled text read steadily, and stickers laid on top
    (text that is part of the picture, labels on things, one-off reads and stickers marked as in the picture stay).
    persistent=True also erases text that sits unchanged across cuts (disclaimers, licence numbers, corner titles):
    laid on in the edit, never part of a scene, and a reference clip should not carry it."""
    from .classify import _same_words

    pk = b.get("packaging") or {}
    cuts = [r["start"] for r in (b.get("shots") or [])[1:]]

    def laid_on(c: dict) -> bool:
        """Text that holds still through a cut of the source, or sits on the frame's edge: added in the edit, not
        filmed or generated (product lettering moves with the product and changes between shots)."""
        if c.get("follows"):
            return False
        x, y, w, h = c["bbox"]
        if h > 0.1:  # lettering this tall is on a thing in the shot (a product held up to the camera), not a caption line
            return False
        edge = y + h > 0.93 or x < 0.04 or x + w > 0.96
        crosses = any(c["t0"] + 0.2 < t < c["t1"] - 0.2 for t in cuts)
        return bool(c.get("persistent")) or crosses or edge

    out = []
    for c in pk.get("text_cues") or []:
        if c.get("part_of_picture") or not c.get("bbox") or (c.get("kind") not in ERASE_KINDS and not (persistent and laid_on(c))):
            continue
        if int(c.get("samples") or 0) < MIN_SAMPLES:
            continue  # a flicker read: printing on a dancer's clothes, caught for a frame or two as it turns past
        mid = (c["t0"] + c["t1"]) / 2
        r = next((r for r in b.get("shots", []) if r["start"] <= mid < r["end"]), None) or {}
        said = (r.get("vlm") or {}).get("overlay_text")
        said = said if isinstance(said, list) else (r.get("review") or {}).get("overlay_text")
        if isinstance(said, list) and not any(_same_words(c.get("text") or "", str(o)) for o in said):
            continue  # a reader listed this shot's post-production words; this one is text in the scene (a phone screen, a sign)
        out.append({"t0": float(c["t0"]), "t1": float(c["t1"]), "bbox": c["bbox"], "what": c.get("kind_zh") or c.get("kind") or "text",
                    "sub": c.get("kind") == "subtitle"})
    # OCR often loses a subtitle line a little before it really goes; subtitles run back to back, so hold each one
    # until the next starts (at most SUB_HOLD)
    subs = [x for x in out if x["sub"]]

    def cy(x: dict) -> float:
        return x["bbox"][1] + x["bbox"][3] / 2

    for x in subs:
        later = [y["t0"] for y in subs if y["t0"] > x["t0"] + 0.05 and abs(cy(y) - cy(x)) < 0.06]  # the next line in the same band
        x["t1"] = min(x["t1"] + SUB_HOLD, max(x["t1"], min(later))) if later else x["t1"] + SUB_HOLD
    for s in pk.get("stickers") or []:
        if s.get("in_picture") or s.get("is_overlay") is False or s.get("confidence") == "low" or not s.get("bbox"):
            continue
        out.append({"t0": float(s["t0"]), "t1": float(s["t1"]), "bbox": s["bbox"], "what": s.get("kind_zh") or "sticker"})
    return out


def _mask(boxes: list[dict], t: float, w: int, h: int) -> np.ndarray | None:
    on = [x for x in boxes if x["t0"] - T_PAD <= t <= x["t1"] + T_PAD]
    if not on:
        return None
    m = np.zeros((h, w), np.uint8)
    for x in on:
        bx, by, bw, bh = x["bbox"]
        x0, y0 = int(max(0.0, bx - PAD) * w), int(max(0.0, by - PAD) * h)
        x1, y1 = int(min(1.0, bx + bw + PAD) * w), int(min(1.0, by + bh + PAD) * h)
        m[y0:y1, x0:x1] = 255
    return m


def erase(frame: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """Fill the overlay boxes from their surroundings. Done at half size and pasted back: a drive clip needs the
    text gone, not a perfect fill, and full-size inpainting of a subtitle band is slow."""
    if mask is None or not mask.any():
        return frame
    h, w = frame.shape[:2]
    small, sm = cv2.resize(frame, (w // 2, h // 2), interpolation=cv2.INTER_AREA), cv2.resize(mask, (w // 2, h // 2), interpolation=cv2.INTER_NEAREST)
    filled = cv2.resize(cv2.inpaint(small, sm, 3, cv2.INPAINT_TELEA), (w, h), interpolation=cv2.INTER_LINEAR)
    out = frame.copy()
    out[mask > 0] = filled[mask > 0]
    return out


def motion_curve(path: str | Path, info, a: float, z: float, boxes: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """(times, motion) at CURVE_FPS: mean absolute change from the previous frame, overlay boxes left out."""
    prev, ts, es = None, [], []
    for i, f in enumerate(iter_frames(path, info, CURVE_W, start=a, duration=z - a, gray=True, fps=CURVE_FPS)):
        t = a + i / CURVE_FPS
        g = f.astype(np.float32)
        m = _mask(boxes, t, g.shape[1], g.shape[0])
        keep = np.ones_like(g, bool) if m is None else m == 0
        if prev is not None:
            ts.append(t)
            es.append(float(np.abs(g - prev)[keep].mean()) if keep.any() else 0.0)
        prev = g
    e = np.array(es, float)
    if len(e) >= 3:
        e = np.convolve(e, np.ones(3) / 3, mode="same")
    return np.array(ts, float), e


def cut_points(a: float, z: float, ts: np.ndarray, es: np.ndarray, beats: list[float], shot_cuts: list[float],
               lim: dict, bpm: float | None = None) -> list[tuple[float, str]]:
    """Where to cut [a, z] into segments: [(time, why)]. The count comes first (as few as the maximum allows, about
    the preferred length each), then each cut is searched around its even split: the source's own cuts are free
    seams; inside a take the calmest moment near a beat wins."""
    dur = z - a
    n = dance.segment_count(dur, lim)
    if n <= 1:
        return []
    step = dur / n
    scale = float(np.percentile(es, 90)) if len(es) else 1.0
    scale = scale or 1.0
    beat_gap = 60.0 / bpm if bpm else 0.5
    bs = np.array(beats, float)
    out: list[tuple[float, str]] = []
    pos = a
    for k in range(1, n):
        target = a + k * step
        left = n - k  # segments still to come after this cut
        lo = max(pos + lim["min"], target - 0.3 * step, z - left * lim["max"])
        hi = min(pos + lim["max"], target + 0.3 * step, z - left * lim["min"])
        if hi < lo:
            lo = hi = target
        best: tuple[float, float, str] | None = None
        for c in shot_cuts:
            if lo <= c <= hi:
                sc = 0.1 + 0.3 * abs(c - target) / step
                if best is None or sc < best[0]:
                    best = (sc, c, "cut")
        for t, e in zip(ts, es):
            if lo <= t <= hi:
                bd = min(1.0, float(np.min(np.abs(bs - t))) / beat_gap) if len(bs) else 0.5
                sc = float(e) / scale + 0.4 * bd + 0.3 * abs(t - target) / step
                if best is None or sc < best[0]:
                    best = (sc, float(t), "beat" if bd < 0.25 else "calm")
        cut = best[1] if best else target
        out.append((round(cut, 3), best[2] if best else "calm"))
        pos = cut
    return out


_WHY = {"cut": T("原片切点", "source cut"), "beat": T("动作停顿，落在拍点上", "calm moment on a beat"),
        "calm": T("动作停顿", "calm moment"), "start": T("单元开头", "unit start")}


def _units(b: dict, shots: list[int] | None) -> list[dict]:
    if shots:
        want = set(shots)
        runs, cur = [], []
        for r in b["shots"]:
            if r["index"] in want and (not cur or abs(cur[-1]["end"] - r["start"]) < 0.05):
                cur.append(r)
                continue
            if cur:
                runs.append(cur)
            cur = [r] if r["index"] in want else []
        if cur:
            runs.append(cur)
        return [{"id": f"M{k}", "shots": [r["index"] for r in run], "start": run[0]["start"], "end": run[-1]["end"]} for k, run in enumerate(runs, 1)]
    return (b.get("production_plan") or {}).get("drive") or []


def _depth_model():
    """Depth Anything V2 Small through transformers, when installed; None otherwise (the README then gives the
    Video Depth Anything command, which is the better tool: it is made for video and does not flicker)."""
    try:
        import torch  # noqa: F401
        from transformers import pipeline
    except ImportError:
        return None
    try:
        return pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")
    except Exception as e:  # network, weights, device
        LOG.warning("depth model unavailable: %s", e)
        return None


def _write_depth(model, frames: list[np.ndarray], path: Path, fps: float) -> None:
    from PIL import Image

    raw = [np.asarray(model(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))["predicted_depth"].squeeze(), np.float32) for f in frames]
    lo, hi = np.percentile(np.stack(raw), [2, 98])  # one range for the whole clip: per-frame ranges flicker
    h, w = frames[0].shape[:2]
    prev = None
    enc = _encoder(path, w, h, fps)
    for d in raw:
        d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        prev = d if prev is None else 0.6 * d + 0.4 * prev
        g = cv2.resize((prev * 255).astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR)
        enc.stdin.write(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR).tobytes())
    enc.stdin.close()
    enc.wait()


def _encoder(path: Path, w: int, h: int, fps: float, crf: int = 18):
    return subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.4f}",
                             "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf), str(path)], stdin=subprocess.PIPE)


def _sheet(rows: list[list[np.ndarray]], labels: list[str], path: Path) -> None:
    H = 220
    lines = []
    for frames, lab in zip(rows, labels):
        thumbs = [cv2.resize(f, (max(1, int(f.shape[1] * H / f.shape[0])), H)) for f in frames]
        row = np.concatenate(thumbs, axis=1)
        cv2.putText(row, lab, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(row, lab, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        lines.append(row)
    w = max(r.shape[1] for r in lines)
    write_image(path, np.concatenate([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in lines], axis=0))


def clean_clip(b: dict, ranges: list[list[float]], path: Path, width: int = 720, crf: int = 26) -> Path:
    """The source over `ranges` (joined when there are several) with subtitles, styled text and stickers erased and no
    sound: a reference video for a remix, so the model takes the shots and pacing but not the old words."""
    src = Path(b["source"]["path"])
    info = video_info(src)
    boxes = overlays(b, persistent=True)
    w, h = scaled_size(info, min(width, info.width or width))
    fps = info.fps if 0 < info.fps <= 60 else 30.0
    path.parent.mkdir(parents=True, exist_ok=True)
    # small: the clip travels inside the request (base64) and only has to show shots, camera and pacing
    enc = _encoder(path, w, h, fps, crf=crf)
    try:
        for a, z in ranges:
            for i, f in enumerate(iter_frames(src, info, w, start=a, duration=z - a, fps=fps)):
                t = a + i / fps
                enc.stdin.write(erase(f, _mask(boxes, t, f.shape[1], f.shape[0]) if boxes else None).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    return path


def clean_frame(b: dict, t: float, path: Path, width: int = 1080) -> Path:
    """One source frame at t with the edit's text erased: a composition reference for a model without reference video."""
    src = Path(b["source"]["path"])
    info = video_info(src)
    boxes = overlays(b, persistent=True)
    w, _ = scaled_size(info, min(width, info.width or width))
    for f in iter_frames(src, info, w, start=t, duration=0.1):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_image(path, erase(f, _mask(boxes, t, f.shape[1], f.shape[0]) if boxes else None))
        break
    return path


def drive(out: Path, shots: list[int] | None = None, depth: bool = False, clean: bool = True,
          prefer: float | None = None, max_s: float | None = None) -> dict:
    b = read_json(out / "breakdown.json")
    units = _units(b, shots)
    if not units:
        raise ValueError(T("没有动作驱动单元：先在看图复核里给舞蹈 / 动作镜头填 performance.move 并 apply-review，或用 --shots 指定镜头",
                           "no motion-drive units: mark the dance / action shots with performance.move in the review and apply it, or pass --shots"))
    src = Path(b["source"]["path"])
    info = video_info(src)
    lim = dance.segment_limits()
    if prefer:
        lim["prefer"] = float(prefer)
    if max_s:
        lim["max"] = float(max_s)
    lim["prefer"] = min(lim["prefer"], lim["max"])
    boxes = overlays(b) if clean else []
    beats = ((b.get("audio") or {}).get("music") or {}).get("beats") or []
    bpm = dance._bpm(b)
    ddir = out / "drive"
    ddir.mkdir(parents=True, exist_ok=True)
    for old in ddir.glob("seg_*"):  # a rerun may cut differently: no stale segments next to the new ones
        old.unlink()
    music = out / "stems" / "music.wav"
    model = _depth_model() if depth else None
    w, h = scaled_size(info, info.width or 1920)
    fps = info.fps if 0 < info.fps <= 60 else 30.0
    by_shot = {r["index"]: r for r in b["shots"]}
    segs, sheet_rows, sheet_labels = [], [], []
    for u in units:
        a, z = float(u["start"]), float(u["end"])
        shot_cuts = [by_shot[i]["start"] for i in u["shots"][1:] if i in by_shot]
        ts, es = motion_curve(src, info, a, z, boxes)
        cuts = cut_points(a, z, ts, es, beats, shot_cuts, lim, bpm)
        bounds = [(a, "start")] + cuts + [(z, "")]
        for (s0, why), (s1, _) in zip(bounds, bounds[1:]):
            k = len(segs) + 1
            name = f"seg_{k:02d}"
            inside = [c for c in shot_cuts if s0 + 0.05 < c < s1 - 0.05]
            erased: list[str] = []
            frames, keep = [], []
            enc = _encoder(ddir / f"{name}.mp4", w, h, fps)
            for i, f in enumerate(iter_frames(src, info, w, start=s0, duration=s1 - s0)):
                t = s0 + i / fps
                m = _mask(boxes, t, f.shape[1], f.shape[0]) if boxes else None
                if m is not None:
                    erased += [w for w in dict.fromkeys(x["what"] for x in boxes if x["t0"] - T_PAD <= t <= x["t1"] + T_PAD) if w not in erased]
                f = erase(f, m)
                enc.stdin.write(f.tobytes())
                if model is not None:
                    frames.append(f)
                if i == 0:
                    write_image(ddir / f"{name}_first.jpg", f)
                if i % max(1, int(fps)) == 0:  # one frame a second for the contact sheet
                    keep.append(f)
            enc.stdin.close()
            enc.wait()
            files = {"clip": f"drive/{name}.mp4", "first": f"drive/{name}_first.jpg"}
            if music.is_file() or info.has_audio:
                _ff(["-ss", f"{s0:.3f}", "-i", str(music if music.is_file() else src), "-t", f"{s1 - s0:.3f}", "-vn", "-ac", "2", str(ddir / f"{name}_music.wav")])
                files["music"] = f"drive/{name}_music.wav"
            if model is not None and frames:
                _write_depth(model, frames, ddir / f"{name}_depth.mp4", fps)
                files["depth"] = f"drive/{name}_depth.mp4"
            if keep:
                sheet_rows.append([keep[0], keep[len(keep) // 2], keep[-1]])
                sheet_labels.append(f"{name}  {s0:.1f}-{s1:.1f}s")
            segs.append({"id": name, "unit": u["id"], "start": round(s0, 3), "end": round(s1, 3), "duration": round(s1 - s0, 3),
                         "shots": [i for i in u["shots"] if by_shot.get(i) and by_shot[i]["start"] < s1 - 0.05 and by_shot[i]["end"] > s0 + 0.05],
                         "cut_in": why, "cuts_inside": len(inside), "beats": sum(1 for t in beats if s0 <= t < s1),
                         "overlays_erased": erased, "files": files})
    if sheet_rows:
        _sheet(sheet_rows, sheet_labels, ddir / "segments.jpg")
    res = {"video": str(src), "limits": lim, "depth": "written" if model is not None else ("missing" if depth else "off"),
           "units": [u["id"] for u in units], "segments": segs}
    write_json(ddir / "drive.json", res)
    (ddir / "README.md").write_text("\n".join(readme(res, (b.get("production_plan") or {}).get("drive") or [])) + "\n", encoding="utf-8")
    return res


def readme(res: dict, plan_units: list[dict]) -> list[str]:
    L = [T("# 动作驱动视频", "# Motion drive clips"), "",
         T("每段是原片的一截动作，字幕和贴纸已经擦掉，没有声音。拿去喂动作迁移或参考视频模型，每段都用同一张角色图。",
           "Each segment is a stretch of the source motion with subtitles and stickers erased and no sound. Feed it to a motion-transfer or "
           "reference-video model, with the same character image for every segment."), "",
         T("先打开 `segments.jpg` 看一遍：每段头到脚是不是都在画面里、有没有擦坏的地方。字幕正好压着手脚时，擦过的地方会糊，"
           "这时最好找到没有字幕的原片（舞蹈多半有原版）再跑一次。",
           "Look at `segments.jpg` first: is the whole body in frame in every segment, and did the erasing leave anything broken. Where a "
           "subtitle sits over hands or feet the erased patch blurs them; then find a copy without subtitles (most dances have an original upload) and run it again."), "",
         T("| 段 | 原片时间 | 时长 | 怎么切的 | 段内剪辑 | 拍数 | 擦掉的 | 镜头 |", "| Segment | Source time | Length | Cut at | Cuts inside | Beats | Erased | Shots |"),
         "|---|---|---|---|---|---|---|---|"]
    for s in res["segments"]:
        L.append(f"| `{s['id']}` | {s['start']:.1f}–{s['end']:.1f}s | {s['duration']:.1f}s | {_WHY.get(s['cut_in'], s['cut_in'])} | "
                 f"{s['cuts_inside'] or '—'} | {s['beats'] or '—'} | {'、'.join(s['overlays_erased']) or '—'} | {shot_ids(s['shots'])} |")
    short = [s["id"] for s in res["segments"] if s["duration"] < 3]
    cut = [s["id"] for s in res["segments"] if s["cuts_inside"]]
    notes = []
    if cut:
        notes.append(T("{s} 段内有原片剪辑：Kling 动作控制要一镜到底，这几段用 Seedance 2.5 全能参考", "{s} contain source cuts: Kling Motion Control needs a single take, use Seedance 2.5 omni-reference for these", s="、".join(cut)))
    if short:
        notes.append(T("{s} 短于 3 秒：Kling 不收，前后多带一点再生成，或并进相邻的段", "{s} are under 3 s: Kling refuses them; extend them a little or merge with a neighbour", s="、".join(short)))
    if res["depth"] == "missing":
        notes.append(T("没装深度模型（transformers + torch），这次没出深度视频。更好的做法是用 Video Depth Anything 逐段跑："
                       "`python3 run.py --input_video drive/seg_01.mp4 --output_dir drive --encoder vits --grayscale`（Small 版可商用）",
                       "No depth model installed (transformers + torch), so no depth videos this time. Better: run Video Depth Anything per segment: "
                       "`python3 run.py --input_video drive/seg_01.mp4 --output_dir drive --encoder vits --grayscale` (the Small model allows commercial use)"))
    if notes:
        L += [""] + [f"- {n}" for n in notes]
    for u in plan_units:
        if u["id"] not in res["units"]:
            continue
        L += ["", f"## {u['id']}", "", T("Seedance 2.5（@视频1 = 驱动视频或深度视频，@图片1 = 角色图）：", "Seedance 2.5 (@视频1 = drive or depth video, @图片1 = character image):"),
              "", "```text", u["prompts"]["seedance"], "```", "", T("Kling 动作控制（人物朝向选「跟随视频」）：", "Kling Motion Control (orientation: match the video):"),
              "", "```text", u["prompts"]["kling"], "```", "", T("深度视频驱动：", "Depth-video drive:"), "", "```text", u["prompts"]["depth"], "```"]
    L += ["", T("## 接回原时间线", "## Back onto the timeline"), "",
          T("生成好的每段写进 `drive/results.json`：`{\"seg_01\": \"/绝对路径/seg_01.mp4\", ...}`，再跑 `rea-video drive <报告目录> --join`，"
            "然后 `rea-video remake <报告目录>`。", "List each generated segment in `drive/results.json`: `{\"seg_01\": \"/absolute/path/seg_01.mp4\", ...}`, run "
            "`rea-video drive <report folder> --join`, then `rea-video remake <report folder>`.")]
    return L


def join(out: Path, results: Path | None = None) -> dict:
    """Generated segments -> per-shot clips in remake/mine.json. A shot is filled only when every segment over it is in."""
    from .remake import _fit_clip, _original_segment, frame_bounds

    b = read_json(out / "breakdown.json")
    ddir = out / "drive"
    spec = read_json(ddir / "drive.json")
    got = read_json(results or ddir / "results.json")
    got = got.get("results", got) if isinstance(got, dict) else {}
    paths = {k: Path(v["video"] if isinstance(v, dict) else v) for k, v in got.items() if v}
    src = b["source"]
    w, h = (src["height"], src["width"]) if src.get("rotation") in (90, 270) else (src["width"], src["height"])
    w, h = w - w % 2, h - h % 2
    fps = float(src["fps"]) if src.get("fps") and src["fps"] <= 60 else 30.0
    jdir = ddir / "joined"
    jdir.mkdir(parents=True, exist_ok=True)
    blocks, cur = [], []
    for s in spec["segments"]:
        p = paths.get(s["id"])
        ok = p is not None and p.is_file()
        if ok and cur and cur[-1]["unit"] == s["unit"] and abs(cur[-1]["end"] - s["start"]) < 1e-3:
            cur.append(s)
            continue
        if cur:
            blocks.append(cur)
        cur = [s] if ok else []
    if cur:
        blocks.append(cur)
    mine_p = out / "remake" / "mine.json"
    mine = read_json(mine_p) if mine_p.is_file() else {}
    res = mine.setdefault("results", {})
    filled, missing = [], [s["id"] for s in spec["segments"] if not (paths.get(s["id"]) and paths[s["id"]].is_file())]
    for k, blk in enumerate(blocks, 1):
        fitted = []
        for s in blk:
            f = jdir / f"{s['id']}_fit.mp4"
            _fit_clip(paths[s["id"]], f, max(1, int(round(s["end"] * fps)) - int(round(s["start"] * fps))), (w, h), fps)
            fitted.append(f)
        lst = jdir / f"block_{k:02d}.txt"
        lst.write_text("".join(f"file '{f.resolve()}'\n" for f in fitted), encoding="utf-8")
        whole = jdir / f"block_{k:02d}.mp4"
        _ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(whole)])
        a, z = blk[0]["start"], blk[-1]["end"]
        bounds = frame_bounds(b["shots"], fps)
        for r in b["shots"]:
            if r["start"] >= a - 1e-3 and r["end"] <= z + 1e-3:
                clip = jdir / f"shot_{int(r['index']):03d}.mp4"
                first, n = bounds[r["index"]]
                _original_segment(whole, clip, first - int(round(a * fps)), n, (w, h), fps)
                res[str(r["index"])] = {"video": str(clip.resolve())}
                filled.append(r["index"])
    mine_p.parent.mkdir(parents=True, exist_ok=True)
    write_json(mine_p, mine)
    return {"filled_shots": filled, "missing_segments": missing, "mine": str(mine_p),
            "next": T("跑 `rea-video remake {o}` 出成片和对比片", "run `rea-video remake {o}` for the cut and the side-by-side", o=out)
            + (semi() + T("还缺 {m}", "still missing {m}", m="、".join(missing)) if missing else "")}
