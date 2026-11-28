"""Draw a special moment out for a viewer who missed it: a numbered frame diagram and a reveal clip.

The diagram is the steps the reader wrote, one frame each, zoomed on the place to look, with a red ring where the
reader was sure; then the change itself frame by frame (every frame of the stretch the reader marked, zoomed, so the
object is seen travelling rather than popping up); under it what the frames show, what is only a guess, and why
viewers miss it. The clip plays the moment at speed, that stretch again slowed down and zoomed in with the steps as
captions, holds the key frame, then the reaction.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .visual import _font

RED = (235, 40, 40)
INK = (25, 25, 25)
GUESS = (160, 70, 20)
SLOW = (3, 10)      # the slow look plays at 1/n speed, n chosen so it lasts about SLOW_LEN seconds
SLOW_LEN = 6.0
SLOW_BEFORE, SLOW_AFTER = 1.0, 0.6   # seconds of source around the key step in the slow look, without a marked stretch
SEQ_MAX, SEQ_COLS = 18, 6            # frames in the frame-by-frame row
SEQ_DEFAULT = (0.4, 0.1)             # stretch around the key step when the reader marked none
SEQ_CONTEXT = (0.25, 0.5)            # frames added before and after the stretch in the frame-by-frame row (s away)
HOLD = 2.5          # seconds the key frame is held
CLIP_W = 720


ASPECT = (0.6, 1.8)  # the zoom keeps the reader's box shape within these width / height ratios


def zoom_box(focus: list[float] | None, pts: list[tuple[float, float]], w: int, h: int) -> tuple[int, int, int, int] | None:
    """The region to zoom on, in pixels (x, y, w, h): the reader's focus box (its own shape, within ASPECT), else
    around the marked points; None when there is neither or it is about the whole frame."""
    if focus:
        x0, y0, x1, y1 = focus
    elif pts:
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        x0, y0, x1, y1 = cx - .25, cy - .25, cx + .25, cy + .25
    else:
        return None
    for x, y in pts if not focus else []:  # without a box, every marked point stays inside, with a margin
        x0, y0, x1, y1 = min(x0, x - .08), min(y0, y - .08), max(x1, x + .08), max(y1, y + .08)
    side = 0.25 * min(w, h)
    bw, bh = max((x1 - x0) * w, side), max((y1 - y0) * h, side)
    if bw / bh > ASPECT[1]:
        bh = bw / ASPECT[1]
    elif bw / bh < ASPECT[0]:
        bw = bh * ASPECT[0]
    bw, bh = min(bw, w), min(bh, h)
    cx, cy = (x0 + x1) / 2 * w, (y0 + y1) / 2 * h
    x = int(min(max(0, cx - bw / 2), w - bw))
    y = int(min(max(0, cy - bh / 2), h - bh))
    bw, bh = int(bw) // 2 * 2, int(bh) // 2 * 2
    if bw * bh >= 0.85 * w * h:
        return None
    return x, y, bw, bh


def _grab(video: str, t: float, tmp: Path, k: int) -> Image.Image | None:
    p = tmp / f"f{k}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t, 0):.3f}", "-i", video, "-frames:v", "1", str(p)], capture_output=True)
    return Image.open(p).convert("RGB") if p.is_file() else None


def _ring(d: ImageDraw.ImageDraw, c: tuple[float, float], r: float, w: int) -> None:
    d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=RED, width=w)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    out, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) > width and cur:
            out.append(cur)
            cur = ""
        cur += ch
    return out + ([cur] if cur else [])


def _panel(im: Image.Image, box, at, pw: int, zoom: bool) -> Image.Image:
    """One step's frame: zoomed on the box (or whole), ring where the reader marked."""
    w, h = im.size
    if zoom and box:
        x, y, bw, bh = box
        im = im.crop((x, y, x + bw, y + bh))
        to = lambda p: ((p[0] * w - x) / bw, (p[1] * h - y) / bh)  # noqa: E731
    else:
        to = lambda p: p  # noqa: E731
    ph = int(pw * im.height / im.width)
    im = im.resize((pw, ph), Image.LANCZOS)
    if at:
        cx, cy = to(at)
        _ring(ImageDraw.Draw(im), (cx * pw, cy * ph), pw * (0.09 if zoom and box else 0.06), max(3, pw // 100))
    return im


def seq_times(f0: float, f1: float, fps: float, key: float | None = None, n: int = SEQ_MAX) -> list[float]:
    """Every frame from f0 to f1, or every k-th when there are more than n, always with the key frame."""
    dt = 1.0 / max(fps, 1.0)
    allf = [f0 + i * dt for i in range(int(round((f1 - f0) / dt)) + 1)]
    k = max(1, -(-len(allf) // n))
    ts = allf[::k]
    if key is not None and f0 <= key <= f1 and all(abs(t - key) > dt / 2 for t in ts):
        ts = sorted(ts + [key])
        if len(ts) > n:
            ts.remove(min((t for t in ts if t != key), key=lambda t: abs(t - key)))
    return [round(t, 3) for t in ts]


def diagram(video: str, steps: list[dict], box, title: str, sub: str, notes: list[tuple[str, str]], out: Path,
            seq: list[float] | None = None, seq_title: str = "", key: float | None = None, pw: int = 480, cols: int = 3,
            seq_labels: tuple[str, str] = ("前 ", "后 ")) -> None:
    """Numbered frames of the steps, zoomed, ringed, captioned; then `seq` frame by frame (the key one in red);
    notes = [(kind, text)], kind seen / guess / why."""
    cols = min(cols, max(1, len(steps)))
    W = cols * pw + (cols + 1) * 12
    sw = (W - (SEQ_COLS + 1) * 8) // SEQ_COLS
    with tempfile.TemporaryDirectory() as td:
        ims, seq_ims = [], []
        for k, s in enumerate(steps):
            im = _grab(video, s["t"], Path(td), k)
            if im is None:
                continue
            ims.append((s, _panel(im, box, s.get("at"), pw, box is not None and not s.get("whole"))))
        ctx = [round(seq[0] - d, 3) for d in SEQ_CONTEXT[::-1] if seq and seq[0] - d >= 0] + list(seq or []) \
            + [round(seq[-1] + d, 3) for d in SEQ_CONTEXT if seq]
        for k, t in enumerate(ctx):
            im = _grab(video, t, Path(td), 100 + k)
            if im is not None:
                pim = _panel(im, box, None, sw, box is not None)
                if seq and not (seq[0] - 1e-3 <= t <= seq[-1] + 1e-3):
                    pim = Image.blend(pim, Image.new("RGB", pim.size, (250, 248, 244)), 0.35)
                seq_ims.append((t, pim))
    if not ims:
        return
    zoomed = [im.height for s, im in ims if not s.get("whole")] or [im.height for _, im in ims]
    ph = max(zoomed)
    fit = []
    for s, im in ims:  # a whole-frame panel (often a tall portrait) fits the zoomed panels' height, centred
        if im.height > ph:
            im = im.resize((max(1, int(im.width * ph / im.height)), ph), Image.LANCZOS)
            pad_im = Image.new("RGB", (pw, ph), (250, 248, 244))
            pad_im.paste(im, ((pw - im.width) // 2, 0))
            im = pad_im
        fit.append((s, im))
    ims = fit
    rows = (len(ims) + cols - 1) // cols
    pad, cap_h = 12, 64
    sh = max((im.height for _, im in seq_ims), default=0)
    srows = (len(seq_ims) + SEQ_COLS - 1) // SEQ_COLS
    seq_h = (44 + srows * (sh + 30)) if seq_ims else 0
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f_title = _font(30)
    title_lines = _wrap(probe, title, f_title, W - 2 * pad - 8)[:2]
    head_h = 20 + 40 * len(title_lines) + 34
    f_note = _font(22)
    note_lines = []
    for kind, text in notes:
        for ln in _wrap(probe, text, f_note, W - 2 * pad - 8):
            note_lines.append((kind, ln))
    foot_h = 24 + 34 * len(note_lines)
    sheet = Image.new("RGB", (W, head_h + rows * (ph + cap_h + pad) + seq_h + foot_h), (250, 248, 244))
    d = ImageDraw.Draw(sheet)
    for j, ln in enumerate(title_lines):
        d.text((pad + 4, 14 + 40 * j), ln, fill=INK, font=f_title)
    d.text((pad + 4, head_h - 34), sub, fill=(115, 115, 115), font=_font(18))
    f_cap, f_num, f_t = _font(22), _font(26), _font(20)
    for k, (s, im) in enumerate(ims):
        r, c = divmod(k, cols)
        x, y = pad + c * (pw + pad), head_h + r * (ph + cap_h + pad)
        sheet.paste(im, (x, y))
        d.ellipse([x + 8, y + 8, x + 50, y + 50], fill=RED)
        d.text((x + 29, y + 29), str(k + 1), fill="white", font=f_num, anchor="mm")
        lbl = (f"{s['t']:.1f}" if abs(s["t"] - round(s["t"], 1)) < 1e-6 else f"{s['t']:.2f}") + "s"
        d.rectangle([x + 54, y + 14, x + 66 + int(d.textlength(lbl, font=f_t)), y + 44], fill=(0, 0, 0))
        d.text((x + 60, y + 17), lbl, fill="white", font=f_t)
        for j, ln in enumerate(_wrap(d, s["text"], f_cap, pw - 8)[:2]):
            d.text((x + 4, y + ph + 6 + j * 28), ln, fill=RED if s.get("key") else INK, font=f_cap)
    if seq_ims:
        y0 = head_h + rows * (ph + cap_h + pad)
        d.text((pad + 4, y0 + 6), seq_title, fill=INK, font=_font(24))
        f_s = _font(16)
        for k, (t, im) in enumerate(seq_ims):
            r, c = divmod(k, SEQ_COLS)
            x, y = 8 + c * (sw + 8), y0 + 44 + r * (sh + 30)
            sheet.paste(im, (x, y))
            hit = key is not None and k == min(range(len(seq_ims)), key=lambda j: abs(seq_ims[j][0] - key))
            if hit:
                d.rectangle([x - 4, y - 4, x + sw + 3, y + sh + 3], outline=RED, width=5)
            side = "" if not seq or seq[0] - 1e-3 <= t <= seq[-1] + 1e-3 else (seq_labels[0] if t < seq[0] else seq_labels[1])
            if side:  # context outside the change: dimmed
                d.rectangle([x, y, x + sw - 1, y + sh - 1], fill=None, outline=(170, 170, 170), width=2)
            d.text((x + sw // 2, y + sh + 14), f"{side}{t:.2f}s", fill=RED if hit else ((140, 140, 140) if side else INK), font=f_s, anchor="mm")
    y = sheet.height - foot_h + 12
    for kind, ln in note_lines:
        d.text((pad + 4, y), ln, fill=GUESS if kind == "guess" else INK, font=f_note)
        y += 34
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out, quality=90)


def _card(path: Path, w: int, h: int, label: str = "", lines: list[str] | None = None, ring: tuple[float, float, float] | None = None) -> Path:
    """A transparent overlay: a red label top left, captions on a dark band, a ring (x, y, r in pixels)."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = max(18, w // 22)
    if label:
        f = _font(int(s * .7))
        tw = int(d.textlength(label, font=f))
        d.rounded_rectangle([12, 12, 12 + tw + 24, 12 + int(s * .7) + 18], 8, fill=RED + (235,))
        d.text((24, 12 + (int(s * .7) + 18) // 2), label, fill="white", font=f, anchor="lm")
    if lines:
        f = _font(s)
        wrapped = [x for ln in lines for x in _wrap(d, ln, f, w - 40)][:3]
        top = int(s * .7) + 44
        d.rectangle([0, top, w, top + (s + 12) * len(wrapped) + 12], fill=(0, 0, 0, 170))
        for j, ln in enumerate(wrapped):
            d.text((w // 2, top + 8 + j * (s + 12) + s // 2 + 2), ln, fill="white", font=f, anchor="mm")
    if ring:
        _ring(d, ring[:2], ring[2], max(4, w // 120))
    im.save(path)
    return path


def reveal_clip(video: str, has_audio: bool, size: tuple[int, int], dur: float, span: tuple[float, float],
                steps: list[dict], box, guess: str, out: Path, labels: dict[str, str],
                window: tuple[float, float] | None = None) -> Path | None:
    """At speed -> the change (`window`, else around the key step) slowed and zoomed with the steps as captions ->
    the key frame held -> the reaction. None without a key step."""
    key = next((s for s in steps if s.get("key")), None)
    if key is None:
        return None
    sw, sh = size
    W = min(CLIP_W, sw) // 2 * 2
    H = int(W * sh / sw) // 2 * 2
    kt = float(key["t"])
    norm = f"scale={W}:{H},setsar=1,fps=30,format=yuv420p"
    zoom = (f"crop={box[2]}:{box[3]}:{box[0]}:{box[1]},scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2," if box else "")

    def ring_px(at):
        if not at:
            return None
        x, y = at[0] * sw, at[1] * sh
        if not box:
            return (x * W / sw, y * H / sh, W * 0.06)
        k = min(W / box[2], H / box[3])
        ox, oy = (W - box[2] * k) / 2, (H - box[3] * k) / 2
        return (ox + (x - box[0]) * k, oy + (y - box[1]) * k, box[2] * k * 0.09)

    def ff(args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)

    a_out = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
    with tempfile.TemporaryDirectory() as td:
        T = Path(td)
        segs = []

        def speed(name, t0, t1, label):
            if t1 - t0 < 0.3:
                return
            card = _card(T / f"{name}.png", W, H, label)
            src = ["-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", video, "-i", str(card)]
            if has_audio:
                ff([*src, "-filter_complex", f"[0:v]{norm}[v];[v][1:v]overlay[o]", "-map", "[o]", "-map", "0:a", *a_out, str(T / f"{name}.mp4")])
            else:
                ff([*src, "-f", "lavfi", "-t", f"{t1 - t0:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
                    "-filter_complex", f"[0:v]{norm}[v];[v][1:v]overlay[o]", "-map", "[o]", "-map", "2:a", "-shortest", *a_out, str(T / f"{name}.mp4")])
            segs.append(T / f"{name}.mp4")

        # 1. at speed: the whole moment, at most 12 s around the key step
        a = max(span[0], kt - 6.0)
        speed("a", a, min(span[1], a + 12.0, dur), labels["speed"])

        # 2. slow and zoomed: each step's caption from its time on, the ring with the step that marked it
        if window:
            s0, s1 = max(0.0, window[0] - 0.3), min(dur, max(window[1], kt) + 0.3)
        else:
            s0, s1 = max(0.0, kt - SLOW_BEFORE), min(dur, kt + SLOW_AFTER)
        slow = float(min(SLOW[1], max(SLOW[0], round(SLOW_LEN / max(s1 - s0, 0.1)))))
        slow_lbl = labels["slow"].format(n=int(slow))
        inside = [s for s in steps if s0 - 1.0 <= s["t"] <= s1]
        cards, cuts = [], []
        for j, s in enumerate(inside):
            st = max(0.0, (s["t"] - s0) * slow)
            en = (inside[j + 1]["t"] - s0) * slow if j + 1 < len(inside) else (s1 - s0) * slow
            if en > st:
                cards.append(_card(T / f"b{j}.png", W, H, slow_lbl, [s["text"]]))
                cuts.append((st, en))
            if ring_px(s.get("at")) and s0 <= s["t"] <= s1:  # the ring only around the frame it was placed on
                cards.append(_card(T / f"r{j}.png", W, H, ring=ring_px(s.get("at"))))
                cuts.append((max(0.0, (s["t"] - 0.04 - s0) * slow), min((s1 - s0) * slow, (min(s["t"] + 0.2, inside[j + 1]["t"] if j + 1 < len(inside) else 1e9) - s0) * slow)))
        lead = _card(T / "b_lead.png", W, H, slow_lbl)
        L = (s1 - s0) * slow
        inputs = ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", video, "-i", str(lead)]
        chain = f"[0:v]{zoom}minterpolate=fps=60:mi_mode=blend,setpts={slow}*PTS,{norm}[v0];[v0][1:v]overlay[v1]"
        for j, (c, (st, en)) in enumerate(zip(cards, cuts)):
            inputs += ["-i", str(c)]
            chain += f";[v{j + 1}][{j + 2}:v]overlay=enable='between(t,{st:.3f},{en:.3f})'[v{j + 2}]"
        n = len(cards) + 2
        ff([*inputs, "-f", "lavfi", "-t", f"{L:.3f}", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", chain,
            "-map", f"[v{len(cards) + 1}]", "-map", f"{n}:a", "-t", f"{L:.3f}", *a_out, str(T / "b.mp4")])
        segs.append(T / "b.mp4")

        # 3. the key frame held, with the key step and the guess
        ff(["-ss", f"{kt:.3f}", "-i", video, "-frames:v", "1", str(T / "k.png")])
        hold_lines = [key["text"], *([guess] if guess else [])]
        card = _card(T / "c.png", W, H, labels["hold"].format(t=kt), hold_lines, ring_px(key.get("at")))
        ff(["-loop", "1", "-t", f"{HOLD}", "-i", str(T / "k.png"), "-i", str(card), "-f", "lavfi", "-t", f"{HOLD}", "-i", "anullsrc=r=44100:cl=stereo",
            "-filter_complex", f"[0:v]{zoom}{norm}[v];[v][1:v]overlay[o]", "-map", "[o]", "-map", "2:a", "-t", f"{HOLD}", *a_out, str(T / "c.mp4")])
        segs.append(T / "c.mp4")

        # 4. the reaction at speed
        after = [s["t"] for s in steps if s["t"] > kt + 0.3]
        r0 = max(kt + 0.3, (after[-1] - 0.5) if after else kt + 0.6)
        speed("d", r0, min(dur, r0 + 2.0), labels["react"])

        ins, flt = [], ""
        for j, p in enumerate(segs):
            ins += ["-i", str(p)]
            flt += f"[{j}:v][{j}:a]"
        out.parent.mkdir(parents=True, exist_ok=True)
        ff([*ins, "-filter_complex", f"{flt}concat=n={len(segs)}:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)])
    return out


SLOW_FRAME = 0.2     # seconds each frame of the change stays on screen in the slow cut (5 frames a second: each one seen)
CONTEXT_FRAME = 0.1  # seconds each frame around the change stays on screen (a third of normal speed at 30 fps)
SLOW_PRE, SLOW_POST = 1.0, 1.0  # source seconds shown before the change (the approach) and after it (the result shown)
HOLD_KEY = 1.5       # seconds the key frame is held in the slow cut


def slow_clip(video: str, size: tuple[int, int], dur: float, fps: float, window: tuple[float, float], key: float | None,
              box, at, out: Path, labels: dict[str, str]) -> Path | None:
    """The change alone, every frame shown long enough to see: zoomed, each frame's time on it, the key frame ringed
    and held. Frames are repeated, not blended, so nothing smears."""
    sw, sh = size
    bw0, bh0 = (box[2], box[3]) if box else (sw, sh)  # the canvas takes the zoom's shape, so a wide region fills it
    W = CLIP_W if bw0 >= bh0 else int(CLIP_W * bw0 / bh0) // 2 * 2
    H = int(W * bh0 / bw0) // 2 * 2
    a, z = max(0.0, window[0] - SLOW_PRE), min(dur, max(window[1], key if key is not None else 0.0) + SLOW_POST)
    if z - a < 0.1:
        return None
    each = SLOW_FRAME
    with tempfile.TemporaryDirectory() as td:
        T = Path(td)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{z - a:.3f}", "-i", video,
                        "-fps_mode", "passthrough", str(T / "s_%06d.png")], check=True, capture_output=True)
        frames = sorted(T.glob("s_*.png"))
        if not frames:
            return None
        n = len(frames)
        times = [a + i * (z - a) / max(1, n) for i in range(n)]
        ki = min(range(n), key=lambda i: abs(times[i] - key)) if key is not None else None
        f_t, f_l = _font(max(22, min(W, H) // 18)), _font(max(18, min(W, H) // 26))
        lst = []
        for i, (p, t) in enumerate(zip(frames, times)):
            im = Image.open(p).convert("RGB")
            if box:
                x, y, bw, bh = box
                crop = im.crop((x, y, x + bw, y + bh))
                k = min(W / bw, H / bh)
                crop = crop.resize((max(1, int(bw * k)), max(1, int(bh * k))), Image.LANCZOS)
                frame = Image.new("RGB", (W, H), (0, 0, 0))
                ox, oy = (W - crop.width) // 2, (H - crop.height) // 2
                frame.paste(crop, (ox, oy))
                to = (lambda q: (ox + (q[0] * sw - x) * k, oy + (q[1] * sh - y) * k)) if at else None
                r = bw * k * 0.09
            else:
                frame = im.resize((W, H), Image.LANCZOS)
                to = (lambda q: (q[0] * W, q[1] * H)) if at else None
                r = W * 0.06
            d = ImageDraw.Draw(frame)
            in_window = window[0] - 1e-3 <= t <= window[1] + 1e-3
            zone = "in" if in_window else ("pre" if t < window[0] else "post")
            if i == ki and to:
                _ring(d, to(at), r, max(4, W // 120))
            tag = f"{t:.2f}s"
            tw = int(d.textlength(tag, font=f_t))
            d.rectangle([W - tw - 28, 12, W - 12, 12 + f_t.size + 14], fill=RED if i == ki else (0, 0, 0))
            d.text((W - tw - 20, 18), tag, fill="white", font=f_t)
            lbl = labels["slow"].format(i=i + 1, n=n) if in_window else labels[zone]
            lw = int(d.textlength(lbl, font=f_l))
            d.rounded_rectangle([12, 12, 12 + lw + 24, 12 + f_l.size + 18], 8, fill=RED)
            d.text((24, 21), lbl, fill="white", font=f_l)
            if i == ki and labels.get("key"):
                kw = int(d.textlength(labels["key"], font=f_t))
                d.rectangle([(W - kw) // 2 - 14, H - f_t.size - 40, (W + kw) // 2 + 14, H - 12], fill=(0, 0, 0))
                d.text(((W - kw) // 2, H - f_t.size - 30), labels["key"], fill="white", font=f_t)
            q = T / f"o_{i:06d}.png"
            frame.save(q)
            lst += [f"file '{q}'", f"duration {(each if in_window else CONTEXT_FRAME) + (HOLD_KEY if i == ki else 0):.3f}"]
        lst.append(f"file '{T / f'o_{n - 1:06d}.png'}'")  # the concat demuxer drops the last duration otherwise
        (T / "list.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(T / "list.txt"),
                        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-movflags", "+faststart", str(out)], check=True, capture_output=True)
    return out
