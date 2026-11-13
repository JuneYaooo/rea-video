"""The drawn layer of rendered shots, measured for a code remake.

A code-rendered picture is a smooth background (flat colour, gradient, glow, vignette) with something drawn on it
(particles, lines, shapes, charts, text). The drawn layer is whatever stands out from the smooth background, away from
the ground colour, in any direction: light on dark, dark on light, or another colour of the same brightness.

`rea-video frames out/ref` splits rendered shots into scenes (the drawn layer rearranges without a cut), saves
full-size frames, a cut-out of the drawn layer and samples of it per scene, and measures the ground, the background
glow, the drawn colours and where the drawing sits. A remake can then place its graphics on the original's shapes
instead of redrawing them from a description.

`rea-video compare ref remake` scores a remake against the original frame by frame on the drawn layer (where it sits,
how well the shapes overlap, how much there is), so the remake is fixed where it is furthest off. Each video's layer is
taken against its own ground, so a remake on a different ground colour compares without extra steps.
"""
from __future__ import annotations

import heapq
from pathlib import Path

import cv2
import numpy as np

from .features import DETAIL, halo_blur
from .i18n import T
from .media import extract_frame, iter_frames, video_info
from .util import read_json, write_json

WORK_W = 480  # measuring width; positions are written as 0-1 of the frame, so this only sets precision
GRID = (16, 9)  # cells of the layout map (x, y)
SCENE_WIN = 1.5  # seconds compared on each side of a candidate scene change; also the shortest scene kept
SCENE_MOVE = 0.25  # share of the drawn layer that has to move elsewhere in the frame for a new scene


def _hex(bgr) -> str:
    b, g, r = (int(round(float(v))) for v in bgr)
    return f"#{r:02x}{g:02x}{b:02x}"


def ground(bgr: np.ndarray) -> np.ndarray:
    """Background colour: the median of the frame border."""
    border = np.concatenate([bgr[0], bgr[-1], bgr[:, 0], bgr[:, -1]])
    return np.median(border, axis=0)


