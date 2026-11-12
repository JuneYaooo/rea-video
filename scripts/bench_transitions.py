"""Transition benchmark: join real shots with known transitions and check what the cut detector reports.

    python3 scripts/bench_transitions.py a.mp4 b.mp4 c.mp4 --out out/bench_transitions --pairs 5

Source shots are taken from the given videos (stretches without a cut). Each case is A (hold) -> transition
(0.3 / 0.6 / 1.0 s) -> B (hold). Editor transitions come from ffmpeg's xfade filter; whip pans, spins, zoom
punches, glitches and shakes are composed here. A case passes detection when exactly one boundary is found
and it sits inside the transition; it passes typing when the reported kind is the expected family."""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rea_video.media import video_info  # noqa: E402
from rea_video.shots import build_track, detect_shots  # noqa: E402

W, H, FPS = 360, 640, 30
HOLD = 2.0

XFADE = {
    "dissolve": ["fade", "fadefast", "fadeslow", "fadegrays", "dissolve"],
    "fade": ["fadeblack", "fadewhite"],
    "wipe": ["wipeleft", "wiperight", "wipeup", "wipedown", "smoothleft", "smoothup", "circleopen", "circleclose", "vertopen",
             "horzclose", "radial", "diagtl", "diagbr", "wipetl", "rectcrop", "circlecrop", "hlslice", "vuslice", "hlwind",
             "coverleft", "coverup", "revealright", "revealdown"],
    "slide": ["slideleft", "slideright", "slideup", "slidedown", "squeezeh", "squeezev"],
    "zoom": ["zoomin"],
    "blur": ["hblur", "pixelize", "distance"],
}
CUSTOM = ["whip_left", "whip_up", "spin", "zoom_punch", "glitch", "shake", "blur"]
CUSTOM_FAMILY = {"whip_left": "whip", "whip_up": "whip", "spin": "spin", "zoom_punch": "zoom", "glitch": "glitch", "shake": "shake",
                 "blur": "blur"}
# kinds the detector may report for each family and still be right; a few effects sit between two families
ACCEPT = {"dissolve": {"dissolve"}, "fade": {"fade"}, "wipe": {"wipe"}, "slide": {"slide"}, "zoom": {"zoom"}, "blur": {"blur"},
          "whip": {"whip"}, "spin": {"spin"}, "glitch": {"glitch"}, "shake": {"shake"}}
ACCEPT_KIND = {"coverleft": {"slide", "wipe"}, "coverup": {"slide", "wipe"}, "revealright": {"slide", "wipe"},
               "revealdown": {"slide", "wipe"}, "squeezeh": {"slide", "wipe"}, "squeezev": {"slide", "wipe"},
               "rectcrop": {"wipe", "fade"}, "circlecrop": {"wipe", "fade"},  # the old shot closes down to black first
               "distance": {"dissolve", "blur", "effect"}, "pixelize": {"blur", "dissolve", "effect"}, "hblur": {"blur", "effect"},
               "zoomin": {"zoom", "effect"}}


STEADY = 14.0  # largest change (mean |difference| of 12x16 block means) allowed between frames 0.3 s apart in a source shot


def source_shots(path: str, n: int, need: int) -> list[np.ndarray]:
    """Up to n stretches of `need` frames without a cut, as [need, H, W, 3] uint8 (centre-cropped to 9:16).
    Only steady stretches are used: when the shot itself lurches (a fight, a whip, a caption card popping in)
    there is no telling where the added transition starts or ends, for a viewer or for the detector."""
    info = video_info(path)
    track = build_track(path, info)
    shots = detect_shots(track)
    fps = info.fps or 30.0
    small = [cv2.resize(t, (12, 16), interpolation=cv2.INTER_AREA).astype(np.float32) for t in track.thumbs]
    k = max(1, int(round(0.3 * fps)))

    def steady(s) -> bool:
        a = s.start_frame + int(round(0.25 * fps))
        z = min(len(small) - k, a + int(round(need / FPS * fps)))
        return z > a and max(float(np.abs(small[i] - small[i + k]).mean()) for i in range(a, z)) <= STEADY

    long = [s for s in shots if s.duration >= need / FPS + 0.6 and steady(s)]
    picks = long[:: max(1, len(long) // n)][:n]
    out = []
    for s in picks:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{s.start + 0.25:.3f}", "-i", path, "-frames:v", str(need), "-r", str(FPS),
                            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", "-f", "rawvideo",
                            "-pix_fmt", "bgr24", "-"], capture_output=True)
        a = np.frombuffer(r.stdout, np.uint8)
        if len(a) >= need * H * W * 3:
            out.append(a[:need * H * W * 3].reshape(need, H, W, 3).copy())
    return out


