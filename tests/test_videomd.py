"""VIDEO.md, the package a model reads: a small card, a map, one line per shot, one file per shot, all consistent."""
import json
import re

import videomd as spec

from rea_video import videomd
from rea_video.i18n import set_lang
from rea_video.report import write_reports

from test_report import _with_vlm, breakdown  # noqa: F401  (fixture)


def test_package_levels_and_map(breakdown, tmp_path):  # noqa: F811
    b, out = breakdown
    set_lang("zh")
    write_reports(_with_vlm(b), out)
    card, body = spec.read_file(out / videomd.ENTRY)
    # L0: the card is small and says what the video is and how sure
    assert card["videomd"] == videomd.VERSION and card["generator"]["name"] == "rea-video" and card["shots"] == len(b["shots"]) and card["description"]
    assert videomd.tokens(json.dumps(card, ensure_ascii=False)) < 300
    assert abs(sum(card["made_mix"].values()) - 1) < 0.02
    # L1: every file the map names exists; sizes are given so a reader can choose
    rows = [x["path"] for x in spec.read(out)["map"]]
    assert "video/timeline.md" in rows and "video/shots/*.md" in rows and "breakdown.json" in rows
    assert card["name"] == videomd.slug(card["name"]) and len(card["description"]) <= 1024
    for p in out.glob("video/*.md"):
        fm, text = spec.read_file(p)
        assert fm["videomd"] == videomd.VERSION and fm["tokens"] > 0 and "<details>" not in text
    assert len(list((out / "video" / "shots").glob("*.md"))) == len(b["shots"])


def test_timeline_lines_parse_and_mark_inference(breakdown):  # noqa: F811
    b, out = breakdown
    set_lang("zh")
    write_reports(_with_vlm(b), out)
    pkg = videomd.read(out)
    tl = pkg["timeline"]
    assert [x["shot"] for x in tl] == [r["index"] for r in b["shots"]]
    for x, r in zip(tl, b["shots"]):
        assert abs(x["start"] - r["start"]) < 0.06 and x["made~"].startswith(r["base"]["label_zh"])
        assert set(x) - {"shot", "start", "end"} <= set(videomd.KEYS)
    # the per-shot front matter is the machine view of the same verdict
    for r in b["shots"]:
        fm = pkg["shots"][r["index"]]
        assert fm["inferred"]["made"] == r["base"]["label"] and fm["frames"].get("sheet") == r["assets"]["sheet"]


def test_shot_line_escapes_separators():
    assert videomd._one_line("a | b|c\nd") == "a / b/c d"
    assert videomd.slug("Salted_Egg 最终版") == "salted-egg" and videomd.slug("最终版") == "video"


def test_rewrite_drops_stale_shot_files(breakdown, tmp_path):  # noqa: F811
    b, out = breakdown
    set_lang("zh")
    (out / "video" / "shots").mkdir(parents=True, exist_ok=True)
    (out / "video" / "shots" / "99.md").write_text("old", encoding="utf-8")
    videomd.write(b, out)
    assert not (out / "video" / "shots" / "99.md").exists()


def test_neutral_ids_in_the_package(breakdown):  # noqa: F811
    b, out = breakdown
    set_lang("zh")
    write_reports(_with_vlm(b), out)
    pkg = videomd.read(out)
    assert set(pkg["card"]["readers"]) <= {"tools", "model", "agent", "human"}
    for fm in pkg["shots"].values():
        assert fm["inferred"]["decided_by"] in {"tools", "model", "agent", "human"} and "huazi" not in fm.get("overlays", [])


def test_english_package(breakdown, tmp_path):  # noqa: F811
    b, _ = breakdown
    out = tmp_path / "en"
    out.mkdir()
    try:
        set_lang("en")
        videomd.write(b, out)
    finally:
        set_lang("zh")
    _, body = spec.read_file(out / videomd.ENTRY)
    # the package's own words follow the language (the verdict keeps the language the breakdown was made in)
    assert "## Map" in body and "## How to read" in body and "Each line is `path | ~tokens |" in body


