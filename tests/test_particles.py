"""Particle / point-cloud graphics on black: rendered by code, not 3D, AI or night footage."""
import cv2
import numpy as np

from rea_video.classify import deterministic
from rea_video.features import spatial_features
from rea_video.plan import code_scene
from rea_video.production import lit_colours, report_md


def _particles(seed=0):
    rng = np.random.default_rng(seed)
    img = np.zeros((270, 480, 3), np.uint8)
    for _ in range(1500):  # glowing dots sampled on an ellipse, like a particle organ
        a = rng.uniform(0, 2 * np.pi)
        r = rng.uniform(0, 1) ** 0.5
        x, y = int(240 + 90 * r * np.cos(a)), int(135 + 60 * r * np.sin(a))
        cv2.circle(img, (x, y), 1, (230, 220, 60), -1)
    return img


def _shaded():
    img = np.zeros((270, 480, 3), np.uint8)
    yy, xx = np.mgrid[0:270, 0:480]
    d = np.sqrt((xx - 240) ** 2 + (yy - 135) ** 2)
    ball = np.clip(255 * (1 - d / 90), 0, 255).astype(np.uint8)  # a smoothly shaded sphere on black
    img[..., 1] = ball
    img[..., 2] = ball
    return img


def _feat(img):
    f = spatial_features(img)
    f.update({"dup_ratio": 0.0, "moving_pair_ratio": 1.0, "camera": "smooth_move", "temporal_noise": 0.5, "zero_pixel_ratio": 0.6})
    return f


def test_fine_dark_separates_particles_from_shaded_surfaces():
    fp, fs = _feat(_particles()), _feat(_shaded())
    assert fp["lit_smooth"] < 0.3 and fp["lit_peaks"] > 4
    assert fs["lit_smooth"] > 0.5
    probs, ev, facts = deterministic(fp)
    assert facts["fine_dark"] > 0.5
    assert max(probs, key=probs.get) == "code_render"
    assert any("粒子" in e for e in ev)
    _, _, facts_s = deterministic(fs)
    assert facts_s["fine_dark"] < 0.1


def test_code_scene_and_report_table(tmp_path):
    cv2.imwrite(str(tmp_path / "a.jpg"), _particles())
    assert lit_colours([tmp_path / "a.jpg"])[0] in ("青", "白")
    shot = {"deterministic": {"facts": {"fine_dark": 0.9}}, "features": {"camera": "smooth_move", "zoom_per_s": 0.05},
            "review": {"description": "青色粒子拼成的胶囊"},
            "text": {"tracks": [{"kind": "subtitle", "texts": ["字幕"]}, {"kind": "title", "texts": ["第一站·胃", "ECOPSWOE"]}],
                     "items": [{"text": "第一站·胃", "conf": 0.99}, {"text": "ECOPSWOE", "conf": 0.55}, {"text": "字幕", "conf": 0.99}]}}
    sc = code_scene(shot)
    assert sc["particles"] and sc["picture"] == "青色粒子拼成的胶囊"
    assert sc["on_screen_text"] == ["第一站·胃"]  # subtitles and low-confidence OCR are left out
    assert "推近" in sc["move"]
    plan = {"summary": "x", "units": [], "shoot": [], "local": [], "avatar": [],
            "code": [{"id": "段1", "shots": [1], "start": 0, "end": 3, "screen_capture": [],
                      "scenes": [{"shot": 1, "start": 0.0, "end": 3.0, **sc, "colours": ["青"]}]}]}
    md = "\n".join(report_md(plan))
    assert "Three.js" in md and "| #1 | 0.0–3.0s | 粒子/点云 | 青色粒子拼成的胶囊 |" in md


def _halo(img, colour=(140, 120, 40), radius=150):
    """Lay a large soft glow behind the picture, as particle explainers often do."""
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    g = np.exp(-((xx - 240) ** 2 + (yy - 135) ** 2) / (2 * (radius / 2) ** 2))
    glow = (g[..., None] * np.array(colour, np.float32)).astype(np.float32)
    return np.clip(img.astype(np.float32) + glow, 0, 255).astype(np.uint8)