def pairs_from(videos: list[str], n: int, need: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """n pairs of shots that are different pictures, taking the videos in turn."""
    per = [source_shots(v, n, need) for v in videos]
    pool = [s for i in range(n) for shots in per for s in shots[i:i + 1]]
    pairs = []
    while len(pool) >= 2 and len(pairs) < n:
        a = pool.pop(0)
        small = cv2.resize(a[0], (48, 85)).astype(np.float32)
        j = next((j for j, b in enumerate(pool) if np.abs(cv2.resize(b[0], (48, 85)).astype(np.float32) - small).mean() > 25), None)
        if j is not None:
            pairs.append((a, pool.pop(j)))
    assert len(pairs) == n, f"only {len(pairs)} pairs of different shots in the source videos"
    return pairs


def write(frames, path: Path) -> None:
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
                          "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close()
    p.wait()


def xfade(a: np.ndarray, b: np.ndarray, kind: str, d: int, tmp: Path, out: Path) -> None:
    hold = int(HOLD * FPS)
    write(a[:hold + d], tmp / "a.mp4")
    write(b[:hold + d], tmp / "b.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp / "a.mp4"), "-i", str(tmp / "b.mp4"), "-filter_complex",
                    f"[0:v][1:v]xfade=transition={kind}:duration={d / FPS:.4f}:offset={HOLD:.4f},format=yuv420p", "-c:v", "libx264",
                    "-crf", "18", str(out)], check=True)


def _shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    return np.roll(img, (int(round(dy)), int(round(dx))), axis=(0, 1))


