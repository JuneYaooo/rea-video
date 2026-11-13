"""The drawn layer of rendered shots: scenes, cut-outs, samples and remake scores, on dark and light grounds."""
import cv2
import numpy as np

from rea_video.layers import compare, cutout, layer_mask, layout, measure, sample_points, scene_frames, split_scenes
from rea_video.production import layer_scenes_md


def _dots(seed=0, cx=240, light=False):
    """Dots on an ellipse: light dots on black, or dark dots on white."""
    rng = np.random.default_rng(seed)
    img = np.full((270, 480, 3), 245 if light else 0, np.uint8)
    for _ in range(1500):
        a, r = rng.uniform(0, 2 * np.pi), rng.uniform(0, 1) ** 0.5
        cv2.circle(img, (int(cx + 90 * r * np.cos(a)), int(135 + 60 * r * np.sin(a))), 1,
                   (60, 40, 30) if light else (230, 220, 60), -1)
    return img


def _strokes(x0, light=True):
    """A small line chart: a few strokes in one half of the frame."""
    img = np.full((270, 480, 3), 245 if light else 10, np.uint8)
    ink = (40, 40, 40) if light else (240, 240, 240)
    pts = np.array([[x0 + 20 * i, 200 - int(60 * np.sin(i / 2))] for i in range(9)], np.int32)
    cv2.polylines(img, [pts], False, ink, 2)
    cv2.line(img, (x0, 220), (x0 + 170, 220), ink, 1)
    return img


def _glow(img, colour=(140, 120, 40), radius=150):
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    g = np.exp(-((xx - 240) ** 2 + (yy - 135) ** 2) / (2 * (radius / 2) ** 2))
    return np.clip(img.astype(np.float32) + g[..., None] * np.array(colour, np.float32), 0, 255).astype(np.uint8)


def _video(path, frames, fps=4):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frames[0].shape[1], frames[0].shape[0]))
    for f in frames:
        vw.write(f)
    vw.release()
    return path


def test_layer_follows_the_drawing_on_either_ground():
    for img in (_glow(_dots()), _dots(light=True)):
        m = measure(img)
        assert abs(m["centre"][0] - 0.5) < 0.05 and abs(m["centre"][1] - 0.5) < 0.05
        assert m["box"][0] > 0.25 and m["box"][2] < 0.75  # the ellipse spans x 150-330 of 480
        xs = np.array([p[0] for p in sample_points(img, 500)])
        assert len(xs) == 500 and xs.min() > 0.25 and xs.max() < 0.75
    assert measure(_glow(_dots()))["glow"]["radius"] > 0.05
    assert measure(_dots(light=True))["ground"] in ("#f5f5f5", "#f4f4f4")
    m = measure(_strokes(40))
    assert m["box"][2] < 0.5  # the chart sits in the left half
    assert not sample_points(_dots(), 50, text_boxes=[[0.0, 0.0, 1.0, 1.0]])  # text boxes are blanked
    rgba = cutout(_dots(light=True))
    assert rgba.shape[2] == 4 and rgba[..., 3][0, 0] == 0 and rgba[..., 3].max() > 0


def test_split_scenes_finds_a_rearrangement_without_a_cut():
    for a, b in ((_dots(cx=120), _dots(cx=360)), (_strokes(20), _strokes(280))):
        frames = [a] * 20 + [b] * 20
        maps = np.array([layout(layer_mask(f)).ravel() for f in frames])
        times = np.arange(40) * 0.25
        sc = split_scenes(maps, times, 0.0, 10.0)
        assert len(sc) == 2 and abs(sc[0][1] - 5.0) <= 0.25
        assert split_scenes(maps[:20], times[:20], 0.0, 5.0) == [(0.0, 5.0)]


