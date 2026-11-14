"""How each line is said, measured: speaking rate, pitch movement, loudness against the other lines, the pause
before it, and the emotion the speech recognizer hears.

A reader writing "急促" or "带笑" guesses; a TTS voice needs numbers it can follow (rate, where to pause, which line
is louder or higher). Pitch and loudness are only measured on the separated vocal track: music under the voice
gives a wrong pitch and a wrong level. Rate and pauses come from the line timings and hold on the mix too.
"""
from __future__ import annotations

import re

import numpy as np

from .i18n import LangDict, T

FRAME_S, HOP_S = 0.04, 0.02
SLOW, FAST = {"zh": 3.5, "en": 2.0}, {"zh": 6.5, "en": 3.3}  # characters / words per second
FLAT_ST, WIDE_ST = 2.5, 10.0  # pitch spread inside a line (10th to 90th percentile, semitones); voiced cartoons sit at 8-11
SPREAD_ST = 3.0  # spread against the median line: what sets one line apart in an already lively voice
LOUD_DB, HIGH_ST, PAUSE_S = 4.0, 2.0, 0.6  # against the median line (same speaker for pitch)
EMOTION = LangDict({"happy": "开心", "sad": "难过", "angry": "生气", "fearful": "害怕", "surprised": "惊讶", "disgusted": "厌恶"},
                   en={"happy": "happy", "sad": "sad", "angry": "angry", "fearful": "fearful", "surprised": "surprised",
                       "disgusted": "disgusted"})
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def emotion_tag(raw) -> str:
    """SenseVoice's emotion token ("<|HAPPY|>") to a key of EMOTION; neutral and unknown give ""."""
    s = str(raw or "").strip("<|>").lower()
    return s if s in EMOTION else ""


def units(text: str) -> tuple[int, str]:
    """Spoken units in a line: characters for CJK text, words otherwise."""
    n = len(_CJK.findall(text or ""))
    if n:
        return n, "zh"
    return len(re.findall(r"[A-Za-z0-9']+", text or "")), "en"


def _frames(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Per frame (pitch in Hz or 0, level in dB)."""
    n, h = int(FRAME_S * sr), int(HOP_S * sr)
    lo, hi = int(sr / 400), int(sr / 70)
    f0, db = [], []
    for s in range(0, max(0, len(x) - n), h):
        seg = x[s:s + n] - x[s:s + n].mean()
        rms = float(np.sqrt(np.mean(seg ** 2)))
        db.append(20 * np.log10(rms + 1e-9))
        ac = np.correlate(seg, seg, "full")[n - 1:]
        if rms < 0.01 or ac[0] <= 0 or hi >= len(ac):
            f0.append(0.0)
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        f0.append(sr / lag if ac[lag] / ac[0] > 0.45 else 0.0)
    return np.array(f0), np.array(db)


def measure(x: np.ndarray | None, sr: int, lines: list[dict], pitch: bool = True) -> list[dict]:
    """One dict per line: rate (+unit), pause before, and with pitch=True (a clean vocal track) the pitch, its
    spread and the level, each also relative to the other lines. Lines without times give {}."""
    out: list[dict] = []
    prev_end = None
    for ln in lines:
        a, z = ln.get("start"), ln.get("end")
        if not isinstance(a, (int, float)) or not isinstance(z, (int, float)) or z - a < 0.3:
            out.append({})
            continue
        n, unit = units(ln.get("text") or "")
        m: dict = {"unit": unit}
        if n:
            m["rate"] = round(n / (z - a), 1)
        if prev_end is not None and a - prev_end >= PAUSE_S:
            m["pause_before"] = round(a - prev_end, 1)
        prev_end = z
        if pitch and x is not None:
            f0, db = _frames(x[int(a * sr):int(z * sr)], sr)
            voiced = f0[f0 > 0]
            if len(voiced) >= 8:
                p10, p50, p90 = np.percentile(voiced, [10, 50, 90])
                m.update(f0_hz=round(float(p50), 1), range_st=round(float(12 * np.log2(p90 / p10)), 1))
            if len(db):
                m["level_db"] = round(float(np.percentile(db, 75)), 1)
        out.append(m)
    _relative(out, lines)
    return out


def _relative(ms: list[dict], lines: list[dict]) -> None:
    """Level against the median line, pitch against the median line of the same speaker (three lines or more)."""
    lv = [m["level_db"] for m in ms if "level_db" in m]
    if len(lv) >= 3:
        med = float(np.median(lv))
        for m in ms:
            if "level_db" in m:
                m["level_rel"] = round(m["level_db"] - med, 1)
    sp = [m["range_st"] for m in ms if "range_st" in m]
    if len(sp) >= 3:
        med = float(np.median(sp))
        for m in ms:
            if "range_st" in m:
                m["range_rel_st"] = round(m["range_st"] - med, 1)
    by: dict[str, list[float]] = {}
    for m, ln in zip(ms, lines):
        if "f0_hz" in m:
            by.setdefault(str(ln.get("speaker") or ""), []).append(m["f0_hz"])
    for m, ln in zip(ms, lines):
        hz = by.get(str(ln.get("speaker") or ""), [])
        if "f0_hz" in m and len(hz) >= 3:
            m["pitch_rel_st"] = round(float(12 * np.log2(m["f0_hz"] / np.median(hz))), 1)


def describe(m: dict | None, emotion: str = "", pause: bool = True) -> str:
    """The measured delivery in a few words: "实测：语速快（6.8 字/秒），音调起伏大，句前停 0.8 秒；语音模型听着偏开心".
    Only what stands out is named, except the rate, which a voice always needs."""
    m = m or {}
    bits = []
    if m.get("rate"):
        u = m.get("unit", "zh")
        speed = (T("快", "fast") if m["rate"] > FAST[u] else T("慢", "slow") if m["rate"] < SLOW[u] else T("正常", "normal"))
        bits.append(T("语速{s}（{r} 字/秒）", "rate {s} ({r} words/s)", s=speed, r=m["rate"]) if u == "zh"
                    else T("语速{s}（{r} 词/秒）", "rate {s} ({r} words/s)", s=speed, r=m["rate"]))
    if "range_st" in m:
        if m["range_st"] >= WIDE_ST:
            bits.append(T("音调起伏大", "wide pitch movement"))
        elif m["range_st"] <= FLAT_ST:
            bits.append(T("音调平", "flat pitch"))
        elif m.get("range_rel_st", 0) >= SPREAD_ST:
            bits.append(T("起伏比别的句子大", "more pitch movement than the other lines"))
        elif m.get("range_rel_st", 0) <= -SPREAD_ST:
            bits.append(T("起伏比别的句子平", "flatter than the other lines"))
    if m.get("pitch_rel_st", 0) >= HIGH_ST:
        bits.append(T("比这人别的句子高", "higher than this speaker's other lines"))
    elif m.get("pitch_rel_st", 0) <= -HIGH_ST:
        bits.append(T("比这人别的句子低", "lower than this speaker's other lines"))
    if m.get("level_rel", 0) >= LOUD_DB:
        bits.append(T("比别的句子响", "louder than the other lines"))
    elif m.get("level_rel", 0) <= -LOUD_DB:
        bits.append(T("比别的句子轻", "quieter than the other lines"))
    if pause and m.get("pause_before"):
        bits.append(T("句前停 {p} 秒", "{p}s pause before", p=m["pause_before"]))
    text = T("，", ", ").join(bits)
    if emotion in EMOTION:
        text += (T("；", "; ") if text else "") + T("语音模型听着偏{e}", "speech model hears {e}", e=EMOTION[emotion])
    return T("实测：", "measured: ") + text if text else ""
