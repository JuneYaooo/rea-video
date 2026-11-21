"""Small shared helpers: logging, JSON IO, env loading, time formatting."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger("rea_video")
OCR_LANGS = ("zh", "ja", "ko")  # subtitle/huazi OCR languages; zh is the bundled recognizer, others are in overlay._REC_MODELS
ASR_LANGS = ("auto", "bn")  # speech recognition: auto is SenseVoice (zh/en/ja/ko/yue, detected per line); bn is speech.BN_MODEL_DIR


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)


def write_json(path: Path, data: Any, compact: bool = False) -> Path:
    """compact=True: no indentation (about half the size; for large machine-read files like breakdown.json)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return json.loads(Path(path).read_text(encoding="utf-8"))


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


def load_env_files(paths: Iterable[str | Path]) -> list[str]:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars win. Returns loaded files."""
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
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
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