def test_compare_ranks_remakes_and_ignores_the_ground_colour(tmp_path):
    ref = _video(tmp_path / "ref.mp4", [_glow(_dots())] * 12)
    good = _video(tmp_path / "good.mp4", [_dots(1, light=True)] * 12)  # same shape, dark on a light ground
    bad = np.full((270, 480, 3), 230, np.uint8)
    cv2.circle(bad, (420, 60), 30, (40, 40, 40), -1)
    bad = _video(tmp_path / "bad.mp4", [bad] * 12)
    g = compare(str(ref), str(good), out=tmp_path / "cmp")
    b = compare(str(ref), str(bad))
    assert g["score"] > 0.6 > b["score"]
    assert (tmp_path / "cmp" / "compare_worst.jpg").exists() and (tmp_path / "cmp" / "compare.json").exists()
    assert compare(str(ref), str(ref))["score"] > 0.99


def test_scene_frames_covers_rendered_shots_and_clears_old_files(tmp_path):
    video = _video(tmp_path / "v.mp4", [_strokes(20)] * 20 + [_strokes(280)] * 20)
    shot = {"index": 1, "start": 0.0, "end": 10.0, "deterministic": {"probs": {"code_render": 0.9, "cg_3d": 0.1}}}
    b = {"source": {"path": str(video)}, "shots": [shot]}
    out = tmp_path / "out"
    stale = out / "frames" / "points" / "scene_09.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    res = scene_frames(out, breakdown=b)
    assert [s["id"] for s in res["scenes"]] == ["scene_01", "scene_02"] and not stale.exists()
    sc = res["scenes"][0]
    assert sc["measure"]["box"][2] < 0.5 and sc["track"]
    assert (out / sc["points"]).exists() and (out / sc["frames"]["layer"]).exists()
    shot["base"] = {"label": "cg_3d"}  # relabelled after review: nothing left to write, no empty folder
    assert scene_frames(out, breakdown=b)["scenes"] == []
    assert not (out / "frames").exists()


def test_layer_step_failure_keeps_the_breakdown(tmp_path, monkeypatch):
    import rea_video.layers as layers
    from rea_video.pipeline import decompose

    def boom(*a, **k):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(layers, "scene_frames", boom)
    video = _video(tmp_path / "dots.mp4", [_dots(i % 3) for i in range(24)], fps=8)
    out = tmp_path / "o"
    b = decompose(video, out, use_vlm=False, ocr=False, stems=False, asr=False, speakers=False)
    assert "layer_scenes" not in b
    assert (out / "report.html").exists() and (out / "breakdown.json").exists()


def test_scene_table_follows_the_shot_labels(tmp_path):
    from rea_video.memory import correct
    from rea_video.pipeline import decompose, finalize

    video = _video(tmp_path / "dots.mp4", [_dots(i % 3) for i in range(24)], fps=8)
    out = tmp_path / "o"
    b = decompose(video, out, use_vlm=False, ocr=False, stems=False, asr=False, speakers=False)
    assert b.get("layer_scenes", {}).get("count", 0) >= 1
    assert b["production_plan"].get("layer_scenes")
    assert "画面场景" in (out / "video" / "remake.md").read_text(encoding="utf-8")
    correct(b, label="cg_3d", shots="1", record=False)  # the user says it is a 3D render after all
    finalize(b, out)
    assert not b["production_plan"].get("layer_scenes")


def test_scene_table_text():
    md = "\n".join(layer_scenes_md([{"id": "scene_01", "shot": 1, "start": 0.0, "end": 5.2, "points": "frames/points/scene_01.json",
                                     "measure": {"ground": "#000000", "glow": {"colour": "#507c87", "centre": [0.5, 0.52], "radius": 0.15},
                                                 "colours": [{"hex": "#4e747c"}], "pieces": 286, "box": [0.4, 0.03, 0.6, 0.78]}}]))
    assert "| scene_01 | #1 | 0.0–5.2s | #000000 | #507c87" in md and "rea-video compare" in md and "scene_XX_layer.png" in md
    assert layer_scenes_md([]) == []
