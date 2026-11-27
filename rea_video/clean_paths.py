"""Take this machine's paths out of breakdown packages written before packages became portable.

Report by default; `apply=True` rewrites. The source video stays findable through $REA_VIDEO_HOME/sources.json.
Paths a later step still opens (the user's swap images, remake/ run files) are kept and listed: do not share those as is.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from .util import BREAKDOWN, _portable_breakdown, _sources_file, _source_key, dumps_rows

TEXT = {".json", ".md", ".html", ".txt", ".vtt", ".yaml", ".yml", ".csv", ".ass", ".srt", ".jsonl"}
JSON_SUFFIXES = {".json", ".jsonl"}

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s\"'<>]*")
# A path is local when it is rooted: a drive letter, a UNC share, or a POSIX root. A URL is not.
_ROOTED = (
    re.compile(r"(?<![\w\\])(?:[A-Za-z]:[\\/])[^\s\"'<>|]*"),
    re.compile(r"\\\\[^\s\"'<>|\\]+\\[^\s\"'<>|]*"),
    re.compile(r"(?<![\w:/])/(?:Users|home|Volumes|private|tmp|opt|srv|root|var)/[^\s\"'<>|]*"),
)


def local_paths(text: str) -> list[str]:
    """Every rooted local path in this text. URLs are stripped first, so `https://host/a/b` is not one."""
    text = _URL.sub(" ", text)
    return [m.group(0) for rx in _ROOTED for m in rx.finditer(text)]


def has_local_path(value: Any) -> bool:
    """True when any string in the value (decoded, not JSON-escaped) is or contains a rooted path.

    Decoding first is the point: on Windows the text holds `C:\\\\Users\\\\name`, so comparing against
    `str(Path.home())` finds nothing even though the path is right there."""
    if isinstance(value, str):
        return bool(local_paths(value))
    if isinstance(value, dict):
        return any(has_local_path(k) or has_local_path(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(has_local_path(v) for v in value)
    return False


def file_has_local_path(f: Path) -> bool:
    """A package file still carrying a rooted path, judged on its decoded content where it has structure."""
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if f.suffix.lower() in JSON_SUFFIXES:
        try:
            return has_local_path(json.loads(text))
        except ValueError:
            pass
    return bool(local_paths(text))


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


def clean_package(root: Path, apply: bool = False) -> dict:
    root = Path(root)
    p = root / BREAKDOWN
    old = p.read_text(encoding="utf-8")
    b = json.loads(old)
    if not isinstance(b, dict) or not isinstance(b.get("source") or {}, dict):
        raise ValueError(f"{BREAKDOWN} is not a breakdown")
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
        data = json.loads(text)
        if not has_local_path(data):
            continue
        res["cleaned"].append(rel)
        if apply:
            jobs.append((f, text, fix(data), rows))
    for f, text, data, rows in jobs:
        _replace(f, _dump(data, text, rows))
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.suffix.lower() in TEXT:
            rel = f.relative_to(root).as_posix()
            if file_has_local_path(f) and (apply or rel not in res["cleaned"]):
                res["kept"].append(rel)
    return res


def clean_paths(start: Path, apply: bool = False, home: str | None = None) -> list[dict]:
    """`home` is kept for callers that still pass it; rooted paths are recognised without it now."""
    return [_guarded(f.parent, apply) for f in sorted(Path(start).expanduser().resolve().rglob(BREAKDOWN))
            if (f.parent / "VIDEO.md").is_file()]


def _guarded(root: Path, apply: bool) -> dict:
    """One unreadable or half-written package is reported like the other per-file failures, so the rest of the
    directory still gets cleaned instead of the whole run dying on it."""
    try:
        return clean_package(root, apply)
    except (OSError, ValueError, TypeError) as exc:
        return {"package": str(root), "cleaned": [], "kept": [], "error": f"could not clean this package: {exc}"}
