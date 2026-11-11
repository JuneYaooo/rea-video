"""Reel: a video breakdown laid out for models. Read the card, then the map, then open only the file you need.

The output directory is the package. Levels, each cheaper than the next:
  L0  REEL.md front matter   the card: what the video is, how it was made, how sure        ~150 tokens
  L1  REEL.md body           overview, open questions and the map of every file below       ~1k tokens
  L2  reel/<topic>.md        one topic per file; reel/timeline.md is the spine: one line per shot
  L3  reel/shots/07.md       everything about one shot: what is visible, what is inferred and why, remake prompts
  L4  breakdown.json, shots/, stems/, sfx/, packaging/   raw data and media
Every file opens with front matter saying what it covers and roughly how many tokens it holds, so a reader can decide
before opening it. Paths are relative to the package root. In timeline lines a key ending in `~` is the tools'
inference; keys without it are what is visible on screen or measured directly. The spec is docs/reel.md.
"""
from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import yaml

from . import entities, narrative
from .classify import LABEL_ZH
from .i18n import T, join

FORMAT = "reel"
VERSION = 1
ENTRY = "REEL.md"
DIR = "reel"

# timeline keys, in line order; `~` = inferred by the tools
KEYS = ("say", "seen", "cam", "over", "made~", "real~", "remake", "flag")


# ------------------------------------------------------------------ helpers ---------------------------------------

def tokens(text: str) -> int:
    """Rough token count: ~4 ASCII characters per token, ~1.5 tokens per 2 CJK characters."""
    ascii_n = sum(c.isascii() for c in text)
    return int(ascii_n / 4 + (len(text) - ascii_n) * 0.75) + 1


def _one_line(s, limit: int | None = None) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).replace(" | ", " / ").replace("|", "/").strip()
    return s[:limit] + "…" if limit and len(s) > limit else s