def contrast(bgr: np.ndarray) -> np.ndarray:
    """How far each pixel stands out from the smooth background, away from the ground: its colour distance to the
    ground colour minus the smooth background's (Lab). Light dots on a dark glow, dark ink on paper, a white road or a
    blue river on a pale map all stand out; the dark gaps between dots inside a glow (closer to the ground) do not."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    g = cv2.cvtColor(ground(bgr).astype(np.uint8)[None, None], cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
    smooth = np.dstack([halo_blur(np.ascontiguousarray(lab[..., c])) for c in range(3)])
    return np.linalg.norm(lab - g, axis=2) - np.linalg.norm(smooth - g, axis=2)


def layer_mask(bgr: np.ndarray, text_boxes: list | None = None) -> np.ndarray:
    """The drawn layer. text_boxes (0-1 x, y, w, h) are blanked, so subtitles and labels are left out."""
    m = contrast(bgr) > DETAIL
    h, w = m.shape
    for x, y, bw, bh in text_boxes or []:
        pad = 0.01
        x0, y0 = int(max(0, x - pad) * w), int(max(0, y - pad) * h)
        x1, y1 = int(min(1, x + bw + pad) * w + 1), int(min(1, y + bh + pad) * h + 1)
        m[y0:y1, x0:x1] = False
    return m


def layout(mask: np.ndarray) -> np.ndarray:
    """Where the drawn layer sits: share of it in each grid cell."""
    d = cv2.resize(mask.astype(np.float32), GRID, interpolation=cv2.INTER_AREA)
    s = float(d.sum())
    return d / s if s > 0 else d


def _colours(pixels: np.ndarray, k: int = 3) -> list[dict]:
    """Main colours of a set of BGR pixels, as hex with their share."""
    if len(pixels) < 10:
        return []
    px = pixels.astype(np.float32)
    if len(px) > 6000:
        px = px[np.random.default_rng(0).choice(len(px), 6000, replace=False)]
    k = min(k, len(np.unique(px, axis=0)))
    cv2.setRNGSeed(0)
    _, lbl, centers = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 2,
                                 cv2.KMEANS_PP_CENTERS)
    share = np.bincount(lbl.ravel(), minlength=k) / len(lbl)
    return [{"hex": _hex(centers[i]), "share": round(float(share[i]), 2)} for i in np.argsort(-share) if share[i] >= 0.05]


def measure(bgr: np.ndarray, text_boxes: list | None = None) -> dict:
    """Ground, background glow (colour, centre, radius), drawn colours, how many separate pieces and how big, where
    the drawing sits and how much of the frame it covers. Positions are 0-1 of the frame."""
    h, w = bgr.shape[:2]
    gf = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = ground(bgr)
    out: dict = {"ground": _hex(g)}
    gl = float(cv2.cvtColor(g.astype(np.uint8)[None, None], cv2.COLOR_BGR2GRAY)[0, 0])
    lift = np.abs(halo_blur(gf) - gl)  # the smooth background's departure from the ground: glow, vignette, gradient
    if lift.max() > 6:
        on = lift > lift.max() * 0.5
        ys, xs = np.nonzero(on)
        wts = lift[on]
        peak = np.unravel_index(int(np.argmax(lift)), lift.shape)
        blur = cv2.resize(cv2.GaussianBlur(cv2.resize(bgr, (max(1, w // 4), max(1, h // 4))), (0, 0), max(h, w) / 80.0), (w, h))
        out["glow"] = {"colour": _hex(blur[peak]), "centre": [round(float((xs * wts).sum() / wts.sum()) / w, 3),
                                                             round(float((ys * wts).sum() / wts.sum()) / h, 3)],
                       "radius": round(float(np.sqrt(on.sum() / np.pi)) / w, 3)}
    m = layer_mask(bgr, text_boxes)
    n = int(m.sum())
    out["cover"] = round(n / float(h * w), 4)
    if n < 10:
        return out
    out["colours"] = _colours(bgr[m])
    ys, xs = np.nonzero(m)
    out["box"] = [round(float(np.percentile(xs, 2)) / w, 3), round(float(np.percentile(ys, 2)) / h, 3),
                  round(float(np.percentile(xs, 98)) / w, 3), round(float(np.percentile(ys, 98)) / h, 3)]
    out["centre"] = [round(float(xs.mean()) / w, 3), round(float(ys.mean()) / h, 3)]
    n_cc, _, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    if len(areas):
        out["pieces"] = int(n_cc - 1)
        out["piece_area"] = round(float(np.median(areas)) / float(h * w), 6)  # median piece, share of the frame
    return out


def sample_points(bgr: np.ndarray, n: int = 4000, text_boxes: list | None = None) -> list[list[float]]:
    """Up to n pixels of the drawn layer as [x, y, r, g, b, a] (x, y 0-1; colour 0-255; a = how strongly the pixel
    stands out, 0-1), picked with probability by that strength: targets to place particles, dots or strokes on."""
    c = contrast(bgr)
    m = layer_mask(bgr, text_boxes)
    ys, xs = np.nonzero(m)
    if not len(xs):
        return []
    wts = c[ys, xs]
    pick = np.random.default_rng(0).choice(len(xs), size=min(n, len(xs)), replace=False, p=wts / wts.sum())
    h, w = c.shape
    top = float(wts.max()) or 1.0
    return [[round(float(xs[i] + 0.5) / w, 4), round(float(ys[i] + 0.5) / h, 4), *[int(v) for v in bgr[ys[i], xs[i]][::-1]],
             round(float(wts[i]) / top, 2)] for i in pick]


def cutout(bgr: np.ndarray, text_boxes: list | None = None) -> np.ndarray:
    """The drawn layer as an RGBA image (BGRA for OpenCV): the frame's colours, alpha by how strongly each pixel
    stands out from the smooth background; text left out."""
    c = np.clip(contrast(bgr) / 100.0, 0, 1)
    c[~cv2.dilate(layer_mask(bgr, text_boxes).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)] = 0
    return np.dstack([bgr, (c * 255).astype(np.uint8)])


def _text_boxes(out: Path, b: dict) -> list[tuple[float, float, list]]:
    """Where text sits and when: every OCR read stored on the shots, plus the packaging timeline once it is written
    (decompose measures the layer before that file exists)."""
    boxes = [(float(it["t"]) - 0.6, float(it["t"]) + 0.6, it["bbox"]) for s in b.get("shots", [])
             for it in (s.get("text") or {}).get("items", []) if it.get("bbox") and it.get("t") is not None]
    tl = out / "packaging" / "timeline.json"
    if tl.exists():
        boxes += [(float(x["t0"]), float(x["t1"]), x["bbox"]) for x in read_json(tl).get("text", []) if x.get("bbox")]
    return boxes


def _boxes_at(boxes, t: float, until: float | None = None) -> list:
    """Text boxes on screen at t (or at any time in t..until): OCR misses text on some frames, so a scene blanks
    every box seen during it."""
    z = t if until is None else until
    return [b for t0, t1, b in boxes if t0 - 0.3 <= z and t <= t1 + 0.3]


def split_scenes(maps: np.ndarray, times: np.ndarray, start: float, end: float) -> list[tuple[float, float]]:
    """Scene changes inside one shot: where the layout before and after differs (share of the drawn layer that sits
    elsewhere) by more than SCENE_MOVE beyond how much it varies within each side. maps: one flattened layout per
    sampled time."""
    if len(times) < 2:
        return [(start, end)]
    step = float(np.median(np.diff(times)))
    win = max(1, int(round(SCENE_WIN / step)))
    score = np.zeros(len(times))
    for i in range(win, len(times) - win + 1):
        a, b = maps[i - win:i], maps[i:i + win]
        spread = 0.5 * (0.5 * np.abs(a - a.mean(0)).sum(1).mean() + 0.5 * np.abs(b - b.mean(0)).sum(1).mean())
        score[i] = 0.5 * np.abs(a.mean(0) - b.mean(0)).sum() - spread
    cuts: list[float] = []
    for i in np.argsort(-score):
        if score[i] < SCENE_MOVE:
            break
        t = float(times[i])
        if t - start < SCENE_WIN or end - t < SCENE_WIN or any(abs(t - c) < SCENE_WIN for c in cuts):
            continue
        lo, hi = max(0, i - win), min(len(score), i + win + 1)
        if score[i] >= score[lo:hi].max():
            cuts.append(t)
    edges = [start, *sorted(cuts), end]
    return list(zip(edges[:-1], edges[1:]))


def shot_label(shot: dict) -> str | None:
    """The shot's current label: after review / correction when there is one, else the measured one."""
    base = (shot.get("base") or {}).get("label")
    if base:
        return base
    probs = (shot.get("deterministic") or {}).get("probs") or {}
    return max(probs, key=probs.get) if probs else None


