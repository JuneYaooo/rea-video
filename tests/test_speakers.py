"""Speaker separation: grouping, merging, turn bookkeeping and how the result reaches the script and the report.
No model is loaded: voices are made-up unit vectors."""
import numpy as np

from rea_video import speakers
from rea_video.entities import script
from rea_video.report import _speakers_md
from rea_video.speech import SR, _by_speaker


def _voice(axis: int, rng, spread: float = 0.12, dim: int = 16) -> np.ndarray:
    v = rng.normal(0, spread, dim)
    v[axis] += 1.0
    return (v / np.linalg.norm(v)).astype(np.float32)


def test_pieces_of_three_voices_group_into_three():
    rng = np.random.default_rng(0)
    truth = [0, 1, 2, 0, 1, 2, 0, 0, 1, 2, 2, 1] * 3
    V = np.stack([_voice(k, rng) for k in truth])
    labels = speakers._settle(V, speakers.group_pieces(V))
    assert len(set(labels.tolist())) == 3
    for k in range(3):  # every true voice sits in one group
        assert len({labels[i] for i, t in enumerate(truth) if t == k}) == 1
    # a named head count is honoured
    assert len(set(speakers.group_pieces(V, k=2).tolist())) == 2


def test_one_voice_split_three_ways_is_merged_step_by_step_and_a_stray_moment_folded():
    # voice A arrives as three groups (0, 1, 2): 0-1 and 1-2 sound alike, 0-2 only after the first merge
    # voice B is group 3; group 4 is 0.8 s of something nearer to B than to anything else
    turns = [(0, 6, 0), (6, 12, 1), (12, 18, 2), (18, 30, 3), (30, 30.8, 4), (31, 37, 0)]
    base = {0: [1.0, 0.0, 0.0], 1: [0.8, 0.6, 0.0], 2: [0.45, 0.9, 0.0], 3: [0.0, 0.0, 1.0], 4: [0.0, 0.5, 0.86]}

    def measure(ranges):
        if not ranges:
            return None
        groups = {s for a, b, s in turns for x, y in ranges if a <= x and y <= b}
        v = np.sum([base[g] for g in groups], axis=0).astype(np.float32)
        return v / np.linalg.norm(v)

    out = speakers.regroup(turns, measure)
    assert len({s for _, _, s in out}) == 2
    assert len({s for a, _, s in out if a < 18 or a >= 31}) == 1  # all of A together
    assert {s for a, _, s in out if a == 30} == {s for a, _, s in out if a == 18}  # the stray moment went to B
    # asked for a fixed number of speakers: nothing is merged
    assert speakers.regroup(turns, measure, fixed=True) == turns


def test_turns_are_numbered_by_first_appearance_and_joined_across_short_gaps():
    turns = speakers._tidy([(5.0, 7.0, 9), (0.0, 2.0, 4), (2.2, 4.0, 4), (7.0, 7.1, 4), (6.5, 9.0, 4)])
    assert [(t["speaker"], t["start"], t["end"]) for t in turns] == [("S1", 0.0, 4.0), ("S2", 5.0, 7.0), ("S1", 6.5, 9.0)]
    assert speakers.overlaps(turns) == [[6.5, 7.0]]
    assert speakers.speaker_at(turns, 5.0, 6.4) == "S2" and speakers.speaker_at(turns, 20, 21) == ""
    # one stretch of speech 3.0-8.0 holds a change of speaker: cut in the middle of the gap between the turns
    assert speakers.change_points(turns[:2], 3.0, 8.0) == [4.5]
    assert speakers.change_points(turns[:2], 3.0, 4.6) == []  # the second piece would be too short to recognise


def test_speech_is_cut_at_the_speaker_change():
    turns = [{"start": 0.0, "end": 2.0, "speaker": "S1"}, {"start": 2.0, "end": 5.0, "speaker": "S2"}]
    stretch = (0.0, np.zeros(5 * SR, np.float32))
    pieces = _by_speaker([stretch], turns)
    assert [(round(t, 2), len(x)) for t, x in pieces] == [(0.0, 2 * SR), (2.0, 3 * SR)]
    assert _by_speaker([stretch], None) == [stretch]


def test_voices_take_the_names_a_viewer_gave_them():
    who = {"speakers": [{"id": "S1"}, {"id": "S2"}, {"id": "S3"}],
           "turns": [{"start": 0, "end": 4, "speaker": "S1"}, {"start": 4, "end": 9, "speaker": "S2"},
                     {"start": 9, "end": 10, "speaker": "S3"}, {"start": 10, "end": 14, "speaker": "S1"}]}
    lines = [{"start": 0, "end": 4, "speaker": "店主", "text": "a"}, {"start": 4, "end": 9, "speaker": "顾客", "text": "b"},
             {"start": 9, "end": 10.2, "speaker": "顾客", "text": "c"}, {"start": 10.2, "end": 14, "speaker": "店主", "text": "d"}]
    speakers.name_speakers(who, lines)
    assert [sp.get("name") for sp in who["speakers"]] == ["店主", "顾客", None]  # 顾客 is taken by the voice it fits best


def _breakdown() -> dict:
    return {"speakers": {"ok": True, "count": 2, "tracks": {"S1": "voice_S1.wav", "S2": "voice_S2.wav"}, "overlaps": [[3.8, 4.1]],
                         "speakers": [{"id": "S1", "seconds": 8.0, "share": 0.62, "turns": 2, "first": 0.0, "f0_median_hz": 120.0,
                                       "gender_hint": "male"},
                                      {"id": "S2", "seconds": 5.0, "share": 0.38, "turns": 1, "first": 4.0, "name": "顾客"}],
                         "turns": [{"start": 0, "end": 4, "speaker": "S1"}, {"start": 4, "end": 9, "speaker": "S2"},
                                   {"start": 9, "end": 13, "speaker": "S1"}]},
            "speech": {"ok": True, "lines": [{"start": 0.2, "end": 3.9, "text": "欢迎光临", "speaker": "S1"},
                                             {"start": 4.1, "end": 8.8, "text": "这个怎么卖", "speaker": "S2"}]}}


def test_script_and_report_name_the_separated_voices():
    b = _breakdown()
    rows = script(b)
    assert [(r["speaker"], r["voice"]) for r in rows] == [("说话人 1", "S1"), ("顾客", "S2")]
    md = "\n".join(_speakers_md(b))
    assert "2 个声音" in md and "stems/voice_S1.wav" in md and "顾客" in md and "同时说话" in md
    # a VLM script keeps its own names and gains the voice id
    b["whole_video_vlm"] = {"narration": {"lines": [{"start": 0.0, "end": 4.0, "speaker": "店主", "text": "欢迎光临"}]}}
    assert script(b) == [{"start": 0.0, "end": 4.0, "speaker": "店主", "text": "欢迎光临", "voice": "S1"}]
    # one voice only: nothing to tell apart, nothing printed
    b["speakers"]["speakers"] = b["speakers"]["speakers"][:1]
    b["speakers"]["count"] = 1
    assert _speakers_md(b) == [] and "voice" not in script({**b, "whole_video_vlm": {}})[0]


def test_diarize_without_the_extra_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(speakers, "available", lambda: False)
    assert speakers.diarize(tmp_path / "none.wav") == {"ok": False, "reason": "not_installed"}