def test_particles_on_a_soft_halo_still_read_as_particles():
    f = _feat(_halo(_particles()))
    assert f["lit_smooth"] > 0.3  # the halo hides the dots from the plain lit-pixel measure
    assert f["spark_smooth"] < 0.24 and f["spark_peaks"] > 8
    probs, ev, facts = deterministic(f)
    assert facts["fine_dark"] > 0.5 and max(probs, key=probs.get) == "code_render"
    assert any("柔光" in e for e in ev)
    _, _, facts_s = deterministic(_feat(_halo(_shaded())))  # a shaded ball on a glow stays a shaded surface
    assert facts_s["fine_dark"] < 0.1


def test_measure_and_points_follow_the_dots():
    from rea_video.particles import measure, sample_points

    img = _halo(_particles())
    m = measure(img)
    assert m["ground"] in ("#000000", "#000101") and m["halo"]["radius"] > 0.05
    assert abs(m["centre"][0] - 0.5) < 0.05 and abs(m["centre"][1] - 0.5) < 0.05
    assert m["box"][0] > 0.25 and m["box"][2] < 0.75  # the ellipse spans x 150-330 of 480
    pts = sample_points(img, 500)
    assert len(pts) == 500
    xs = np.array([p[0] for p in pts])
    assert xs.min() > 0.25 and xs.max() < 0.75
    # text boxes are blanked
    assert not sample_points(img, 50, text_boxes=[[0.0, 0.0, 1.0, 1.0]])


def test_split_scenes_finds_a_regroup_without_a_cut():
    from rea_video.particles import density, spark_mask, split_scenes

    left, right = np.zeros((270, 480, 3), np.uint8), np.zeros((270, 480, 3), np.uint8)
    rng = np.random.default_rng(1)
    for _ in range(800):
        cv2.circle(left, (int(rng.uniform(40, 200)), int(rng.uniform(60, 210))), 1, (255, 255, 255), -1)
        cv2.circle(right, (int(rng.uniform(280, 440)), int(rng.uniform(60, 210))), 1, (255, 255, 255), -1)
    frames = [left] * 20 + [right] * 20
    times = np.arange(40) * 0.25
    descs = np.array([density(spark_mask(f)).ravel() for f in frames])
    sc = split_scenes(descs, times, 0.0, 10.0)
    assert len(sc) == 2 and abs(sc[0][1] - 5.0) <= 0.25
    assert split_scenes(descs[:20], times[:20], 0.0, 5.0) == [(0.0, 5.0)]


def test_compare_scores_a_good_remake_above_a_bad_one(tmp_path):
    from rea_video.particles import compare

    def write(path, frames):
        vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 4, (480, 270))
        for f in frames:
            vw.write(f)
        vw.release()

    ref = _halo(_particles())
    good = 255 - cv2.GaussianBlur(_particles(1), (3, 3), 0) // 2  # same shape, dark dots on a light ground
    bad = np.full((270, 480, 3), 230, np.uint8)
    cv2.circle(bad, (420, 60), 30, (40, 40, 40), -1)
    write(tmp_path / "ref.mp4", [ref] * 12)
    write(tmp_path / "good.mp4", [good] * 12)
    write(tmp_path / "bad.mp4", [bad] * 12)
    g = compare(str(tmp_path / "ref.mp4"), str(tmp_path / "good.mp4"), out=tmp_path / "cmp")
    b = compare(str(tmp_path / "ref.mp4"), str(tmp_path / "bad.mp4"))
    assert g["inverted"] and g["score"] > 0.6 > b["score"]
    assert (tmp_path / "cmp" / "compare_worst.jpg").exists() and (tmp_path / "cmp" / "compare.json").exists()


def test_report_lists_particle_scenes():
    from rea_video.production import particle_scenes_md

    md = "\n".join(particle_scenes_md([{"id": "scene_01", "shot": 1, "start": 0.0, "end": 5.2, "points": "frames/points/scene_01.json",
                                        "measure": {"halo": {"colour": "#507c87", "centre": [0.5, 0.52], "radius": 0.15},
                                                    "colours": [{"hex": "#4e747c"}], "dots": 286, "box": [0.4, 0.03, 0.6, 0.78]}}]))
    assert "| scene_01 | #1 | 0.0–5.2s | #507c87" in md and "rea-video compare" in md and "frames/points/scene_XX.json" in md
    assert particle_scenes_md([]) == []