def _clear(fdir: Path) -> None:
    """Drop what an earlier run wrote, so a rerun with fewer scenes leaves no stale files behind."""
    for p in [*fdir.glob("scene_*.jpg"), *fdir.glob("scene_*.png"), *(fdir / "points").glob("scene_*.json"), fdir / "scenes.json"]:
        p.unlink(missing_ok=True)
    for d in (fdir / "points", fdir):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


def scene_frames(out: Path, every: float = 0.25, n_points: int = 4000, all_shots: bool = False, breakdown: dict | None = None) -> dict:
    """Scenes, full-size frames, a cut-out of the drawn layer, measurements and samples for the rendered shots of a
    breakdown (all shots with all_shots). Frames are measured as they are decoded, so memory does not grow with
    shot length."""
    out = Path(out)
    b = breakdown if breakdown is not None else read_json(out / "breakdown.json")
    video = (b.get("source") or {}).get("path")
    if not video or not Path(video).exists():
        raise FileNotFoundError(T("找不到原视频 {p}（breakdown.json 的 source.path）", "source video not found: {p} (source.path in breakdown.json)", p=video))
    fdir = out / "frames"
    _clear(fdir)
    shots = [s for s in b.get("shots", []) if all_shots or shot_label(s) == "code_render"]
    if not shots:
        return {"video": video, "every": every, "scenes": []}
    info = video_info(video)
    boxes = _text_boxes(out, b)
    (fdir / "points").mkdir(parents=True, exist_ok=True)
    full_w = min(1080, info.display_size[0] or 1080)
    scenes: list[dict] = []
    for s in shots:
        st, en = float(s["start"]), float(s["end"])
        maps, times, track = [], [], []
        for i, f in enumerate(iter_frames(video, info, WORK_W, start=st, duration=en - st, fps=1.0 / every)):
            t = st + i * every
            m = layer_mask(f, _boxes_at(boxes, t))
            maps.append(layout(m).ravel())
            times.append(t)
            ys, xs = np.nonzero(m)
            if len(xs) >= 10:  # how the drawing moves: centre, horizontal spread and cover over time
                track.append([round(t, 2), round(float(xs.mean()) / f.shape[1], 3), round(float(ys.mean()) / f.shape[0], 3),
                              round(float(xs.std()) / f.shape[1], 3), round(float(m.mean()), 4)])
        if not times:
            continue
        for a, z in split_scenes(np.array(maps), np.array(times), st, en):
            sid = f"scene_{len(scenes) + 1:02d}"
            mid = (a + z) / 2
            rec = {"id": sid, "shot": s.get("index"), "start": round(a, 2), "end": round(z, 2), "frames": {}}
            for tag, t in (("start", a + min(0.15, (z - a) / 4)), ("mid", mid), ("end", max(a, z - min(0.15, (z - a) / 4)))):
                p = fdir / f"{sid}_{tag}.jpg"
                extract_frame(video, t, p, full_w)
                rec["frames"][tag] = f"frames/{p.name}"
            full = cv2.imread(str(fdir / f"{sid}_mid.jpg"))
            if full is not None:
                in_scene = _boxes_at(boxes, a, z)
                cv2.imwrite(str(fdir / f"{sid}_layer.png"), cutout(full, in_scene))
                rec["frames"]["layer"] = f"frames/{sid}_layer.png"
                img = cv2.resize(full, (WORK_W, max(1, round(full.shape[0] * WORK_W / full.shape[1]))), interpolation=cv2.INTER_AREA)
                rec["measure"] = measure(img, in_scene)
                write_json(fdir / "points" / f"{sid}.json", {"time": round(mid, 2), "format": "x y r g b a",
                                                             "points": sample_points(img, n_points, in_scene)})
                rec["points"] = f"frames/points/{sid}.json"
            rec["track"] = [r for r in track if a <= r[0] < z]
            scenes.append(rec)
    res = {"video": video, "every": every, "track_format": "t cx cy spread cover", "scenes": scenes}
    write_json(fdir / "scenes.json", res)
    return res


