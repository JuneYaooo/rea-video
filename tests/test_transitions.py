"""Transitions: what kind, which way, how long; and the cases that must stay one shot."""
import cv2
import numpy as np

from rea_video import transitions
from rea_video.media import video_info
from rea_video.report import transition_text
from rea_video.shots import build_track, detect_shots
from rea_video.videomd import _transition_in
from tests.conftest import _photo_like, _write

W, H, FPS = 360, 640, 30


def _drift(img: np.ndarray, t: int) -> np.ndarray:
    return np.roll(img, t // 3, axis=1)  # slow camera drift


def _two(seed: int) -> tuple[np.ndarray, np.ndarray]:
    a = _photo_like(W, H, seed)
    b = np.clip(_photo_like(W, H, seed + 1).astype(np.int16) + 45, 0, 255).astype(np.uint8)  # another shot, another tone
    return a, b


def _clip(a: np.ndarray, b: np.ndarray, middle: list[np.ndarray], hold: int = 60) -> list[np.ndarray]:
    """a drifting up to where the transition frames pick it up, the transition, b drifting on."""
    return [_drift(a, t - hold) for t in range(hold)] + middle + [_drift(b, t) for t in range(hold)]


def _shots(frames, tmp_path, name: str):
    p = str(_write(frames, tmp_path / f"{name}.mp4", FPS))
    return detect_shots(build_track(p, video_info(p)))


def test_push_slide_has_kind_direction_and_length(tmp_path):
    a, b = _two(41)
    mid = []
    for k in range(1, 13):  # 0.4 s: both pictures travel left, the new one coming in from the right
        d = int(W * k / 13)
        mid.append(np.concatenate([a[:, d:], b[:, :d]], axis=1))
    shots = _shots(_clip(a, b, mid), tmp_path, "push")
    assert len(shots) == 2
    tr = shots[1].to_dict()["transition"]
    assert tr["type"] == "slide" and tr["mode"] == "push" and tr["direction"] == "left"
    assert 0.25 <= tr["duration"] <= 0.6 and 1.9 <= tr["start"] <= 2.1
    assert "推移" in transition_text(tr) and "向左" in transition_text(tr)
    assert _transition_in(shots[1].to_dict())["type"] == "slide"


def test_iris_wipe_opens_from_the_centre(tmp_path):
    a, b = _two(43)
    yy, xx = np.mgrid[0:H, 0:W]
    rad = np.hypot(xx - W / 2, yy - H / 2)
    mid = [np.where((rad < rad.max() * k / 16)[..., None], b, a) for k in range(1, 16)]
    shots = _shots(_clip(a, b, mid), tmp_path, "iris")
    assert len(shots) == 2 and shots[1].transition_in == "wipe"
    assert shots[1].transition.get("direction") == "center_out"


def test_fade_through_black_is_one_transition(tmp_path):
    a, b = _two(45)
    black = np.zeros_like(a)
    mid = [cv2.addWeighted(a, 1 - k / 8, black, k / 8, 0) for k in range(1, 8)] + [black] * 5 \
        + [cv2.addWeighted(b, k / 8, black, 1 - k / 8, 0) for k in range(1, 8)]
    shots = _shots(_clip(a, b, mid), tmp_path, "fade")
    assert len(shots) == 2 and shots[1].transition_in == "fade" and shots[1].transition["via"] == "black"
    assert shots[1].to_dict()["transition"]["duration"] >= 0.4


def test_whip_pan_hides_the_cut(tmp_path):
    a, b = _two(47)
    mid = []
    for k in range(12):  # the old shot streaks off to the left, the new one streaks in and settles
        u = (k + 0.5) / 12
        src, pos = (a, u * u * 4 * W * 0.6) if u < 0.5 else (b, -(1 - u) ** 2 * 4 * W * 0.6)
        f = np.roll(src, -int(pos), axis=1)
        n = max(3, int(60 * np.sin(np.pi * u)))
        mid.append(cv2.blur(f, (n, 1)))
    shots = _shots(_clip(a, b, mid), tmp_path, "whip")
    assert len(shots) == 2 and shots[1].transition_in == "whip"


def test_dissolve_inside_a_letterboxed_picture(tmp_path):
    a, b = _two(49)
    bar = int(H * 0.32)

    def boxed(f: np.ndarray) -> np.ndarray:
        g = f.copy()
        g[:bar] = 0
        g[H - bar:] = 0
        return g

    mid = [cv2.addWeighted(a, 1 - k / 16, b, k / 16, 0) for k in range(1, 16)]
    frames = [boxed(f) for f in _clip(a, b, mid)]
    p = str(_write(frames, tmp_path / "boxed.mp4", FPS))
    track = build_track(p, video_info(p))
    y0, y1, _, _ = transitions.crop_box(track.thumbs)
    h = track.thumbs[0].shape[0]
    assert 0.25 * h < y0 < 0.4 * h and 0.6 * h < y1 < 0.75 * h  # the bars are left out
    shots = detect_shots(track)
    assert len(shots) == 2 and shots[1].transition_in == "dissolve"
    assert 0.3 <= shots[1].to_dict()["transition"]["duration"] <= 0.7


def test_plain_cut_carries_no_transition_details(tmp_path):
    a, b = _two(51)
    shots = _shots(_clip(a, b, []), tmp_path, "cut")
    assert len(shots) == 2 and shots[1].transition_in == "cut" and "transition" not in shots[1].to_dict()
    assert _transition_in(shots[1].to_dict()) == {}


def test_light_change_and_a_hold_pan_hold_stay_one_shot(tmp_path):
    a = _photo_like(W * 2, H, 53)
    # the lamp comes up over half a second: same scene, brighter
    lit = [np.clip(a[:, :W].astype(np.float32) * (1 + 0.6 * min(1.0, max(0.0, (t - 50) / 15))), 0, 255).astype(np.uint8)
           for t in range(120)]
    assert len(_shots(lit, tmp_path, "lamp")) == 1
    # hold, a slow pan across the same wide picture, hold: movement, not a new shot
    pan = [a[:, :W]] * 40 + [a[:, 4 * t:4 * t + W] for t in range(1, 40)] + [a[:, 160:160 + W]] * 40
    assert len(_shots(pan, tmp_path, "pan")) == 1


def test_edge_composition_directions():
    a = np.zeros((8, 10), np.float32)
    b = np.ones((8, 10), np.float32)
    left = transitions._compose(a, b, "wipe", "left", 3)   # the edge travels left: the new picture grows from the right
    assert left[:, :7].sum() == 0 and left[:, 7:].all()
    down = transitions._compose(a, b, "wipe", "down", 2)   # the edge travels down: the new picture grows from the top
    assert down[:2].all() and down[2:].sum() == 0
    ramp = np.tile(np.arange(10, dtype=np.float32), (8, 1))
    push = transitions._compose(ramp, ramp + 100, "push", "left", 4)
    assert push[0].tolist() == [4, 5, 6, 7, 8, 9, 100, 101, 102, 103]


def test_push_in_on_a_page_stays_one_shot(tmp_path):
    page = np.full((H * 3, W * 3, 3), 245, np.uint8)
    rng = np.random.default_rng(5)
    for _ in range(140):  # a page of blocks and lines
        x, y = int(rng.integers(0, W * 3 - 120)), int(rng.integers(0, H * 3 - 40))
        cv2.rectangle(page, (x, y), (x + int(rng.integers(30, 120)), y + int(rng.integers(8, 40))),
                      tuple(int(c) for c in rng.integers(30, 220, 3)), -1)

    def view(scale: float) -> np.ndarray:
        w, h = int(W * 3 / scale), int(H * 3 / scale)
        x0, y0 = (W * 3 - w) // 2, (H * 3 - h) // 2
        return cv2.resize(page[y0:y0 + h, x0:x0 + w], (W, H), interpolation=cv2.INTER_AREA)

    frames = [view(1.0)] * 45 + [view(1.0 + 1.6 * k / 18) for k in range(1, 18)] + [view(2.6)] * 45
    assert len(_shots(frames, tmp_path, "pushin")) == 1


def test_still_background_is_not_a_border():
    rng = np.random.default_rng(7)
    back = cv2.resize(rng.integers(0, 255, (20, 12)).astype(np.uint8), (96, 170), interpolation=cv2.INTER_CUBIC)
    thumbs = []
    for t in range(60):  # one shot: only a small figure moves in front of a still, detailed background
        f = back.copy()
        cv2.circle(f, (40 + t // 4, 80), 12, 255, -1)
        thumbs.append(f)
    assert transitions.crop_box(thumbs) == (0, 170, 0, 96)
    boxed = [np.pad(f[40:130], ((40, 40), (0, 0))) for f in thumbs]  # the same picture between plain black bars
    y0, y1, _, _ = transitions.crop_box(boxed)
    assert (y0, y1) == (40, 130)


def test_a_labelled_cut_inside_a_transition_counts_as_found():
    from rea_video.evaluate import boundary_f1

    # the detector puts a half-second wipe at 10.0 (9.8-10.3); the labeller marked 10.25
    assert boundary_f1([10.0], [10.25])["tp"] == 0
    assert boundary_f1([10.0], [10.25], spans=[(9.8, 10.3)])["tp"] == 1
    assert boundary_f1([10.0, 12.0], [10.25, 12.05], spans=[(9.8, 10.3), None]) | {} == {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 2, "fp": 0, "fn": 0}
