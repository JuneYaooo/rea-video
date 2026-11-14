"""Measured delivery per line: rate, pitch, loudness, pauses and the emotion the recognizer hears, merged into the script."""
import numpy as np

from rea_video import prosody
from rea_video.audio import speaks_in
from rea_video.entities import script
from rea_video.i18n import set_lang

SR = 16000


def _tone(hz: float, s: float, amp: float = 0.3) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * hz * np.arange(int(s * SR)) / SR)).astype(np.float32)


def test_measure_rate_pitch_level_and_pause():
    x = np.concatenate([_tone(200, 1.0), np.zeros(SR, np.float32), _tone(200, 1.0), _tone(320, 1.0, 0.9)])
    lines = [{"start": 0.0, "end": 1.0, "text": "你好你好你好", "speaker": "A"},
             {"start": 2.0, "end": 3.0, "text": "还好", "speaker": "A"},
             {"start": 3.0, "end": 4.0, "text": "one two three four", "speaker": "A"}]
    m = prosody.measure(x, SR, lines)
    assert m[0]["rate"] == 6.0 and m[1]["rate"] == 2.0 and m[2]["unit"] == "en" and m[2]["rate"] == 4.0
    assert abs(m[0]["f0_hz"] - 200) < 5 and m[0]["range_st"] < 1
    assert m[1]["pause_before"] == 1.0 and "pause_before" not in m[2]
    assert m[2]["pitch_rel_st"] >= 7 and m[2]["level_rel"] >= 8  # the high, loud line stands out
    assert prosody.measure(None, SR, lines, pitch=False)[0] == {"unit": "zh", "rate": 6.0}  # the mix: timings only


def test_describe_names_what_stands_out():
    set_lang("zh")
    got = prosody.describe({"unit": "zh", "rate": 7.1, "pitch_rel_st": -7.2, "pause_before": 0.8, "range_st": 6.0}, "angry")
    assert got == "实测：语速快（7.1 字/秒），比这人别的句子低，句前停 0.8 秒；语音模型听着偏生气"
    assert "句前停" not in prosody.describe({"unit": "zh", "rate": 5.0, "pause_before": 0.8}, pause=False)
    assert prosody.describe({}, "") == ""
    assert prosody.emotion_tag("<|HAPPY|>") == "happy" and prosody.emotion_tag("<|NEUTRAL|>") == "" and prosody.emotion_tag(None) == ""


def test_script_carries_the_measured_delivery():
    set_lang("zh")
    heard = [{"start": 0.1, "end": 3.0, "text": "你信不信", "emotion": "happy",
              "prosody": {"unit": "zh", "rate": 7.0, "pause_before": 1.0}}]
    b = {"shots": [], "speech": {"ok": True, "lines": heard}}
    assert script(b)[0]["delivery"] == "实测：语速快（7.0 字/秒），句前停 1.0 秒；语音模型听着偏开心"
    # a reader's line borrows the measure of the transcribed line under it; its own rough timing gives no pause
    b["whole_video_vlm"] = {"narration": {"lines": [{"start": 0.3, "end": 2.8, "text": "你信不信", "delivery": "挑衅"}]}}
    assert script(b)[0]["delivery"] == "挑衅；实测：语速快（7.0 字/秒）；语音模型听着偏开心"


def test_shot_clip_gets_sound_only_where_someone_speaks():
    audio = {"voice": {"segments": [[1.0, 2.0]]}}
    assert speaks_in(audio, 0.0, 1.5) and not speaks_in(audio, 1.9, 4.0) and not speaks_in({"has_audio": False}, 0, 9)
