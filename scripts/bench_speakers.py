"""Speaker benchmark: build a conversation with known turns out of single-speaker videos and score the speaker split.

    python3 scripts/bench_speakers.py a.mp4 b.mp4 c.mp4 --out /tmp/sb [--music bgm.mp4] [--overlap 0.4]

Each input must be one person talking (a talking head, a voice-over). Their dry voices are cut into turns of
2-7 s and dealt out in turn; with --music a music bed is laid under the result and the vocal stem is separated
again, as the pipeline does. Reports the number of speakers found and the share of speech time given to the
wrong speaker (best one-to-one mapping between found and true speakers)."""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rea_video import speakers  # noqa: E402
from rea_video.stems import SR, load_stereo, save_wav, separate  # noqa: E402


def dry_voice(video: str, out: Path, seconds: float) -> np.ndarray:
    f = out / f"{Path(video).stem}_voice.wav"
    if not f.is_file():
        clip = out / f"{Path(video).stem}_src.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "5", "-t", str(seconds), "-i", video, "-vn", "-ac", "2", "-ar", str(SR),
                        str(clip)], check=True)
        save_wav(separate(load_stereo(clip))[0], f)
    return load_stereo(f)


def main_turns(voice_wav: Path) -> list[tuple[float, float]]:
    """Stretches of the main speaker of a single-speaker source (stray voices in it are left out)."""
    r = speakers.diarize(voice_wav)
    if not r.get("ok") or not r["speakers"]:
        return []
    main = max(r["speakers"], key=lambda s: s["seconds"])["id"]
    return [(t["start"], t["end"]) for t in r["turns"] if t["speaker"] == main and t["end"] - t["start"] >= 2.0]


def score(truth: list[tuple[float, float, int]], found: list[dict], step: float = 0.02) -> dict:
    end = max([b for _, b, _ in truth] + [t["end"] for t in found] + [0.0])
    n = int(end / step) + 1
    names = sorted({t["speaker"] for t in found})
    k_true = max(s for _, _, s in truth) + 1
    T = np.zeros((k_true, n), bool)
    F = np.zeros((max(1, len(names)), n), bool)
    for a, b, s in truth:
        T[s, int(a / step):int(b / step)] = True
    for t in found:
        F[names.index(t["speaker"]), int(t["start"] / step):int(t["end"] / step)] = True
    solo = T.sum(0) == 1  # scored where exactly one person speaks
    best = 0
    for perm in itertools.permutations(range(max(k_true, len(F))), k_true):
        hit = sum(int((T[i] & F[j] & solo).sum()) for i, j in enumerate(perm) if j < len(F))
        best = max(best, hit)
    spoken = int(solo.sum()) or 1
    return {"true_speakers": k_true, "found_speakers": len(names), "wrong_or_missed": round(1 - best / spoken, 3),
            "false_speech_s": round(float((F.any(0) & ~T.any(0)).sum() * step), 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--music", default="", help="a video or audio file whose sound is laid under the conversation")
    ap.add_argument("--music-db", type=float, default=-8.0, help="music level relative to the voices")
    ap.add_argument("--seconds", type=float, default=70.0, help="how much of each source to use")
    ap.add_argument("--overlap", type=float, default=0.0, help="seconds by which each turn starts before the last one ends")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    voices, pools = [], []
    for v in args.videos:
        voices.append(dry_voice(v, out, args.seconds))
        turns = []
        for a, b in main_turns(out / f"{Path(v).stem}_voice.wav"):
            while b - a >= 2.0:  # pieces of 2-7 s
                d = min(b - a, float(rng.uniform(2.0, 7.0)))
                turns.append((a, a + d))
                a += d
        pools.append(turns)
        print(f"{Path(v).stem}: {len(turns)} turns")
    rounds = min(len(p) for p in pools)
    assert rounds >= 2, "a source has too little clean speech"
    total = sum(b - a + 0.7 for p in pools for a, b in p[:rounds]) + 2
    mix = np.zeros((2, int(total * SR)), np.float32)
    truth: list[tuple[float, float, int]] = []
    t = 0.5
    for r in range(rounds):
        for s in rng.permutation(len(pools)):
            a, b = pools[s][r]
            piece = voices[s][:, int(a * SR):int(b * SR)]
            start = max(0.0, t - (args.overlap if truth else 0.0))
            i = int(start * SR)
            mix[:, i:i + piece.shape[1]] += piece
            truth.append((start, start + piece.shape[1] / SR, int(s)))
            t = start + piece.shape[1] / SR + (0.0 if args.overlap else float(rng.uniform(0.1, 0.6)))
    mix = mix[:, :int((t + 0.5) * SR)]
    target = out / "conversation.wav"
    if args.music:
        src = out / "music_src.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", args.music, "-t", f"{mix.shape[1] / SR:.2f}", "-vn",
                        "-ac", "2", "-ar", str(SR), str(src)], check=True)
        bed = load_stereo(src)[:, :mix.shape[1]]
        gain = 10 ** (args.music_db / 20) * float(np.sqrt(np.mean(mix ** 2))) / (float(np.sqrt(np.mean(bed ** 2))) + 1e-9)
        full = mix.copy()
        full[:, :bed.shape[1]] += bed * gain
        save_wav(full, out / "conversation_mix.wav")
        save_wav(separate(full)[0], target)  # what the pipeline hears: the vocal stem of the mix
    else:
        save_wav(mix, target)
    got = speakers.diarize(target)
    assert got.get("ok"), got
    res = score(truth, got["turns"])
    res["speakers"] = [(s["id"], s["seconds"], s.get("f0_median_hz")) for s in got["speakers"]]
    (out / "truth.json").write_text(json.dumps({"truth": truth, "found": got["turns"]}, indent=1))
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
