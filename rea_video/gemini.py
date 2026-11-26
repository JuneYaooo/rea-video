"""Google Gemini as the image / video reader, through its own API (not an OpenAI-compatible gateway).

Set GEMINI_API_KEY (or GOOGLE_API_KEY); the model is REA_GEMINI_MODEL. Gemini watches
video with its sound, so a clip goes in whole: inline when small, else through the Files API (deleted after the
answer; an upload that can't be deleted expires on Google's side within 48 hours). Short clips are sampled densely
(video_metadata.fps), long ones at Gemini's default. Used only when the user asks for a VLM (--vlm): the video leaves
the machine.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .media import duration_s
from .util import LOG

API = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-3.7-flash"
INLINE_MAX = 14 * 1024 * 1024  # base64 adds 33%: 14 MB raw -> ~18.7 MB body, under Gemini's 20 MB inline limit
CLIP_FPS = ((30.0, 10.0), (120.0, 4.0))  # (clips up to s, frames a second); longer: Gemini's default (1)


def api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")


def configured() -> bool:
    return bool(api_key())


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    """ask_json(prompt, media) like VLMClient; media = [(path, mime)], images and video/mp4 clips."""
    video_ok = True

    media = "both"  # watches the clip with its sound and reads the key frames

    def __init__(self, model: str | None = None, key: str | None = None, timeout: float = 600.0):
        self.key = key or api_key()
        if not self.key:
            raise GeminiError("GEMINI_API_KEY is not set")
        self.model = model or os.getenv("REA_GEMINI_MODEL", "") or DEFAULT_MODEL
        self.timeout = timeout
        self.models = [self.model]

    def describe(self) -> str:
        return f"Gemini {self.model}"

    def _call(self, method: str, url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 120.0):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"x-goog-api-key": self.key, "User-Agent": f"rea-video/{__version__}", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return dict(r.headers), r.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()[:300].decode("utf-8", "replace")
            raise GeminiError(f"HTTP {exc.code}: {body}") from None

    def _upload(self, p: Path, mime: str, max_wait: float = 900.0) -> dict:
        size = p.stat().st_size
        h, _ = self._call("POST", f"{API}/upload/v1beta/files", json.dumps({"file": {"display_name": "rea-video"}}).encode(),
                          {"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                           "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": mime,
                           "Content-Type": "application/json"})
        url = {k.lower(): v for k, v in h.items()}.get("x-goog-upload-url")
        if not url:
            raise GeminiError("the Files API returned no upload URL")
        _, body = self._call("POST", url, p.read_bytes(), {"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                                                           "X-Goog-Upload-Command": "upload, finalize"}, timeout=3600.0)
        info = json.loads(body)["file"]
        waited = 0.0
        try:
            while info.get("state") == "PROCESSING" and waited < max_wait:
                time.sleep(2.0)
                waited += 2.0
                info = json.loads(self._call("GET", f"{API}/v1beta/{info['name']}")[1])
        except Exception:
            self._delete(info.get("name", ""))
            raise
        if info.get("state") != "ACTIVE":
            self._delete(info.get("name", ""))
            raise GeminiError(f"uploaded file state {info.get('state')}")
        return info

    def _delete(self, name: str) -> None:
        if not name:
            return
        try:
            self._call("DELETE", f"{API}/v1beta/{name}")
        except Exception as exc:  # noqa: BLE001  cleanup never masks the answer; Google drops it within 48 h
            LOG.warning("could not delete %s from Gemini (%s); it expires within 48 hours", name, str(exc)[:80])

    def ask_json(self, prompt: str, media: list[tuple[Path, str]], max_tokens: int = 4096) -> dict:
        """An answer cut off at maxOutputTokens (finishReason MAX_TOKENS: thinking counts against the budget) is asked
        again with double the budget, up to REA_VLM_MAX_TOKENS, reusing the uploads; a cut-off reply that parsed is kept."""
        from .vlm import TruncatedAnswer, max_tokens_ceiling, parse_json

        ceiling = max(max_tokens, max_tokens_ceiling())
        parts, uploaded = [], []
        inline = sum(Path(p).stat().st_size for p, _ in media) <= INLINE_MAX
        try:
            for p, mime in media:
                p = Path(p)
                part: dict
                if inline or not mime.startswith("video/"):
                    part = {"inline_data": {"mime_type": mime, "data": base64.b64encode(p.read_bytes()).decode()}}
                else:
                    info = self._upload(p, mime)
                    uploaded.append(info["name"])
                    part = {"file_data": {"mime_type": info.get("mimeType") or mime, "file_uri": info["uri"]}}
                if mime.startswith("video/"):
                    d = duration_s(p)
                    if d <= 0:
                        LOG.warning("could not read the length of %s; Gemini samples it at its default rate", p.name)
                    fps = next((f for lim, f in CLIP_FPS if 0 < d <= lim), None)
                    if fps:
                        part["video_metadata"] = {"fps": fps}
                parts.append(part)
            parts.append({"text": prompt})
            budget = max_tokens
            while True:
                body = {"contents": [{"role": "user", "parts": parts}],
                        "generationConfig": {"maxOutputTokens": budget, "temperature": 0.2, "responseMimeType": "application/json"}}
                _, raw = self._call("POST", f"{API}/v1beta/models/{self.model}:generateContent", json.dumps(body).encode(),
                                    {"Content-Type": "application/json"}, timeout=self.timeout)
                data = json.loads(raw)
                cand = (data.get("candidates") or [{}])[0] if isinstance(data, dict) else {}
                finish = str(cand.get("finishReason") or "") if isinstance(cand, dict) else ""
                try:
                    text = "".join(pt.get("text", "") for pt in cand["content"]["parts"])
                except (KeyError, IndexError, TypeError) as exc:
                    if finish != "MAX_TOKENS":  # e.g. a safety block: not something a bigger budget fixes
                        raise GeminiError(f"no answer: {str(data)[:200]}") from exc
                    text = ""  # the whole budget went to thinking
                try:
                    if finish == "MAX_TOKENS" and not text.strip():
                        raise TruncatedAnswer("empty Gemini answer (cut off at maxOutputTokens)")
                    return parse_json(text)
                except ValueError as exc:
                    if finish != "MAX_TOKENS":
                        raise
                    if budget >= ceiling:
                        raise TruncatedAnswer(f"{exc} (cut off at maxOutputTokens={budget}; raise REA_VLM_MAX_TOKENS)") from None
                    LOG.warning("Gemini %s answer cut off at maxOutputTokens=%d; asking again with %d",
                                self.model, budget, min(ceiling, budget * 2))
                    budget = min(ceiling, budget * 2)
        finally:
            for name in uploaded:
                self._delete(name)
