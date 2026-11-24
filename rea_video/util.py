"""Small shared helpers: logging, JSON IO, env loading, time formatting."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger("rea_video")
OCR_LANGS = ("zh", "en", "ja", "ko")  # subtitle/huazi OCR languages; zh is the bundled recognizer, others are in overlay._REC_MODELS
ASR_LANGS = ("auto", "bn")  # speech recognition: auto is SenseVoice (zh/en/ja/ko/yue, detected per line); bn is speech.BN_MODEL_DIR


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)


def write_json(path: Path, data: Any, compact: bool = False) -> Path:
    """compact=True: no indentation (about half the size; for large machine-read files like breakdown.json)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == BREAKDOWN:
        data = _portable_breakdown(data, path.parent)
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=_json_default) if compact
            else json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))
    path.write_text(text + "\n", encoding="utf-8")
    return path


def dumps_rows(data: dict) -> str:
    """JSON with one top-level key per line and every list item on its own line.

    For files an agent reads or edits (review tasks / answers): one shot per line keeps them
    grep-able and editable by id without the token cost of full indentation."""
    def one(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=_json_default)

    lines = []
    for k, v in data.items():
        if isinstance(v, list) and v:
            body = ",\n".join("  " + one(x) for x in v)
            lines.append(f"{one(k)}:[\n{body}\n]")
        elif isinstance(v, dict) and any(isinstance(x, list) and x for x in v.values()):
            lines.append(f"{one(k)}:{{\n" + ",\n".join(
                f" {one(kk)}:[\n" + ",\n".join("  " + one(x) for x in vv) + "\n ]" if isinstance(vv, list) and vv else f" {one(kk)}:{one(vv)}"
                for kk, vv in v.items()) + "\n}")
        else:
            lines.append(f"{one(k)}:{one(v)}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def read_json(path: Path) -> Any:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _local_breakdown(data, Path(path).parent) if Path(path).name == BREAKDOWN else data


# A package gets shared, so breakdown.json must not carry where the video sits on this machine (a home directory names
# the user). The file keeps the video's name; the local path lives in $REA_VIDEO_HOME/sources.json and comes back on read.
BREAKDOWN = "breakdown.json"


def _sources_file() -> Path:
    return Path(os.getenv("REA_VIDEO_HOME", str(Path.home() / ".rea-video"))).expanduser() / "sources.json"


def _source_key(src: dict) -> str:
    return str(src.get("sha256_head") or f"{src.get('filename')}:{src.get('duration')}")


_SOURCES_SEEN: dict[str, str] = {}  # this process's own videos, found even when the index cannot be written or read


def _remember_source(src: dict, path: str) -> None:
    _SOURCES_SEEN[_source_key(src)] = path
    f = _sources_file()
    try:
        known = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        if known.get(_source_key(src)) == path:
            return
        known[_source_key(src)] = path
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(known, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(f)
    except (OSError, ValueError) as exc:  # only the convenience of finding the video later is lost
        LOG.warning("could not remember where the source video is: %s", exc)


def _portable_breakdown(data: Any, root: Path) -> Any:
    """A copy to write: the source path reduced to the file name, paths inside the package made relative."""
    if not isinstance(data, dict) or not isinstance(data.get("source"), dict):
        return data
    src = dict(data["source"])
    path = str(src.get("path") or "")
    if path and Path(path).is_file():
        _remember_source(src, str(Path(path).resolve()))
    if path:
        src["path"] = src.get("filename") or Path(path).name
    out = {**data, "source": src}
    stems = data.get("stems")
    if isinstance(stems, dict) and Path(str(stems.get("effects") or "")).is_absolute():
        try:
            rel = Path(stems["effects"]).resolve().relative_to(Path(root).resolve() / "stems")
            out["stems"] = {**stems, "effects": str(rel)}
        except ValueError:
            out["stems"] = {**stems, "effects": Path(stems["effects"]).name}
    return out


def _local_breakdown(data: Any, root: Path) -> Any:
    """The source path back as a usable local path: the remembered one, else next to the package."""
    if not isinstance(data, dict) or not isinstance(data.get("source"), dict):
        return data
    src = data["source"]
    path = str(src.get("path") or "")
    if not path or Path(path).is_absolute():
        return data
    candidates = [Path(_SOURCES_SEEN[_source_key(src)])] if _source_key(src) in _SOURCES_SEEN else []
    try:
        f = _sources_file()
        remembered = json.loads(f.read_text(encoding="utf-8")).get(_source_key(src)) if f.is_file() else None
        if remembered:
            candidates.append(Path(remembered))
    except (OSError, ValueError):
        pass
    root = Path(root).resolve()
    candidates += [root / path, root.parent / path, root.parent / "videos" / path, root.parent.parent / path]
    found = next((c for c in candidates if c.is_file()), root / path)
    return {**data, "source": {**src, "path": str(found)}}


def _json_default(value: Any) -> Any:
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except ImportError:  # pragma: no cover
        pass
    if isinstance(value, Path):
        return str(value)
    return str(value)


def read_image(path):
    """cv2.imread that also opens paths with non-ASCII characters on Windows (imread goes through the ANSI
    file API there and returns None for a Chinese folder name). None when the file is missing or unreadable."""
    import cv2
    import numpy as np

    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def write_image(path, img, params: list[int] | None = None) -> bool:
    """cv2.imwrite counterpart of read_image; the format follows the file extension."""
    import cv2

    ok, buf = cv2.imencode(Path(path).suffix or ".jpg", img, params or [])
    if ok:
        buf.tofile(str(path))
    return bool(ok)


def _proxy_map() -> dict:
    """Proxy map for urllib, with the Windows "only NO_PROXY is set" case fixed.

    urllib's getproxies() is getproxies_environment() or getproxies_registry(). On Windows a user
    behind a system proxy usually exports NO_PROXY alone, so getproxies_environment() comes back as
    {'no': ...} — non-empty, hence truthy — and the registry is never consulted. Every download then
    dials out directly and fails behind a firewall instead of using the proxy the OS already has.
    """
    import urllib.request

    env = urllib.request.getproxies_environment()
    if os.name != "nt" or set(env) != {"no"}:
        return urllib.request.getproxies()
    try:
        registry = urllib.request.getproxies_registry()
    except Exception:  # pragma: no cover - registry lookups are best effort
        return env
    merged = dict(registry)
    merged.update(env)
    return merged


def fetch(url: str, dest: Path, timeout: float = 60.0) -> None:
    """Download url to dest. The timeout is per read, so a stalled connection raises instead of hanging the run."""
    import shutil
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler(_proxy_map()))
    with opener.open(url, timeout=timeout) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f, 1 << 20)


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