def _front(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def _sized(meta: dict, body: str) -> str:
    """Front matter + body, with the body's size in the front matter."""
    return _front({**meta, "tokens": tokens(body)}, body)


_RE_DETAILS = re.compile(r'^<details(?: class="ref")?><summary>(.*)</summary>$')


def _plain(lines: list[str]) -> str:
    """A report section without the HTML folds: a model reads the whole file it opened."""
    out = []
    for ln in lines:
        m = _RE_DETAILS.match(ln.strip())
        if m:
            out.append(f"**{html.unescape(m.group(1))}**")
        elif ln.strip() != "</details>" and not ln.startswith("!["):  # images: paths live in front matter (`frames`) or the map
            out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _shot_name(i: int) -> str:
    return f"{i:02d}"


# ------------------------------------------------------------------ timeline (the spine) --------------------------

def timeline_line(r: dict, roles: dict, units: dict) -> str:
    from .report import CAMERA_ZH, _layers, _origin, _route

    base = r["base"]
    f = {}
    n = roles.get(r["index"]) or {}
    if n.get("role_zh") or n.get("point"):
        f["say"] = _one_line(join(x for x in (n.get("role_zh"), n.get("point")) if x), 48)
    desc = (r.get("vlm") or r.get("review") or {}).get("description")
    if desc:
        f["seen"] = _one_line(desc, 60)
    f["cam"] = CAMERA_ZH.get((r.get("features") or {}).get("camera", "unknown"), "—")
    if _layers(r) != "—":
        f["over"] = _layers(r)
    made = f"{base['label_zh']}({base['label']}) {base['confidence']:.0%}"
    alt = next(((k, v) for k, v in sorted(base["probs"].items(), key=lambda kv: -kv[1]) if k != base["label"] and v > 0), None)
    if alt and base["decided_by"] != "user":
        made += T(" · 次选 {l} {p:.0%}", " · runner-up {l} {p:.0%}", l=LABEL_ZH[alt[0]], p=alt[1])
    f["made~"] = made
    f["real~"] = _one_line(_origin(r), 40)
    f["remake"] = _one_line(_route(r, units), 30)
    flags = []
    if base["decided_by"] == "user":
        flags.append(T("用户纠正", "user correction"))
    elif base["confidence"] < 0.6:
        flags.append(T("低置信", "low confidence"))
    if base.get("uncertain"):
        flags.append(T("待确认", "to confirm"))
    if base.get("disputed"):
        flags.append(T("有分歧", "disputed"))
    if flags:
        f["flag"] = ",".join(flags)
    head = f"#{_shot_name(r['index'])} {r['start']:.1f}-{r['end']:.1f}"
    return " | ".join([head] + [f"{k} {f[k]}" for k in KEYS if f.get(k)])


_RE_HEAD = re.compile(r"^#(\d+) (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$")


def parse_timeline_line(line: str) -> dict | None:
    """`#07 16.2-18.5 | seen … | made~ …` -> {"shot": 7, "start": 16.2, "end": 18.5, "seen": "…", "made~": "…"}; None if not a shot line."""
    parts = line.strip().split(" | ")
    m = _RE_HEAD.match(parts[0])
    if not m:
        return None
    out: dict = {"shot": int(m.group(1)), "start": float(m.group(2)), "end": float(m.group(3))}
    for p in parts[1:]:
        k, _, v = p.partition(" ")
        out[k] = v
    return out


def _legend() -> list[str]:
    return [T("每行一个镜头：`#编号 起-止(秒) | 键 值 | …`。键后带 `~` 的是工具推断，不带的是画面里看得到或直接测得的。",
              "One shot per line: `#<n> start-end (s) | key value | …`. A key ending in `~` is the tools' inference; keys without it are visible on screen or measured directly."),
            T("`say` 在叙事里的作用和讲的点 · `seen` 画面里看到的 · `cam` 运镜 · `over` 叠加层 · `made~` 制作方式（推断）· "
              "`real~` 素材来源（推断）· `remake` 复刻路线 · `flag` 需要复核",
              "`say` job in the story and the point · `seen` what is on screen · `cam` camera move · `over` overlays · `made~` how it was made (inferred) · "
              "`real~` material origin (inferred) · `remake` remake route · `flag` needs a second look"),
            T("某一镜的全部细节在 `reel/shots/编号.md`（如 `reel/shots/07.md`）。", "Full detail for a shot is in `reel/shots/<n>.md` (e.g. `reel/shots/07.md`).")]


# ------------------------------------------------------------------ per-shot files ---------------------------------

def _shot_file(r: dict) -> str:
    from .report import _shot_detail_md

    base = r["base"]
    probs = sorted(base["probs"].items(), key=lambda kv: -kv[1])
    assets = r.get("assets") or {}
    meta = {
        FORMAT: VERSION, "part": "shot", "shot": r["index"], "time": [round(r["start"], 3), round(r["end"], 3)],
        "camera": (r.get("features") or {}).get("camera", "unknown"),
        "overlays": sorted({l["kind"] for l in r.get("layers", [])}),
        "inferred": {"made": base["label"], "p": base["confidence"],
                     "alternatives": dict([(k, v) for k, v in probs if k != base["label"] and v > 0][:2]),
                     "decided_by": base["decided_by"], "real_material": bool((r.get("material") or {}).get("has_real_material"))},
        "flags": [k for k in ("uncertain", "disputed") if base.get(k)] + (["low_confidence"] if base["confidence"] < 0.6 and base["decided_by"] != "user" else []),
        "frames": {k: v for k, v in (("sheet", assets.get("sheet")), ("first", assets.get("first_frame")), ("last", assets.get("last_frame"))) if v},
    }
    title = T("# 镜头 {i} · {a}–{z}s · {v}", "# Shot {i} · {a}–{z}s · {v}", i=r["index"], a=f"{r['start']:.1f}", z=f"{r['end']:.1f}", v=r.get("verdict", ""))
    return _sized(meta, title + "\n\n" + _plain(_shot_detail_md(r)))


# ------------------------------------------------------------------ topic files ------------------------------------

def _topics(b: dict) -> list[tuple[str, str, str, list[str]]]:
    """(file stem, title, when to read it, report section lines)."""
    from .report import _audio_md, _cast_md, _content_md, _remake_md, _visual_md, packaging_md

    return [
        ("content", T("内容与结构", "Content and structure"), T("要讲什么、叙事线、结构时间轴、台词", "what it says, the narrative line, structure, the script"), _content_md(b)),
        ("cast", T("角色、场景与道具", "Cast, scenes and props"), T("做角色参考图、写首帧提示词", "reference images for characters, first-frame prompts"), _cast_md(b)),
        ("sound", T("声音", "Sound"), T("人声、BGM、音效、节拍和来源", "voice, music, sound effects, beats and sources"), _audio_md(b)),
        ("look", T("拍法、打光与剪辑", "Camera, lighting and editing"), T("有实拍镜头时：景别、机位、布光、器材", "for filmed shots: framing, camera, lighting, kit"), _visual_md(b)),
        ("packaging", T("剪辑包装", "Packaging"), T("字幕、花字、贴纸、画中画的时间和样式", "subtitles, styled text, stickers, picture-in-picture: timing and style"), packaging_md(b)),
        ("remake", T("复刻方案", "Remake plan"), T("生成单元、拍摄场次、代码合成、要准备的真实素材", "generation units, shoots, code builds, real material to collect"), _remake_md(b)),
    ]


def _has_body(text: str) -> bool:
    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.startswith("#")) >= 1