def _video(path, frames, fps=4):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frames[0].shape[1], frames[0].shape[0]))
    for f in frames:
        vw.write(f)
    vw.release()
    return path


def _two_shapes():
    rng = np.random.default_rng(1)
    left, right = np.zeros((270, 480, 3), np.uint8), np.zeros((270, 480, 3), np.uint8)
    for _ in range(800):
        cv2.circle(left, (int(rng.uniform(40, 200)), int(rng.uniform(60, 210))), 1, (255, 255, 255), -1)
        cv2.circle(right, (int(rng.uniform(280, 440)), int(rng.uniform(60, 210))), 1, (255, 255, 255), -1)
    return left, right


def test_halo_layer_only_on_dark_pictures_and_needs_a_halo():
    bright = np.full((270, 480, 3), 200, np.uint8)
    f = spatial_features(bright)
    assert f["glow_ratio"] == 0.0 and f["spark_ratio"] == 0.0 and f["spark_smooth"] == 1.0
    # big soft lights on a glow (night street, bokeh) are not fine dots
    img = np.zeros((270, 480, 3), np.uint8)
    for x, y in [(100, 80), (220, 150), (330, 100), (400, 200)]:
        cv2.circle(img, (x, y), 14, (200, 210, 230), -1)
    img = _halo(cv2.GaussianBlur(img, (0, 0), 3))
    _, _, facts = deterministic(_feat(img))
    assert facts["fine_dark"] < 0.5


def test_scene_frames_clears_old_files_and_skips_without_particles(tmp_path):
    from rea_video.particles import scene_frames

    left, right = _two_shapes()
    video = _video(tmp_path / "p.mp4", [left] * 20 + [right] * 20)
    b = {"source": {"path": str(video)}, "shots": [{"index": 1, "start": 0.0, "end": 10.0, "deterministic": {"facts": {"fine_dark": 0.9}}}]}
    out = tmp_path / "out"
    stale = out / "frames" / "points" / "scene_09.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    (out / "frames" / "scene_09_mid.jpg").write_bytes(b"x")
    res = scene_frames(out, breakdown=b)
    assert [s["id"] for s in res["scenes"]] == ["scene_01", "scene_02"]
    assert not stale.exists() and not (out / "frames" / "scene_09_mid.jpg").exists()
    sc = res["scenes"][0]
    assert sc["measure"]["box"][2] < 0.5 and sc["track"] and (out / sc["points"]).exists()
    b["shots"][0]["deterministic"]["facts"]["fine_dark"] = 0.0  # relabelled: nothing left to write
    assert scene_frames(out, breakdown=b)["scenes"] == []
    assert not (out / "frames").exists()


def test_particle_step_failure_keeps_the_breakdown(tmp_path, monkeypatch):
    import rea_video.particles as particles
    from rea_video.pipeline import decompose

    def boom(*a, **k):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(particles, "scene_frames", boom)
    video = _video(tmp_path / "dots.mp4", [_particles(i % 3) for i in range(24)], fps=8)
    out = tmp_path / "o"
    b = decompose(video, out, use_vlm=False, ocr=False, stems=False, asr=False, speakers=False)
    assert any(((s.get("deterministic") or {}).get("facts") or {}).get("fine_dark", 0) > 0.5 for s in b["shots"])
    assert "particle_scenes" not in b
    assert (out / "report.html").exists() and (out / "breakdown.json").exists()


def test_particle_scenes_follow_the_shot_labels(tmp_path):
    from rea_video.memory import correct
    from rea_video.pipeline import decompose, finalize

    video = _video(tmp_path / "dots.mp4", [_particles(i % 3) for i in range(24)], fps=8)
    out = tmp_path / "o"
    b = decompose(video, out, use_vlm=False, ocr=False, stems=False, asr=False, speakers=False)
    assert b.get("particle_scenes", {}).get("count", 0) >= 1 and (out / "frames" / "scenes.json").exists()
    assert b["production_plan"].get("particle_scenes")
    assert "粒子场景" in (out / "video" / "remake.md").read_text(encoding="utf-8")
    correct(b, label="cg_3d", shots="1", record=False)  # the user says it is a 3D render after all
    finalize(b, out)
    assert not b["production_plan"].get("particle_scenes")