def test_check_accepts_a_written_package_and_names_what_breaks(breakdown, tmp_path):  # noqa: F811
    import shutil

    b, out = breakdown
    set_lang("zh")
    write_reports(_with_vlm(b), out)
    assert videomd.check(out) == []
    bad = tmp_path / "bad"
    shutil.copytree(out, bad)
    p = bad / "video" / "shots" / "01.md"
    p.write_text(p.read_text(encoding="utf-8").replace("made: ", "made: not_a_label # ", 1), encoding="utf-8")
    (bad / "video" / "shots" / "02.md").unlink()
    errs = videomd.check(bad)
    assert any("01.md" in e and "made" in e for e in errs) and any("02.md missing" in e for e in errs)


def test_pdf_needs_a_report_and_a_browser(tmp_path, monkeypatch):
    import pytest

    from rea_video import pdf

    with pytest.raises(RuntimeError, match="report.html"):
        pdf.write_pdf(tmp_path)
    (tmp_path / "report.html").write_text("<details><summary>x</summary>y</details>", encoding="utf-8")
    monkeypatch.setattr(pdf, "find_browser", lambda: None)
    with pytest.raises(RuntimeError, match="Chrome"):
        pdf.write_pdf(tmp_path)
    assert not (tmp_path / ".report_print.html").exists()


def test_sound_effects_are_cut_for_listening(tmp_path):
    import subprocess

    from rea_video.report import _inline
    from rea_video.stems import cut_sfx

    src = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=880:d=3", str(src)], check=True)
    sfx = [{"t": 0.5, "dur": 0.1}, {"t": 2.2, "dur": 0.4}]
    assert cut_sfx(src, sfx, tmp_path) == 2 and sfx[1]["clip"] == "sfx/sfx_02.wav" and (tmp_path / "sfx/sfx_02.wav").is_file()
    assert cut_sfx(tmp_path / "missing.mp4", sfx, tmp_path) == 0 and "clip" not in sfx[0]   # stale clips go away
    assert '<audio controls preload="none" src="sfx/sfx_01.wav"' in _inline("[试听](sfx/sfx_01.wav)")
    assert '<a href="https://x.org/a">' in _inline("[x](https://x.org/a)")


def test_effects_found_on_their_own_track(tmp_path):
    import subprocess

    import numpy as np

    from rea_video import effects

    sr = effects.SR
    y = np.zeros(sr * 4, np.float32)
    for t in (0.5, 1.6, 3.0):  # three short bursts on a silent effects track
        a = int(t * sr)
        y[a:a + int(0.05 * sr)] = np.random.default_rng(1).normal(0, 0.3, int(0.05 * sr))
    y[int(1.75 * sr):int(1.8 * sr)] = 0.2  # a second attack right after the second burst: the same effect
    p = tmp_path / "effects.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", str(p)], input=y.tobytes(), check=True)
    ev = effects.detect(p)
    assert [round(e["t"], 1) for e in ev] == [0.5, 1.6, 3.0]
    assert all(e["source"] == "effects_stem" and e["type"] in ("click", "pop", "ding", "whoosh", "impact", "other") for e in ev)


def test_effects_separation_degrades_without_a_model(tmp_path, monkeypatch):
    import sys
    import types

    from rea_video import effects

    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(InferenceSession=lambda *a, **k: None))
    monkeypatch.setattr(effects, "ensure_model", lambda: (_ for _ in ()).throw(OSError("offline")))
    got = effects.extract_effects(tmp_path / "x.wav", tmp_path)
    assert got["ok"] is False and "offline" in got["reason"]


def test_the_same_effect_used_twice_is_one_sound(tmp_path):
    import subprocess

    import numpy as np

    from rea_video import effects

    sr = effects.SR
    t = np.arange(int(0.3 * sr)) / sr
    ding = (np.sin(2 * np.pi * 1568 * t) * np.exp(-t / 0.08)).astype(np.float32) * 0.5
    noise = np.random.default_rng(2).normal(0, 0.3, int(0.3 * sr)).astype(np.float32) * np.exp(-t / 0.08).astype(np.float32)
    y = np.zeros(sr * 5, np.float32)
    for at, s in ((0.5, ding), (1.5, noise), (3.0, ding)):
        y[int(at * sr):int(at * sr) + len(s)] += s
    p = tmp_path / "effects.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", str(p)], input=y.tobytes(), check=True)
    ev = effects.detect(p)
    groups = effects.group(ev, p)
    assert [len(g["members"]) for g in groups] == [2, 1]                   # the ding twice, the noise burst once
    assert [round(ev[i]["t"], 1) for i in groups[0]["members"]] == [0.5, 3.0]


