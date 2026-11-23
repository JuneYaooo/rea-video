"""Take this machine's paths out of breakdown packages written before packages became portable.

Report by default; `apply=True` rewrites. The source video stays findable through $REA_VIDEO_HOME/sources.json.
Paths a later step still opens (the user's swap images, remake/ run files) are kept and listed: do not share those as is.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from .util import BREAKDOWN, _portable_breakdown, _sources_file, _source_key, dumps_rows

TEXT = {".json", ".md", ".html", ".txt", ".vtt", ".yaml", ".yml", ".csv", ".ass", ".srt", ".jsonl"}


def _command(cmd: str) -> str:
    """A `rea-video tiles` command that runs from the package root."""
    try:
        t = shlex.split(cmd)
    except ValueError:
        return cmd
    if t[:2] != ["rea-video", "tiles"] or len(t) < 3:
        return cmd
    t[2] = "."
    if "-o" in t[:-1]:
        t[t.index("-o") + 1] = Path(t[t.index("-o") + 1]).name
    return " ".join(x if "{" in x else shlex.quote(x) for x in t)


def _clean_review(d: dict) -> dict:
    d = dict(d)
    if d.get("video"):
        d["video"] = Path(str(d["video"])).name
    if d.get("zoom_cmd"):
        d["zoom_cmd"], d["zoom_cmd_cwd"] = _command(d["zoom_cmd"]), "package root"
    if isinstance(d.get("shots"), list):
        d["shots"] = [{**s, "zoom_cmd": _command(s["zoom_cmd"])} if isinstance(s, dict) and s.get("zoom_cmd") else s for s in d["shots"]]
    pack = d.get("packaging")
    if isinstance(pack, dict) and isinstance(pack.get("stickers"), list):
        d["packaging"] = {**pack, "stickers": [{**s, "frame_cmd": _command(s["frame_cmd"])} if isinstance(s, dict) and s.get("frame_cmd") else s
                                               for s in pack["stickers"]]}
    return d


def _clean_named(d: dict, *keys: str) -> dict:
    d = dict(d)
    for k in keys:
        if k == "source.path" and isinstance(d.get("source"), dict) and d["source"].get("path"):
            d["source"] = {**d["source"], "path": Path(str(d["source"]["path"])).name}
        elif k == "video" and d.get("video"):
            d["video"] = Path(str(d["video"])).name
    return d


def _dump(data: Any, old: str, rows: bool) -> str:
    if rows:
        return dumps_rows(data)
    if "\n" not in old.strip():
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _replace(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _remembered(src: dict) -> bool:
    try:
        return bool(json.loads(_sources_file().read_text(encoding="utf-8")).get(_source_key(src)))
    except (OSError, ValueError):
        return False


def clean_package(root: Path, home: str, apply: bool = False) -> dict:
    root = Path(root)
    p = root / BREAKDOWN
    old = p.read_text(encoding="utf-8")
    b = json.loads(old)
    src = b.get("source") or {}
    res: dict[str, Any] = {"package": str(root), "cleaned": [], "kept": [], "error": None}
    source_is_local = Path(str(src.get("path") or "")).is_absolute()
    jobs: list[tuple[Path, str, Any, bool]] = []
    if source_is_local or (isinstance(b.get("stems"), dict) and Path(str(b["stems"].get("effects") or "")).is_absolute()):
        res["cleaned"].append(BREAKDOWN)
        if apply:
            new = _portable_breakdown(b, root)  # also records where the video is
            if source_is_local and Path(src["path"]).is_file() and not _remembered(src):
                res["error"] = f"could not record the source video in {_sources_file()}; package left as it was"
                res["cleaned"] = []
                return res
            jobs.append((p, old, new, False))
    for rel, fix, rows in (("review_tasks.json", _clean_review, True),
                           ("frames/scenes.json", lambda d: _clean_named(d, "video"), False),
                           ("survey/survey.json", lambda d: _clean_named(d, "source.path"), False),
                           ("survey/timeline.json", lambda d: _clean_named(d, "source.path"), False)):
        f = root / rel
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        if home not in text:
            continue
        res["cleaned"].append(rel)
        if apply:
            jobs.append((f, text, fix(json.loads(text)), rows))
    for f, text, data, rows in jobs:
        _replace(f, _dump(data, text, rows))
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.suffix.lower() in TEXT:
            rel = str(f.relative_to(root))
            try:
                has = home in f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if has and (apply or rel not in res["cleaned"]):
                res["kept"].append(rel)
    return res


def clean_paths(start: Path, apply: bool = False, home: str | None = None) -> list[dict]:
    home = home or str(Path.home())
    return [_guarded(f.parent, home, apply) for f in sorted(Path(start).expanduser().resolve().rglob(BREAKDOWN))
            if (f.parent / "VIDEO.md").is_file()]


def _guarded(root: Path, home: str, apply: bool) -> dict:
    """One unreadable or half-written package is reported like the other per-file failures, so the rest of the
    directory still gets cleaned instead of the whole run dying on it."""
    try:
        return clean_package(root, home, apply)
    except (OSError, ValueError) as exc:
        return {"package": str(root), "cleaned": [], "kept": [], "error": f"could not read {BREAKDOWN}: {exc}"}