# ------------------------------------------------------------------ entry (L0 + L1) -----------------------------------

def _card(b: dict) -> dict:
    s, src = b["summary"], b["source"]
    readers = ["tools"] + (["vlm"] if b["analysis"]["vlm"].get("used") else []) + (["agent"] if (b["analysis"].get("review") or {}).get("shots") else [])
    if any(r["base"]["decided_by"] == "user" for r in b["shots"]):
        readers.append("user")
    return {
        FORMAT: VERSION, "name": Path(src["filename"]).stem,
        "description": _one_line(s["verdict"].split(T("；", "; "))[0], 120),
        "source": {"file": src["filename"], "duration": src["duration"], "size": f"{src['width']}x{src['height']}", "fps": src["fps"], "aspect": src["aspect_ratio"]},
        "shots": len(b["shots"]), "confidence": s["confidence"],
        "made_mix": {m["label"]: m["ratio"] for m in s["production_mix"]},
        "readers": readers, "open_questions": len(entities.open_questions(b)), "lang": b.get("lang", "zh"),
    }


def _overview(b: dict, files: list[tuple[str, str, str, int]]) -> str:
    s = b["summary"]
    w = b.get("whole_video_vlm") or {}
    L = [f"# {b['source']['filename']}", "", T("**结论**（推断）：{v}", "**Verdict** (inferred): {v}", v=s["verdict"])]
    if w.get("summary"):
        L.append(T("**讲什么**：{s}", "**What it says**: {s}", s=_one_line(w["summary"], 200)))
    steps = narrative.beats(b)
    if steps:
        L.append(T("**叙事线**：", "**Narrative**: ") + " → ".join(
            f"#{st['shots'][0]:02d}" + (f"-{st['shots'][-1]:02d}" if len(st["shots"]) > 1 else "") + f" {st['role_zh'] or _one_line((st['points'] or ['?'])[0], 16)}"
            for st in steps))
    L.append(T("**制作方式**（推断，按时长）：", "**Made with** (inferred, by duration): ") + join(f"{m['label_zh']} {m['ratio']:.0%}" for m in s["production_mix"]))
    if s.get("production"):
        L.append(T("**复刻**：{p}", "**Remake**: {p}", p=s["production"]))
    rm = s.get("real_material") or {}
    if rm.get("shots"):
        L.append(T("**要拿到的真实素材**：{n} 个镜头（{r:.0%} 时长），清单见 `reel/remake.md`", "**Real material to collect**: {n} shots ({r:.0%} of the duration), list in `reel/remake.md`",
                   n=len(rm["shots"]), r=rm["ratio"]))
    qs = entities.open_questions(b)
    L += ["", T("## 不确定点", "## Open questions"), ""] + ([f"- {_one_line(q, 160)}" for q in qs[:8]] or [T("- 没有", "- None")])
    if len(qs) > 8:
        L.append(T("- 另有 {n} 处，见 `reel/timeline.md` 里带 `flag` 的行", "- {n} more, see the `flag` lines in `reel/timeline.md`", n=len(qs) - 8))
    L += ["", T("## 地图", "## Map"), "",
          T("先读本页；要细节时按下表只打开需要的文件。路径相对本目录。", "Read this page first; for detail, open only the file you need. Paths are relative to this directory."), "",
          T("| 文件 | 里面有什么 | 什么时候读 | 约 token |", "| File | What is in it | When to read it | ~tokens |"), "|---|---|---|---|"]
    L += [f"| `{p}` | {title} | {when} | {n or '—'} |" for p, title, when, n in files]
    L += ["", T("## 读法", "## How to read"), ""] + [f"- {x}" for x in _legend()] + [
        T("- 「看到的」可以对着截图核实；「推断」是工具和看图模型的判断，依据写在每镜文件的「判断依据」里，两者对不上时以截图为准。",
          "- What is “seen” can be checked against the frames; what is “inferred” is the tools' and image readers' judgement, with the basis in each shot file. When they disagree, trust the frames.")]
    return "\n".join(L)