def test_a_sound_that_never_lands_on_an_edit_is_the_pictures_own(breakdown, tmp_path):  # noqa: F811
    from rea_video.report import _audio_md

    b, _ = breakdown
    set_lang("zh")
    b = dict(b, audio=dict(b.get("audio") or {}, has_audio=True))
    b["audio_plan"] = {"sfx_merged": [{"t": 1.0, "type": "pop", "group": "F1", "in_scene": False, "on": {"what": "字幕出现"}, "clip": "sfx/sfx_01.wav"},
                                      {"t": 2.5, "type": "ding", "group": "F2", "in_scene": True, "clip": "sfx/sfx_02.wav"}],
                       "sfx_groups": [{"id": "F1", "rep": 0, "type": "pop", "count": 1, "times": [1.0], "in_scene": False},
                                      {"id": "F2", "rep": 1, "type": "ding", "count": 1, "times": [2.5], "in_scene": True}]}
    md = "\n".join(_audio_md(b))
    assert "F1" in md and "F2" not in md and "画面自带" not in md   # the picture's own sound is left out of the report


def test_a_sound_on_a_cut_is_added_only_when_it_stands_alone():
    from rea_video.pipeline import _placed_in_edit

    assert _placed_in_edit({"on": {"type": "subtitle_in"}, "level_db": -40, "bed_db": -40})        # lands on a text pop
    assert _placed_in_edit({"on": {"type": "cut"}, "level_db": -17, "bed_db": -180})               # a ding over silence on a cut
    assert not _placed_in_edit({"on": {"type": "cut"}, "level_db": -37, "bed_db": -53})            # the live sound jumping at a cut
    assert not _placed_in_edit({"on": {"type": "cut"}, "level_db": -9, "bed_db": -37})             # a lid twisted on a generated cut
    assert not _placed_in_edit({"level_db": -10, "bed_db": -90})                                   # on nothing at all


def test_silent_stems_mean_no_effects_and_no_music(breakdown, tmp_path):  # noqa: F811
    """A near-silent accompaniment stem drops the mix's beat guess; an effects track with nothing on it means no effects."""
    import numpy as np

    from rea_video.pipeline import finalize

    b, out = breakdown
    set_lang("zh")
    b["audio"] = {"has_audio": True, "music": {"present": True, "tempo_bpm": 120.0}, "voice": {"present": True},
                  "sfx": {"events": [{"t": 1.0, "type": "pop", "source": "deterministic", "confidence": "low"}]}}
    b["stems"] = {"ok": True, "level_db": {"mix": -17.0, "vocals": -17.0, "music": -60.0, "effects": -103.0}}
    fx = out / "stems" / "effects.wav"
    fx.parent.mkdir(parents=True, exist_ok=True)
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", "48000", "-ac", "1", "-i", "-", str(fx)],
                   input=np.zeros(48000 * 3, np.float32).tobytes(), check=True)
    b = finalize(b, out)
    assert not b["audio"]["music"]["present"]
    assert not [e for e in b["audio_plan"]["sfx_merged"] if not e.get("in_scene")]


def test_transitions_are_written_with_spec_ids(breakdown):  # noqa: F811
    b, out = breakdown
    set_lang("zh")
    b["shots"][1]["transition_in"] = "dissolve"
    write_reports(_with_vlm(b), out)
    pkg = spec.read(out)
    assert pkg["shots"][b["shots"][1]["index"]]["transition_in"] == {"type": "dissolve"}
    assert pkg["timeline"][1]["transition"] == "叠化"
    assert "transition_in" not in pkg["shots"][b["shots"][0]["index"]] or b["shots"][0].get("transition_in") not in (None, "cut")
    assert videomd.check(out) == []