def _score(fa: np.ndarray, fb: np.ndarray, k: np.ndarray) -> dict:
    ma, mb = layer_mask(fa), layer_mask(fb)
    place = 1.0 - 0.5 * float(np.abs(layout(ma) - layout(mb)).sum()) if ma.any() and mb.any() else float(ma.any() == mb.any())
    ua, ub = cv2.dilate(ma.astype(np.uint8), k) > 0, cv2.dilate(mb.astype(np.uint8), k) > 0
    hit_a = float((ma & ub).sum()) / max(1, int(ma.sum()))
    hit_b = float((mb & ua).sum()) / max(1, int(mb.sum()))
    shape = 2 * hit_a * hit_b / (hit_a + hit_b) if hit_a + hit_b else (1.0 if not ma.any() and not mb.any() else 0.0)
    ca, cb = float(ma.mean()), float(mb.mean())
    amount = min(ca, cb) / max(ca, cb) if max(ca, cb) > 0 else 1.0
    # equal weight on where it sits and on the shapes themselves; how much is drawn counts half as much
    return {"place": round(place, 3), "shape": round(shape, 3), "amount": round(amount, 3),
            "score": round(0.4 * place + 0.4 * shape + 0.2 * amount, 3)}


def compare(ref: str, remake: str, every: float = 0.5, out: Path | None = None, scenes: Path | None = None,
            worst: int = 8) -> dict:
    """Frame-by-frame score of a remake against the original on the drawn layer. Both videos are decoded side by
    side and only the worst frames are kept, so memory does not grow with length."""
    ri, mi = video_info(ref), video_info(remake)
    dur = min(ri.duration, mi.duration)
    k = np.ones((5, 5), np.uint8)
    rows: list[dict] = []
    keep: list = []  # min-heap on -score: the `worst` lowest-scoring frames with their pictures
    pairs = zip(iter_frames(ref, ri, WORK_W, start=0, duration=dur, fps=1.0 / every),
                iter_frames(remake, mi, WORK_W, start=0, duration=dur, fps=1.0 / every))
    for i, (fa, fb) in enumerate(pairs):
        fb = cv2.resize(fb, (fa.shape[1], fa.shape[0]))
        r = {"t": round(i * every, 2), **_score(fa, fb, k)}
        rows.append(r)
        if out:
            item = (-r["score"], i, fa, fb)
            if len(keep) < worst:
                heapq.heappush(keep, item)
            elif item[0] > keep[0][0]:
                heapq.heapreplace(keep, item)
    if not rows:
        raise ValueError(T("没有可比较的帧", "no frames to compare"))
    res: dict = {"ref": ref, "remake": remake, "every": every,
                 **{k2: round(float(np.mean([r[k2] for r in rows])), 3) for k2 in ("score", "place", "shape")}, "frames": rows}
    if scenes and Path(scenes).exists():
        per = []
        for sc in read_json(scenes).get("scenes", []):
            rs = [r for r in rows if sc["start"] <= r["t"] < sc["end"]]
            if rs:
                per.append({"id": sc["id"], "start": sc["start"], "end": sc["end"],
                            "score": round(float(np.mean([r["score"] for r in rs])), 3),
                            "shape": round(float(np.mean([r["shape"] for r in rs])), 3)})
        res["scenes"] = sorted(per, key=lambda x: x["score"])
    res["worst"] = sorted(r["t"] for r in sorted(rows, key=lambda r: r["score"])[:worst])
    if out:
        out.mkdir(parents=True, exist_ok=True)
        cells = []
        for _, i, fa, fb in sorted(keep, key=lambda x: x[1]):
            r = rows[i]
            row = np.hstack([fa, np.full((fa.shape[0], 6, 3), 128, np.uint8), fb])
            cv2.putText(row, f"{r['t']:.1f}s score {r['score']:.2f} (place {r['place']:.2f} shape {r['shape']:.2f})", (8, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
            cells.append(row)
        if cells:
            cv2.imwrite(str(out / "compare_worst.jpg"), np.vstack(cells), [cv2.IMWRITE_JPEG_QUALITY, 88])
            res["sheet"] = str(out / "compare_worst.jpg")
        write_json(out / "compare.json", res)
    return res


def drawn_colours(frames: list[np.ndarray]) -> list[str]:
    """Colours of the drawn layer of a shot (ground and smooth background left out), most common first."""
    px = [f[layer_mask(f)] for f in frames if f is not None]
    px = [p for p in px if len(p)]
    if not px:
        return []
    return [c["hex"] for c in _colours(np.concatenate(px), k=4)]