# ------------------------------------------------------------------ write -------------------------------------------

def write(b: dict, out: Path) -> Path:
    """Write the package into `out` (the breakdown's output directory). Returns the entry file."""
    from .report import _unit_of

    d = out / DIR
    if d.is_dir():
        shutil.rmtree(d)  # generated: a re-run with a different shot count must not leave stale shot files
    (d / "shots").mkdir(parents=True)
    files: list[tuple[str, str, str, int]] = []

    def put(rel: str, text: str, title: str, when: str) -> None:
        (out / rel).write_text(text, encoding="utf-8")
        files.append((rel, title, when, tokens(text)))

    roles, units = narrative.shot_roles(b), _unit_of(b)
    lines = [timeline_line(r, roles, units) for r in b["shots"]]
    body = "\n".join([T("# 时间线", "# Timeline"), ""] + _legend() + ["", "```reel-timeline"] + lines + ["```"])
    put(f"{DIR}/timeline.md", _sized({FORMAT: VERSION, "part": "timeline", "shots": len(lines)}, body),
        T("时间线：一行一个镜头", "Timeline: one line per shot"), T("想知道某段讲什么、哪镜要复核、某镜怎么做", "what a stretch says, which shots need review, how a shot was made"))
    for stem, title, when, section in _topics(b):
        text = _plain(section)
        if _has_body(text):
            put(f"{DIR}/{stem}.md", _sized({FORMAT: VERSION, "part": stem}, text), title, when)
    shot_tokens = 0
    for r in b["shots"]:
        text = _shot_file(r)
        (d / "shots" / f"{_shot_name(r['index'])}.md").write_text(text, encoding="utf-8")
        shot_tokens += tokens(text)
    files.append((f"{DIR}/shots/01.md … {len(b['shots']):02d}.md", T("逐镜细节", "Per-shot detail"),
                  T("核实某一镜：看得到的、推断和依据、提示词、帧图", "checking one shot: what is seen, the inference and its basis, prompts, frames"),
                  shot_tokens // max(1, len(b["shots"]))))
    files.append(("breakdown.json", T("完整原始数据", "Full raw data"), T("程序读取；模型一般不用打开", "for programs; a model rarely needs it"),
                  tokens((out / "breakdown.json").read_text(encoding="utf-8")) if (out / "breakdown.json").is_file() else 0))
    media = [p for p in ("shots/", "stems/", "sfx/", "packaging/", "storyboard.jpg", "audio.png") if (out / p.rstrip("/")).exists()]
    if media:
        files.append((", ".join(media), T("截图、分轨音频、字幕文件", "frames, audio stems, subtitle files"),
                      T("看图核实、复刻时当参考", "checking by eye, references for the remake"), 0))
    entry = out / ENTRY
    entry.write_text(_front(_card(b), _overview(b, files)), encoding="utf-8")
    return entry


# ------------------------------------------------------------------ read (reference reader) ------------------------

def read_file(path: Path) -> tuple[dict, str]:
    """(front matter, body) of one Reel file."""
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    fm, _, body = text[4:].partition("\n---\n")
    return yaml.safe_load(fm) or {}, body.strip()


def read(root: Path) -> dict:
    """The package as data: {"card", "timeline": [shot dicts], "shots": {n: front matter}}. For programs that consume a Reel."""
    root = Path(root)
    card, _ = read_file(root / ENTRY)
    _, tl = read_file(root / DIR / "timeline.md")
    shots = {}
    for p in sorted((root / DIR / "shots").glob("*.md")):
        fm, _ = read_file(p)
        shots[fm.get("shot")] = fm
    return {"card": card, "timeline": [x for x in map(parse_timeline_line, tl.splitlines()) if x], "shots": shots}


# ------------------------------------------------------------------ check (conformance) ----------------------------

SCHEMA = Path(__file__).with_name("reel.schema.json")
_RE_LINE = re.compile(r"^#(\d+) (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)((?: \| [a-z]+~? [^|]+?)*)$")
_RE_ID = re.compile(r"\(([a-z_0-9]+)\)")


def _schema_errors(data: dict, part: str, where: str) -> list[str]:
    try:
        import jsonschema
    except ImportError:  # the structural checks below still run; the schema adds field-level detail when installed
        return []
    import json

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator({**schema, "$ref": f"#/$defs/{part}"})
    return [f"{where}: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(data)]


def check(root: Path) -> list[str]:
    """Problems that make `root` a non-conforming Reel package (empty list = conforms). See docs/reel.md, “Conformance”."""
    root = Path(root)
    errs: list[str] = []
    entry = root / ENTRY
    if not entry.is_file():
        return [f"{ENTRY} missing"]
    card, body = read_file(entry)
    errs += _schema_errors(card, "card", ENTRY)
    for p in re.findall(r"^\| `([^`]+)` \|", body, re.M):
        if "…" not in p and "," not in p and not (root / p).exists():
            errs.append(f"{ENTRY}: map lists {p}, which does not exist")
    for p in sorted((root / DIR).glob("*.md")):
        fm, _ = read_file(p)
        errs += _schema_errors(fm, "part", f"{DIR}/{p.name}")
        if not fm:
            errs.append(f"{DIR}/{p.name}: no front matter")
    tl_path = root / DIR / "timeline.md"
    if not tl_path.is_file():
        return errs + [f"{DIR}/timeline.md missing"]
    _, tl = read_file(tl_path)
    m = re.search(r"```reel-timeline\n(.*?)\n?```", tl, re.S)
    if not m:
        return errs + [f"{DIR}/timeline.md: no ```reel-timeline block"]
    rows = []
    for ln in [x for x in m.group(1).split("\n") if x.strip()]:
        if not _RE_LINE.match(ln):
            errs.append(f"{DIR}/timeline.md: not a timeline line: {ln[:80]}")
            continue
        rows.append(parse_timeline_line(ln))
    if card.get("shots") is not None and len(rows) != card["shots"]:
        errs.append(f"{DIR}/timeline.md: {len(rows)} lines, card says {card['shots']} shots")
    last = 0
    for x in rows:
        if x["shot"] <= last:
            errs.append(f"{DIR}/timeline.md: #{x['shot']:02d} out of order")
        if x["end"] < x["start"]:
            errs.append(f"{DIR}/timeline.md: #{x['shot']:02d} ends before it starts")
        last = x["shot"]
        sp = root / DIR / "shots" / f"{_shot_name(x['shot'])}.md"
        if not sp.is_file():
            errs.append(f"{DIR}/shots/{sp.name} missing")
            continue
        fm, _ = read_file(sp)
        errs += _schema_errors(fm, "shot", f"{DIR}/shots/{sp.name}")
        t = fm.get("time") or [None, None]
        if fm.get("shot") != x["shot"] or t[0] is None or abs(t[0] - x["start"]) > 0.06 or abs(t[1] - x["end"]) > 0.06:
            errs.append(f"{DIR}/shots/{sp.name}: shot number or time differs from the timeline")
        made = _RE_ID.search(x.get("made~", ""))
        if made and made.group(1) != (fm.get("inferred") or {}).get("made"):
            errs.append(f"{DIR}/shots/{sp.name}: inferred.made differs from the timeline's made~")
        for k, fp in (fm.get("frames") or {}).items():
            if not (root / fp).is_file():
                errs.append(f"{DIR}/shots/{sp.name}: frames.{k} {fp} does not exist")
    return errs