_ENV_QUOTED = re.compile(r"""((["']).*?\2)\s*(?:#.*)?""")


def _env_value(raw: str) -> str:
    """The value of a KEY=VALUE line, read the way dotenv files usually are: a quoted value ends at its closing
    quote and a comment after it is dropped; unquoted, a comment starts at a # that follows whitespace, so
    pa#ss and http://x/#frag stay whole."""
    quoted = _ENV_QUOTED.fullmatch(raw.strip())
    if quoted:
        return quoted.group(1)[1:-1]
    return re.sub(r"\s#.*", "", raw).strip()


def load_env_files(paths: Iterable[str | Path]) -> list[str]:
    """Minimal .env loader (KEY=VALUE lines, `# comment` after a value allowed). Existing env vars win. Returns loaded files."""
    loaded: list[str] = []
    for raw in paths:
        if not raw:
            continue
        p = Path(raw).expanduser()
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = _env_value(value)
        loaded.append(str(p))
    return loaded


def fmt_time(seconds: float) -> str:
    """MM:SS.mmm. Rounds to milliseconds before splitting off the minutes, so 59.9996 is 01:00.000, not 00:60.000."""
    ms = round(max(0.0, float(seconds)) * 1000)
    m, ms = divmod(ms, 60_000)
    return f"{m:02d}:{ms / 1000:06.3f}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def round_floats(obj: Any, nd: int = 4) -> Any:
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, nd) for v in obj]
    try:
        import numpy as np

        if isinstance(obj, np.floating):
            return round(float(obj), nd)
        if isinstance(obj, np.integer):
            return int(obj)
    except ImportError:  # pragma: no cover
        pass
    return obj


MAX_MODEL_THREADS = 8  # the ONNX models here stop getting faster past this, and would crowd out the picture analysis


def _usable_cpus() -> int:
    """Logical CPUs this process may run on (a container's or taskset's limit, where the OS reports one)."""
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return os.cpu_count() or 4


def _fast_cores() -> int | None:
    """Cores that run a model thread at full speed: Apple silicon's performance cores (mixing in efficiency cores
    makes a model slower, not faster), else physical cores (a hyper-thread pair shares one core's arithmetic)."""
    import subprocess

    if sys.platform == "darwin":
        for key in ("hw.perflevel0.physicalcpu", "hw.physicalcpu"):
            try:
                n = int(subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=2).stdout.strip())
                if n > 0:
                    return n
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
        return None
    if sys.platform.startswith("linux"):
        try:
            cores, phys, core = set(), None, None
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                k, _, v = line.partition(":")
                k = k.strip()
                if k == "physical id":
                    phys = v.strip()
                elif k == "core id":
                    core = v.strip()
                elif not line.strip():
                    if core is not None:
                        cores.add((phys, core))
                    phys = core = None
            if core is not None:
                cores.add((phys, core))
            return len(cores) or None
        except OSError:
            return None
    return None


def model_threads() -> int:
    """Threads for each ONNX model (sound separation, OCR): $REA_VIDEO_THREADS if set, else this machine's full-speed
    cores, never more than the CPUs this process may use, at most MAX_MODEL_THREADS. More threads than that only make
    the models and the picture analysis fight over the same cores. (The thread count can move a model's output by
    ~1e-7, far below what a 16-bit file keeps.)"""
    env = os.getenv("REA_VIDEO_THREADS", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    usable = _usable_cpus()
    fast = _fast_cores() or max(1, usable // 2)
    return max(1, min(fast, usable, MAX_MODEL_THREADS))