def _mblur(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    k = int(max(abs(dx), abs(dy)))
    if k < 2:
        return img
    ker = np.zeros((k, k), np.float32)
    if abs(dx) >= abs(dy):
        ker[k // 2, :] = 1 / k
    else:
        ker[:, k // 2] = 1 / k
    return cv2.filter2D(img, -1, ker)


def _ease(u: float) -> float:
    return u * u * (3 - 2 * u)


def custom(a: np.ndarray, b: np.ndarray, kind: str, d: int) -> list[np.ndarray]:
    hold = int(HOLD * FPS)
    frames = list(a[:hold])
    rng = np.random.default_rng(d)
    for k in range(d):
        u = (k + 0.5) / d
        src = a[hold + k] if u < 0.5 else b[k]
        if kind in ("whip_left", "whip_up"):
            # the picture streaks away, the cut hides in the blur, the next shot streaks in and settles
            speed = np.sin(np.pi * u) * (W if kind == "whip_left" else H) * 0.9 / max(1, d / 6)
            pos = (_ease(u) - (0 if u < 0.5 else 1)) * (W if kind == "whip_left" else H) * 1.5
            dx, dy = (-pos, 0) if kind == "whip_left" else (0, -pos)
            sx, sy = (speed, 0) if kind == "whip_left" else (0, speed)
            f = _mblur(_shift(src, dx, dy), sx, sy)
        elif kind == "spin":
            ang = (_ease(u) - (0 if u < 0.5 else 1)) * 180
            M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0 + 0.6 * np.sin(np.pi * u))
            f = cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            f = cv2.GaussianBlur(f, (0, 0), 0.5 + 4 * np.sin(np.pi * u))
        elif kind == "zoom_punch":
            s = 1 + 2.5 * _ease(u * 2) if u < 0.5 else 3.5 - 2.5 * _ease(u * 2 - 1)
            if u >= 0.5:
                s = 1 + (s - 1) * 0.6
            M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, s)
            f = cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            f = cv2.GaussianBlur(f, (0, 0), 0.5 + 3 * np.sin(np.pi * u))
        elif kind == "glitch":
            src = a[hold + k] if rng.random() > u else b[k]
            f = src.copy()
            for _ in range(6):  # displaced slices and split colour channels
                y0 = int(rng.integers(0, H - 40))
                hh = int(rng.integers(10, 60))
                f[y0:y0 + hh] = np.roll(f[y0:y0 + hh], int(rng.integers(-60, 60)), axis=1)
            f[..., 2] = np.roll(f[..., 2], int(rng.integers(4, 14)), axis=1)
            f[..., 0] = np.roll(f[..., 0], -int(rng.integers(4, 14)), axis=1)
        elif kind == "shake":
            amp = 40 * np.sin(np.pi * u)
            f = _shift(src, rng.normal(0, amp), rng.normal(0, amp))
            f = cv2.GaussianBlur(f, (0, 0), 0.5 + 1.5 * np.sin(np.pi * u))
        else:  # blur: defocus out of A, cut, focus in on B
            f = cv2.GaussianBlur(src, (0, 0), 0.5 + 14 * np.sin(np.pi * u))
        frames.append(f)
    frames += list(b[d:d + hold])
    return frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs", type=int, default=3)
    ap.add_argument("--durations", default="0.3,0.6,1.0")
    ap.add_argument("--only", default="", help="comma-separated transition names")
    ap.add_argument("--reuse", action="store_true", help="keep clips already rendered in --out")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    durs = [int(round(float(x) * FPS)) for x in args.durations.split(",")]
    need = int(HOLD * FPS) + max(durs) + 2
    only = set(filter(None, args.only.split(",")))
    cases = [(fam, k, True) for fam, ks in XFADE.items() for k in ks] + [(CUSTOM_FAMILY[k], k, False) for k in CUSTOM]
    cases = [c for c in cases if not only or c[1] in only]
    shots = None
    hold = int(HOLD * FPS)
    rows = []
    for p in range(args.pairs):
        for fam, kind, is_x in cases:
            for d in durs:
                f = out / f"{kind}_{d}_{p}.mp4"
                if not (args.reuse and f.is_file()):
                    if shots is None:
                        shots = pairs_from(args.videos, args.pairs, need)
                    a, b = shots[p]
                    if is_x:
                        xfade(a, b, kind, d, out, f)
                    else:
                        write(custom(a, b, kind, d), f)
                cache = f.with_suffix(".track")
                if args.reuse and cache.is_file() and cache.stat().st_mtime >= f.stat().st_mtime:
                    track = pickle.loads(cache.read_bytes())
                else:
                    track = build_track(str(f), video_info(str(f)))
                    cache.write_bytes(pickle.dumps(track))
                found = detect_shots(track)[1:]
                inside = [s for s in found if hold - 2 <= s.start_frame <= hold + d + 2]
                ok = len(found) == 1 and len(inside) == 1
                got = inside[0].transition_in if inside else (found[0].transition_in if found else "none")
                tr = (inside[0].to_dict().get("transition") or {}) if inside else {}
                rows.append({"family": fam, "kind": kind, "frames": d, "pair": p, "found": len(found), "detected": ok, "got": got,
                             "typed": ok and got in ACCEPT_KIND.get(kind, ACCEPT[fam]), "at": [s.start_frame - hold for s in found],
                             "span": [round(tr["start"] - HOLD, 2), round(tr["end"] - HOLD, 2)] if tr.get("end") else None,
                             "direction": tr.get("direction")})
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    by = defaultdict(list)
    for r in rows:
        by[r["family"]].append(r)
    print(f"{'family':10} {'cases':>5} {'found':>6} {'typed':>6}")
    for fam, rs in by.items():
        print(f"{fam:10} {len(rs):5d} {sum(r['detected'] for r in rs) / len(rs):6.2f} {sum(r['typed'] for r in rs) / len(rs):6.2f}")
    print(f"{'all':10} {len(rows):5d} {sum(r['detected'] for r in rows) / len(rows):6.2f} {sum(r['typed'] for r in rows) / len(rows):6.2f}")
    bad = defaultdict(list)
    for r in rows:
        if not r["typed"]:
            bad[r["kind"]].append(f"{r['frames']}f:{r['got']}x{r['found']}")
    if args.verbose:
        for r in rows:
            print(r)
    for k, v in bad.items():
        print(f"  {k}: {' '.join(v)}")


if __name__ == "__main__":
    main()
