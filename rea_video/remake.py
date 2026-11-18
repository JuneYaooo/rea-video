"""Rebuild a video on the original timeline from remake results.

- generated clips (capsule-cinema)  -> retimed to the original shot, frame-exact: the clip's moves are warped onto
                                       the original's (where they start, peak and stop), within the speed limits
- still_motion / static_hold shots  -> rebuilt locally from one image using the measured
                                       zoom/pan (deterministic, no model call)
- everything else                    -> original footage kept (marked in the compare video)
- with overlays=True, the measured subtitles / 花字 / titles are laid back on over the replaced shots only (kept
  original footage already carries them)
Outputs remake.mp4 (original audio) and compare.mp4 (original | remake side by side)."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .util import LOG, read_json, read_image


def _ff(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, cwd=cwd)


def render_still_motion(image: Path, out: Path, duration: float, size: tuple[int, int], fps: float,
                        zoom_per_s: float = 0.0, pan_px_per_s: float = 0.0, pan_dir_deg: float = 0.0,
                        analysis_width: int = 480) -> Path:
    """Re-create a Ken Burns move: per-frame similarity transform about the frame centre,
    with the zoom rate and pan speed measured during decomposition."""
    img = read_image(image)
    if img is None:
        raise FileNotFoundError(image)
    w, h = size
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    n = max(1, int(round(duration * fps)))
    px_scale = w / float(analysis_width)
    vx = math.cos(math.radians(pan_dir_deg)) * pan_px_per_s * px_scale
    vy = math.sin(math.radians(pan_dir_deg)) * pan_px_per_s * px_scale
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}",
                             "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)], stdin=subprocess.PIPE)
    assert proc.stdin is not None
    # the measured motion maps frame t -> t+1; start slightly zoomed in when zooming out so edges never show
    base = 1.0 + max(0.0, -zoom_per_s * duration) + 0.02 + (abs(vx) + abs(vy)) * duration / max(w, h)
    for i in range(n):
        t = i / fps
        s = base * (1.0 + zoom_per_s * t)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 0, s)
        M[0, 2] += vx * t - vx * duration / 2
        M[1, 2] += vy * t - vy * duration / 2
        frame = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    return out


MAX_SPEEDUP = 3.0   # a generated clip is retimed to the original shot length, up to this much faster
MAX_SLOWDOWN = 1.25  # and up to this much slower; past that the remainder is trimmed / held


def fit_speed(clip_s: float, duration: float) -> float:
    """Playback speed that fits a generated clip into the original shot. Models have a minimum length
    (often 4-5 s), so a 1.2 s shot comes back as 4 s of the same action: playing only its first 1.2 s
    cuts the action off and slows the edit, so the whole clip is sped up instead (within limits)."""
    if clip_s <= 0 or duration <= 0:
        return 1.0
    return max(1 / MAX_SLOWDOWN, min(MAX_SPEEDUP, clip_s / duration))


def _clip_seconds(src: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                           capture_output=True, text=True, check=True)
        return float(r.stdout.strip() or 0)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def frame_bounds(shots: list[dict], fps: float) -> dict[int, tuple[int, int]]:
    """{shot index: (first frame, frame count)} on the original's frame grid. Every segment of a remake is cut to
    exactly its count, so a cut lands on the original's frame and the lengths never add up to a drift against the
    original sound (seconds rounded per segment lose or gain a frame each, a few tenths of a second by the end)."""
    starts = [int(round(sh["start"] * fps)) for sh in shots]
    ends = starts[1:] + [int(round(shots[-1]["end"] * fps))] if shots else []
    return {sh["index"]: (a, max(1, z - a)) for sh, a, z in zip(shots, starts, ends)}


def _exact(fps: float, frames: int) -> tuple[str, list[str]]:
    """The tail of a filter chain and the output flags that make a segment exactly `frames` frames at `fps`: the last
    frame held when the source runs short, the rest cut off."""
    return (f"fps={fps},tpad=stop_mode=clone:stop_duration={frames / fps + 1:.3f}",
            ["-frames:v", str(frames), "-r", f"{fps}"])


WARP_W = 96          # width the motion of a clip is measured at
WARP_STEP_COST = 0.04  # how much a step away from the clip's mean speed costs against matching the motion better


def motion_curve(frames) -> np.ndarray:
    """How much the picture moves at each frame, 0-1 of its largest value: the change in the most-changed block of a
    12 x 8 grid (a small subject moving counts), held 3 frames and smoothed. Flat (all zero) when nothing moves."""
    out, prev = [], None
    for f in frames:
        g = (f if f.ndim == 2 else cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)).astype(np.float32)
        out.append(0.0 if prev is None else float(cv2.resize(np.abs(g - prev), (12, 8), interpolation=cv2.INTER_AREA).max()) / 255.0)
        prev = g
    c = np.array(out)
    if len(c) >= 3:
        c = np.array([c[max(0, i - 2):i + 1].max() for i in range(len(c))])
        c = np.convolve(c, np.ones(3) / 3, mode="same")
    top = float(c.max()) if len(c) else 0.0
    return c / top if top >= 0.03 else np.zeros_like(c)


def warp_map(ref: np.ndarray, gen: np.ndarray) -> list[int] | None:
    """For each frame of the original shot (ref), the frame of the generated clip (gen) to show: a monotonic path that
    lines the clip's moves up with the original's (dynamic time warping on the motion curves), each step 0-3 clip
    frames (at most MAX_SPEEDUP; holds cost more), ending where the even fit would (the whole clip, or as much as
    MAX_SPEEDUP allows). None when either has no motion to line up: the even fit is as good."""
    n, m = len(ref), len(gen)
    if n < 4 or m < 2 or not ref.any() or not gen.any():
        return None
    r = max(1 / MAX_SLOWDOWN, min(MAX_SPEEDUP, m / n))
    end = min(m - 1, int(round((n - 1) * r)))
    steps = (0, 1, 2, 3)
    pen = {k: WARP_STEP_COST * (k - r) ** 2 for k in steps}
    INF = 1e18
    D = np.full((n, m), INF)
    back = np.zeros((n, m), np.int8)
    D[0, 0] = abs(ref[0] - gen[0])
    for i in range(1, n):
        best = np.full(m, INF)
        arg = np.zeros(m, np.int8)
        for k in steps:
            prev = np.full(m, INF)
            prev[k:] = D[i - 1, :m - k] if k else D[i - 1]
            cand = prev + pen[k]
            better = cand < best
            best[better], arg[better] = cand[better], k
        D[i] = best + np.abs(ref[i] - gen)
        back[i] = arg
    if D[n - 1, end] >= INF:
        return None
    path, j = [end], end
    for i in range(n - 1, 0, -1):
        j -= int(back[i, j])
        path.append(j)
    return path[::-1]


def _frames_at(src: Path, fps: float, width: int, start_frame: int = 0, count: int | None = None, gray: bool = False):
    """Frames of src resampled to fps, from frame start_frame (count of them, or to the end), at the given width."""
    from .media import iter_frames, video_info

    info = video_info(str(src))
    it = iter_frames(str(src), info, width, start=start_frame / fps if start_frame else None, gray=gray, fps=fps)
    for k, f in enumerate(it):
        if count is not None and k >= count:
            break
        yield f


def _warp_clip(src: Path, out: Path, path: list[int], size: tuple[int, int], fps: float) -> Path:
    """Write the clip's frames in the order path gives (each clip frame repeated as often as it is used): exactly
    len(path) frames, streamed, never the whole clip in memory."""
    w, h = size
    need: dict[int, int] = {}
    for j in path:
        need[j] = need.get(j, 0) + 1
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}",
                             "-i", "-", "-frames:v", str(len(path)), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)],
                            stdin=subprocess.PIPE)
    assert proc.stdin is not None
    written, last = 0, None
    for j, f in enumerate(_frames_at(src, fps, max(w, int(round(h * 16 / 9))))):
        if j > path[-1]:
            break
        fh, fw = f.shape[:2]
        s = max(w / fw, h / fh)  # cover, then centre crop: as the even fit's scale + crop
        f = cv2.resize(f, (max(w, int(round(fw * s))), max(h, int(round(fh * s)))), interpolation=cv2.INTER_AREA)
        y0, x0 = (f.shape[0] - h) // 2, (f.shape[1] - w) // 2
        last = np.ascontiguousarray(f[y0:y0 + h, x0:x0 + w])
        for _ in range(need.get(j, 0)):
            proc.stdin.write(last.tobytes())
            written += 1
    while last is not None and written < len(path):  # the clip decoded shorter than measured: hold its last frame
        proc.stdin.write(last.tobytes())
        written += 1
    proc.stdin.close()
    if proc.wait() != 0 or written == 0:
        raise RuntimeError(f"warp failed for {src}")
    return out


def fit_to_original(src: Path, out: Path, original: Path, first: int, frames: int, size: tuple[int, int], fps: float) -> str:
    """A generated clip into the original shot's frames: warped so its moves land where the original's do, else
    sped up or slowed down evenly. Returns how ("warped" / "even")."""
    try:
        ref = motion_curve(_frames_at(original, fps, WARP_W, first, frames, gray=True))
        gen = motion_curve(_frames_at(src, fps, WARP_W, gray=True))
        path = warp_map(ref[:frames], gen) if len(ref) >= frames - 1 else None
        if path:
            _warp_clip(src, out, path + [path[-1]] * (frames - len(path)), size, fps)
            return "warped"
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        LOG.warning("timing the clip to the original failed (%s); fitting it evenly", str(exc)[:120])
    _fit_clip(src, out, frames, size, fps)
    return "even"


def _fit_clip(src: Path, out: Path, frames: int, size: tuple[int, int], fps: float) -> Path:
    w, h = size
    speed = fit_speed(_clip_seconds(src), frames / fps)
    tail, flags = _exact(fps, frames)
    vf = f"setpts=PTS/{speed:.4f},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},{tail}"
    _ff(["-i", str(src), "-an", "-vf", vf, *flags, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)])
    return out


def _original_segment(src: Path, out: Path, first: int, frames: int, size: tuple[int, int], fps: float) -> Path:
    """Frames first .. first + frames - 1 of src: seeking half a frame early, so the first one is never skipped, and
    its time reset to zero, so the frame-rate filter does not repeat it (which would shift the whole segment a frame)."""
    w, h = size
    tail, flags = _exact(fps, frames)
    _ff(["-ss", f"{max(0.0, (first - 0.5) / fps):.6f}", "-i", str(src), "-an",
         "-vf", f"setpts=PTS-STARTPTS,scale={w}:{h},{tail}", *flags, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)])
    return out


def replaced_spans(b: dict, legend: list[tuple]) -> list[tuple[float, float]]:
    """Time spans of shots no longer showing the original picture, adjacent ones merged."""
    shots = {sh["index"]: sh for sh in b["shots"]}
    spans: list[list[float]] = []
    for i, how in legend:
        if how in ("original", "code"):  # both already carry their text
            continue
        a, z = shots[i]["start"], shots[i]["end"]
        if spans and abs(spans[-1][1] - a) < 1e-3:
            spans[-1][1] = z
        else:
            spans.append([a, z])
    return [(a, z) for a, z in spans]


def overlay_cues(b: dict, spans: list[tuple[float, float]]) -> tuple[list[dict], list[dict]]:
    """Text layers to lay back on, clipped to the replaced spans, and the stickers there that need an asset by hand.
    A layer cut by a span edge loses its entrance animation, so it does not pop in again mid-line."""
    from .packaging import ANCHOR_KINDS, cjk_count, speech_lines

    pack = b.get("packaging") or {}
    speech = {c["id"] for c in speech_lines(pack.get("text_cues", [])) if c.get("id")}
    cues, stickers = [], []
    for c in pack.get("text_cues", []):
        if c["kind"] == "scene" or c.get("part_of_picture"):
            continue
        # spoken lines and styled text go back on; other OCR reads only when they hold real words, not "8uXrH"-like noise
        if not (c.get("id") in speech or (c["kind"] in ANCHOR_KINDS and c["kind"] != "label") or cjk_count(c.get("text", "")) >= 2):
            continue
        for a, z in spans:
            lo, hi = max(c["t0"], a), min(c["t1"], z)
            if hi - lo >= 0.1:
                cues.append({**c, "t0": lo, "t1": hi, **({"anim_in": None} if lo > c["t0"] + 1e-3 else {}),
                             **({"anim_out": None} if hi < c["t1"] - 1e-3 else {})})
    for st in pack.get("stickers", []):
        if not st.get("in_picture") and st.get("confidence") != "low" and any(min(st["t1"], z) - max(st["t0"], a) >= 0.1 for a, z in spans):
            stickers.append({k: st.get(k) for k in ("id", "kind_zh", "what", "t0", "t1", "bbox", "image")})
    return cues, stickers


def unit_shots(b: dict, results: dict, udir: Path, size: tuple[int, int], fps: float,
               bounds: dict[int, tuple[int, int]] | None = None) -> dict:
    """Generation-unit clips (one call made several shots: results keyed "G2", or "G4-1", "G4-2" for the parts of a
    long shot) -> one clip per shot. The parts are fitted to their lengths and joined; the shots are then cut at the
    source's own cut points, because the model was given the source stretch and follows its timing.
    A unit is used only when every part of it came back."""
    by_unit: dict[str, list[dict]] = {}
    for v in results.values():
        if isinstance(v, dict) and v.get("unit"):
            by_unit.setdefault(v["unit"], []).append(v)
    if not by_unit:
        return {}
    by_index = {r["index"]: r for r in b["shots"]}
    bounds = bounds or frame_bounds(b["shots"], fps)
    out: dict[str, dict] = {}
    udir.mkdir(parents=True, exist_ok=True)
    for uid, got in by_unit.items():
        got.sort(key=lambda v: v.get("part", 1))
        if len(got) < int(got[0].get("parts") or 1) or not all(v.get("video") and Path(v["video"]).is_file() for v in got):
            continue
        fitted = []
        for v in got:
            f = udir / f"{uid}_p{v.get('part', 1)}.mp4"
            _fit_clip(Path(v["video"]), f, max(1, int(round(float(v["trim_to"]) * fps))), size, fps)
            fitted.append(f)
        whole = fitted[0]
        if len(fitted) > 1:
            lst = udir / f"{uid}.txt"
            lst.write_text("".join(f"file '{f.resolve()}'\n" for f in fitted), encoding="utf-8")
            whole = udir / f"{uid}.mp4"
            _ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(whole)])
        at = 0
        for i in got[0].get("shots") or []:
            if i not in by_index or i not in bounds:
                continue
            clip = udir / f"shot_{int(i):03d}.mp4"
            n = bounds[i][1]
            _original_segment(whole, clip, at, n, size, fps)
            out[str(i)] = {"video": str(clip), "unit": uid}
            at += n
    return out


def assemble(breakdown_path: Path, results_path: Path, out_dir: Path | None = None, overlays: bool = False,
             code_video: Path | None = None, extra: dict | None = None) -> str:
    """code_video: a remake of the code-rendered shots on the original timeline (`code-remake`), cut in for them.
    extra: more {shot: {"video": path}} results on top of results_path's (later ones win)."""
    b = read_json(breakdown_path)
    bdir = breakdown_path.parent
    jobs_path = results_path.with_name("jobs.json")
    jobs = {j["shot"]: j for j in read_json(jobs_path)["jobs"]} if jobs_path.is_file() else {}
    results = read_json(results_path).get("results", {}) if results_path.is_file() else {}
    out_dir = out_dir or results_path.parent
    seg_dir = out_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    src = Path(b["source"]["path"])
    w, h = b["source"]["width"], b["source"]["height"]
    if b["source"].get("rotation") in (90, 270):
        w, h = h, w
    w, h = w - w % 2, h - h % 2
    fps = float(b["source"]["fps"]) if b["source"]["fps"] and b["source"]["fps"] <= 60 else 30.0
    results = {**results, **{str(k): v for k, v in (extra or {}).items()}}
    # unit clips (one call, several shots) become per-shot clips; a shot's own clip, given later, still wins
    bounds = frame_bounds(b["shots"], fps)
    results = {**unit_shots(b, results, seg_dir / "units", (w, h), fps, bounds),
               **{k: v for k, v in results.items() if not (isinstance(v, dict) and v.get("unit"))}}
    parts, legend = [], []
    timing: dict[str, str] = {}  # generated shots: warped onto the original's moves, or fitted evenly
    for sh in b["shots"]:
        first, n = bounds[sh["index"]]
        dur = n / fps
        seg = seg_dir / f"shot_{int(sh['index']):03d}.mp4"  # 不用 JSON 里的 id 拼路径，防 ../
        res = results.get(str(sh["index"])) or {}
        job = jobs.get(sh["index"], {})
        if res.get("video") and Path(res["video"]).is_file():
            how = fit_to_original(Path(res["video"]), seg, src, first, n, (w, h), fps)
            legend.append((sh["index"], "generated"))
            timing[str(sh["index"])] = how
        elif code_video and sh["base"]["label"] == "code_render" and Path(code_video).is_file():
            _original_segment(Path(code_video), seg, first, n, (w, h), fps)
            legend.append((sh["index"], "code"))
        elif job.get("executor") == "local_ffmpeg" or sh["base"]["label"] in ("still_motion", "static_hold"):
            m = sh["replication"].get("local", {})
            img = bdir / sh["assets"]["first_frame"]
            render_still_motion(img, seg, dur, (w, h), fps, m.get("zoom_per_s", 0.0), m.get("pan_px_per_s", 0.0),
                                m.get("pan_dir_deg", 0.0), m.get("analysis_width", 480))
            legend.append((sh["index"], "local_still"))
        else:
            _original_segment(src, seg, first, n, (w, h), fps)
            legend.append((sh["index"], "original"))
        parts.append(seg)
    lst = seg_dir / "concat.txt"
    lst.write_text("".join("file '" + str(p.resolve()).replace("'", "'\\''") + "'\n" for p in parts), encoding="utf-8")
    silent = out_dir / "remake_silent.mp4"
    _ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)])
    overlay_log: dict = {}
    if overlays:
        from .packaging import fit_ass_sizes, to_ass

        cues, stickers = overlay_cues(b, replaced_spans(b, legend))
        overlay_log = {"text": len(cues), "stickers_to_add": stickers}
        if cues:
            (out_dir / "overlays_remake.ass").write_text(to_ass(cues, w, h), encoding="utf-8")
            fit_ass_sizes(out_dir / "overlays_remake.ass")
            try:  # relative name + cwd: no filter-string escaping of the path
                _ff(["-i", silent.name, "-vf", "ass=overlays_remake.ass", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                     "remake_overlaid.mp4"], cwd=out_dir)
                silent = out_dir / "remake_overlaid.mp4"
                overlay_log["ass"] = str(out_dir / "overlays_remake.ass")
            except subprocess.CalledProcessError as exc:  # ffmpeg built without libass
                overlay_log["error"] = f"ffmpeg ass filter failed ({exc.returncode}); overlays_remake.ass can be burned in another editor"
                LOG.warning(overlay_log["error"])
    final = out_dir / "remake.mp4"
    if b["source"].get("has_audio"):
        _ff(["-i", str(silent), "-i", str(src), "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)])
    else:
        final = silent
    compare = out_dir / "compare.mp4"
    ch = 720 if h >= 720 else h - h % 2
    label = ",drawtext=text='{t}':x=10:y=10:fontcolor=white:box=1:boxcolor=black@0.5"
    for with_text in (True, False):  # drawtext needs libfreetype; fall back to plain hstack
        la, lb = (label.format(t="original"), label.format(t="remake")) if with_text else ("", "")
        try:
            _ff(["-i", str(src), "-i", str(final), "-filter_complex",
                 f"[0:v]scale=-2:{ch}{la}[a];[1:v]scale=-2:{ch}{lb}[b];[a][b]hstack=inputs=2[v]",
                 "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-shortest", str(compare)])
            break
        except subprocess.CalledProcessError:
            if not with_text:
                raise
    log = {"legend": legend, "remake": str(final), "compare": str(compare), **({"timing": timing} if timing else {}),
           **({"overlays": overlay_log} if overlays else {})}
    (out_dir / "assemble_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.info("remake -> %s ; compare -> %s", final, compare)
    return json.dumps(log, ensure_ascii=False)


GENERATED = ("ai_video", "cg_3d", "anim_2d", "stop_motion", "avatar")


def _asset_words(a) -> str:
    """One thing the user has to bring, in words: kind, where in the frame, what it is."""
    if not isinstance(a, dict):
        return str(a)
    bits = [a.get("where") or "", a.get("description") or ""]
    extra = "，".join(x for x in bits if x)
    return (a.get("kind_zh") or a.get("kind") or "") + (f"（{extra}）" if extra else "")


def _needs(sh: dict) -> list[str]:
    """What the user must supply for this shot, minus the shot itself (a live-action shot is its own footage)."""
    lab = sh["base"]["label"]
    out = []
    for a in (sh.get("replication") or {}).get("user_assets") or []:
        if isinstance(a, dict) and lab == "live_action" and a.get("kind") == "real_footage":
            continue
        w = _asset_words(a)
        if w and w not in out:
            out.append(w)
    return out


def _next_step(sh: dict, plan: dict | None = None) -> str:
    """What still has to happen for a shot that is showing the original."""
    from .i18n import T

    lab = sh["base"]["label"]
    plan = plan or {}
    need = _needs(sh)
    tail = T("（要准备：{a}）", " (bring: {a})", a="、".join(need)) if need else ""
    unit = next((u for u in plan.get("units") or [] if sh["index"] in u.get("shots", [])), None)
    scene = next((s for s in plan.get("shoot") or [] if sh["index"] in s.get("shots", [])), None)
    if (sh.get("replication") or {}).get("executor") == "motion_drive":
        return T("动作驱动：rea-video drive 出驱动视频，按报告「动作驱动」的路线逐段生成，再 drive --join",
                 "motion drive: rea-video drive for the drive clips, generate each segment by a route under “Motion drive”, then drive --join")
    if lab in GENERATED:
        if unit:
            return T("生成 {u}：用报告「生成单元」{u} 的提示词生成", "generate {u}: use the prompt of generation unit {u} in the report", u=unit["id"]) + tail
        return T("生成：用报告「生成单元」的提示词在网页上手动生成，或 remake-plan + remake-run（计费，先 --dry-run）",
                 "generate: paste the report's generation-unit prompt into a video model, or remake-plan + remake-run (paid; --dry-run first)") + tail
    if lab == "live_action":
        if scene:
            return T("拍摄 {s}：按报告「拍摄场次」{s} 拍", "shoot {s}: follow shooting scene {s} in the report", s=scene["id"]) + tail
        return T("拍摄：按报告的拍摄方案拍", "shoot it: follow the report's shooting plan") + tail
    if lab == "screen_capture":
        return T("录屏：按原片的操作重录一遍", "record the screen: redo the same steps")
    if lab == "film_footage":
        return T("影视片段：找到原片对应片段（有版权），或换成自己拍的", "film clip: find it in the source (rights apply) or shoot your own")
    if lab == "code_render":
        return T("代码渲染：交给 HTML 视频框架（如 HyperFrames）按 video/rhythm.md 的节奏和关键帧重做，做好的片段写进 mine.json；要快速草稿加 --code",
                 "code render: rebuild it in an HTML video framework (such as HyperFrames) from the rhythm and key frames in video/rhythm.md "
                 "and add the clip to mine.json; --code makes a quick draft")
    return T("提供素材", "provide the footage") + tail


CODE_DRAFT = 0.6  # a redrawn scene scoring below this against the source is a starting point, not a finished shot


def _code_scores(out: Path) -> list[dict]:
    """Per-scene scores of the code redraw against the source (code/compare/compare.json), if it was scored."""
    p = out / "code" / "compare" / "compare.json"
    return (read_json(p).get("scenes") or []) if p.is_file() else []


def _code_score(scores: list[dict], sh: dict) -> dict | None:
    best, ov = None, 0.0
    for sc in scores:
        o = min(sh["end"], sc["end"]) - max(sh["start"], sc["start"])
        if o > ov:
            best, ov = sc, o
    return best


def remake(out: Path, code: bool = False, overlays: bool = True) -> dict:
    """The whole remake in one pass, as far as it can go without paid generation or the user's own footage:
    with `code`, code-rendered shots get a quick redraw (code-remake; otherwise they are left to an HTML video
    framework and keep the original, unless a code-remake is already there), stills are rebuilt from the measured move, clips already
    generated (remake/results.json from remake-run) or supplied (remake/mine.json, {"results": {"<shot>": {"video": path}}})
    are cut in, everything else keeps the original as a stand-in. Writes remake/remake.mp4, remake/compare.mp4 and
    remake/status.md (per shot: how it is made now and what is still to do). Run it again whenever a clip comes in."""
    from .i18n import T
    from .util import write_json

    out = Path(out)
    b = read_json(out / "breakdown.json")
    rdir = out / "remake"
    rdir.mkdir(exist_ok=True)
    res: dict = {}
    code_video = out / "code" / "remake.mp4"
    if code and any(sh["base"]["label"] == "code_render" for sh in b["shots"]):
        from .code_remake import code_remake

        try:
            if not code_video.is_file():
                cr = code_remake(out)
                res["code_score"] = (cr.get("compare") or {}).get("score")
        except (ValueError, OSError, RuntimeError) as e:
            res["code_error"] = str(e)
    mine = rdir / "mine.json"
    extra = read_json(mine).get("results", {}) if mine.is_file() else {}
    log = json.loads(assemble(out / "breakdown.json", rdir / "results.json", rdir, overlays=overlays,
                              code_video=code_video if code_video.is_file() else None, extra=extra))
    how = dict(log["legend"])
    HOW = {"generated": T("生成 / 你的素材", "generated / your footage"), "code": T("代码重画", "redrawn in code"),
           "local_still": T("静图按测得的运动重建", "still rebuilt with the measured move"), "original": T("原片占位", "original as stand-in")}
    plan = b.get("production_plan") or {}
    scores = _code_scores(out)
    rows, todo = [], []
    for sh in b["shots"]:
        h = how.get(sh["index"], "original")
        nxt = _next_step(sh, plan) if h == "original" else ""
        if h == "code":
            sc = _code_score(scores, sh)
            if sc and sc.get("score") is not None and sc["score"] < CODE_DRAFT:
                h = "code_draft"
                nxt = T("代码重画只是初稿（和原片对比 {p:.0%}）：在 `code/spec.json` 里改，或照报告「代码合成」重写；{adv}",
                        "the code redraw is a first draft ({p:.0%} match): edit `code/spec.json` or rewrite it from “Code composition”; {adv}",
                        p=sc["score"], adv="；".join(sc.get("advice") or []) or T("对照 compare.mp4 看差在哪", "compare with compare.mp4"))
                need = _needs(sh)
                if need:
                    nxt += T("；直接换成你的：{a}", "; use your own: {a}", a="、".join(need))
        rows.append({"shot": sh["index"], "start": sh["start"], "end": sh["end"], "label": sh["base"]["label"], "now": h, "next": nxt})
        if nxt:
            todo.append(sh["index"])
    done = sum(r["end"] - r["start"] for r in rows if r["now"] not in ("original", "code_draft"))
    total = sum(r["end"] - r["start"] for r in rows) or 1.0
    HOW["code_draft"] = T("代码重画（初稿）", "redrawn in code (draft)")
    from .classify import LABEL_ZH
    from .i18n import shot_ids

    # the same job for several shots is one line: one generation unit, one shooting scene
    groups: dict[str, list[int]] = {}
    for r in rows:
        if r["next"]:
            groups.setdefault(r["next"], []).append(r["shot"])
    L = [T("# 复刻进度", "# Remake status"), "",
         T(f"已经做好 {done / total:.0%} 时长；成片 `remake/{Path(log['remake']).name}`，左右对比 `remake/compare.mp4`（没做的镜头先用原片占位）。",
           f"{done / total:.0%} of the running time is done; video `remake/{Path(log['remake']).name}`, side by side `remake/compare.mp4` (shots not done yet show the original)."), ""]
    if groups:
        L += [T("## 还要做", "## Still to do"), ""]
        for k, (what, shots_) in enumerate(groups.items(), 1):
            secs = sum(r["end"] - r["start"] for r in rows if r["shot"] in shots_)
            L.append(T("{k}. {w}（镜头 {s}，共 {t:.1f}s）", "{k}. {w} (shots {s}, {t:.1f}s)", k=k, w=what, s=shot_ids(shots_), t=secs))
        L.append("")
    L += [T("拿到新的镜头视频（生成的或用户自己的）就写进 `remake/mine.json`：`{\"results\": {\"镜头号\": {\"video\": \"绝对路径\"}}}`，再跑一次 `rea-video remake <目录>`。",
           "When a clip comes in (generated or the user's own), add it to `remake/mine.json`: `{\"results\": {\"<shot>\": {\"video\": \"<absolute path>\"}}}`, then run `rea-video remake <folder>` again."),
         "", T("## 逐镜", "## Shot by shot"), "",
         T("| 镜头 | 时间 | 画面类型 | 现在 |", "| Shot | Time | Picture | Now |"), "|---|---|---|---|"]
    for r in rows:
        L.append(f"| #{r['shot']} | {r['start']:.1f}–{r['end']:.1f}s | {LABEL_ZH.get(r['label'], r['label'])} | {HOW[r['now']]} |")
    (rdir / "status.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    write_json(rdir / "status.json", {"replaced_share": round(done / total, 3), "shots": rows})
    res.update({"remake": log["remake"], "compare": log["compare"], "status": str(rdir / "status.md"),
                "replaced_share": round(done / total, 3), "to_do": todo})
    return res
