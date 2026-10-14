"""Client for a user's OpenAI-compatible endpoint (normally the Sandroid AI Router).

Only the calls the pipeline needs: chat completion (planner/editor), model
list with ``kind``, video generation (router async job → poll → content, or a
plain synchronous call for other providers) and text-to-speech.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass

import requests

CHAT_TIMEOUT = 180
TTS_TIMEOUT = 120
VIDEO_SUBMIT_TIMEOUT = 120
VIDEO_SYNC_TIMEOUT = 900
VIDEO_POLL_SECONDS = 8
VIDEO_MAX_WAIT = 20 * 60
POLL_MAX_CONSECUTIVE_ERRORS = 10  # a busy/restarting router must not kill a running clip
# Content/copyright refusals repeat for the same prompt: retrying only burns time.
_POLICY_MARKERS = ("copyright", "moderation", "sensitive", "policy", "inappropriate", "nsfw", "prohibited",
                   "violat", "not allowed")


def is_policy_refusal(message: str) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in _POLICY_MARKERS)

_KIND_PATTERNS = (
    ("video", r"kling|sora|seedance|dreamina|hailuo|veo[-_.\d]|luma|runway|pika|vidu|wan.*(t2v|i2v|video)"),
    ("music", r"lyria|suno|musicgen|(^|[-_./])music([-_./\d]|$)"),
    ("image", r"dall-?e|gpt[-_]?image|flux|imagen|sdxl|seedream|-image"),
    ("tts", r"(^|[-_./])tts([-_./\d]|$)|text-to-speech|aura"),
    ("stt", r"whisper|transcribe|(^|[-_./])asr([-_./\d]|$)"),
    ("embedding", r"embed"),
)


class ProviderError(Exception):
    """Upstream failure. ``message`` is safe to show the owning user (no key)."""

    def __init__(self, message: str, status: int = 502, retryable: bool = True):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable


def guess_kind(model_id: str) -> str:
    name = (model_id or "").lower()
    for kind, pattern in _KIND_PATTERNS:
        if re.search(pattern, name):
            return kind
    return "chat"


@dataclass
class VideoResult:
    data: bytes
    ext: str = "mp4"


class ProviderClient:
    def __init__(self, base_url: str, api_key: str, session: requests.Session | None = None):
        base = (base_url or "").strip().rstrip("/")
        self.base = base[:-3] if base.endswith("/v1") else base
        self.api_key = api_key
        self.http = session or requests.Session()

    # ── helpers ────────────────────────────────────────────────────────
    def _headers(self, json_body: bool = True) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _error(resp: requests.Response, what: str) -> ProviderError:
        detail = ""
        try:
            body = resp.json()
            err = body.get("error") if isinstance(body, dict) else None
            detail = (err.get("message") if isinstance(err, dict) else err) or body.get("message") or ""
        except ValueError:
            detail = (resp.text or "")[:200]
        retryable = resp.status_code in (408, 409, 425, 429) or resp.status_code >= 500
        return ProviderError(f"{what} gagal (HTTP {resp.status_code}): {str(detail)[:200]}",
                             status=resp.status_code, retryable=retryable)

    def _call(self, method: str, url: str, what: str, **kwargs) -> requests.Response:
        """HTTP call with network errors mapped to a retryable ``ProviderError``
        (never an unhandled exception, never the URL/key in the message)."""
        try:
            return self.http.request(method, url, **kwargs)
        except requests.Timeout as exc:
            raise ProviderError(f"{what}: timeout menunggu endpoint", status=504) from exc
        except requests.RequestException as exc:
            raise ProviderError(f"{what}: koneksi ke endpoint gagal ({type(exc).__name__})", status=502) from exc

    def _download(self, url: str, timeout: int = 300) -> bytes:
        absolute = url if url.startswith("http") else f"{self.base}{url}"
        headers = self._headers(False) if absolute.startswith(self.base) else {}
        resp = self._call("GET", absolute, "unduh hasil", headers=headers, timeout=timeout)
        if resp.status_code != 200 or not resp.content:
            raise ProviderError(f"unduh hasil gagal (HTTP {resp.status_code})")
        return resp.content

    # ── models ─────────────────────────────────────────────────────────
    def list_models(self) -> list[dict]:
        resp = self._call("GET", f"{self.base}/v1/models", "daftar model", headers=self._headers(False), timeout=60)
        if resp.status_code != 200:
            raise self._error(resp, "daftar model")
        out = []
        for item in (resp.json() or {}).get("data") or []:
            model_id = str(item.get("id") or "")
            if model_id:
                out.append({"id": model_id, "kind": item.get("kind") or guess_kind(model_id)})
        return out

    # ── chat ───────────────────────────────────────────────────────────
    def chat(self, model: str, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        resp = self._call(
            "POST", f"{self.base}/v1/chat/completions", "chat",
            headers=self._headers(),
            json={"model": model, "messages": messages, "temperature": temperature,
                  "max_tokens": max_tokens, "stream": False},
            timeout=CHAT_TIMEOUT,
        )
        if resp.status_code != 200:
            raise self._error(resp, "chat")
        try:
            choice = (resp.json().get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content")
        except (ValueError, AttributeError) as exc:
            raise ProviderError("respons chat tidak valid") from exc
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not content:
            raise ProviderError("model chat tidak mengembalikan teks")
        return content

    # ── text-to-speech ─────────────────────────────────────────────────
    def tts(self, model: str, text: str, voice: str = "", language: str = "", fmt: str = "wav") -> bytes:
        body = {"model": model, "input": text, "response_format": fmt}
        if voice:
            body["voice"] = voice
        if language:
            body["language"] = language
        resp = self._call("POST", f"{self.base}/v1/audio/speech", "TTS", headers=self._headers(), json=body,
                          timeout=TTS_TIMEOUT)
        if resp.status_code != 200 or not resp.content:
            raise self._error(resp, "TTS")
        ctype = resp.headers.get("Content-Type", "")
        if "json" in ctype:  # base64 envelope (router ?response_format=json style)
            payload = resp.json()
            return base64.b64decode(payload.get("audio") or "")
        return resp.content

    # ── video ──────────────────────────────────────────────────────────
    def generate_video(self, model: str, prompt: str, *, seconds: int | None = None,
                       aspect_ratio: str | None = None, resolution: str | None = None,
                       image_png: bytes | None = None, enable_audio: bool = False,
                       should_cancel=None) -> VideoResult:
        """Generate one clip. Tries the router async job API first and falls
        back to a synchronous request when the provider has no job support."""
        body: dict = {"model": model, "prompt": prompt, "enable_audio": enable_audio}
        if seconds:
            body["duration"] = int(seconds)
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if resolution:
            body["resolution"] = resolution
        if image_png:
            body["image"] = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")

        resp = self._call("POST", f"{self.base}/v1/videos/generations", "generate video",
                          headers=self._headers(), json={**body, "async": True}, timeout=VIDEO_SUBMIT_TIMEOUT)
        if resp.status_code == 202:
            job = resp.json()
            return self._wait_media_job(job.get("id") or "", should_cancel)
        if resp.status_code == 200:
            return self._video_from_body(resp.json())
        if resp.status_code in (400, 422) and "async" in (resp.text or "").lower():
            resp = self._call("POST", f"{self.base}/v1/videos/generations", "generate video",
                              headers=self._headers(), json=body, timeout=VIDEO_SYNC_TIMEOUT)
            if resp.status_code == 200:
                return self._video_from_body(resp.json())
        raise self._error(resp, "generate video")

    def _video_from_body(self, body: dict) -> VideoResult:
        items = (body or {}).get("data") or [{}]
        item = items[0] if isinstance(items[0], dict) else {}
        if item.get("b64_json"):
            return VideoResult(base64.b64decode(item["b64_json"]))
        if item.get("url"):
            return VideoResult(self._download(item["url"]))
        raise ProviderError("respons video tidak berisi file")

    def _wait_media_job(self, job_id: str, should_cancel=None) -> VideoResult:
        if not job_id:
            raise ProviderError("job video tidak punya id")
        deadline = time.monotonic() + VIDEO_MAX_WAIT
        errors = 0
        while time.monotonic() < deadline:
            if should_cancel and should_cancel():
                raise ProviderError("dibatalkan", status=499, retryable=False)
            time.sleep(VIDEO_POLL_SECONDS)
            try:
                resp = self._call("GET", f"{self.base}/v1/media/jobs/{job_id}", "status job video",
                                  headers=self._headers(False), timeout=60)
            except ProviderError:
                resp = None
            if resp is None or resp.status_code >= 500:
                # The job keeps running on the router; a slow or restarting
                # router only delays the answer. Give up after a long streak.
                errors += 1
                if errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                    raise ProviderError("status job video tidak bisa dicek (router tidak merespons)", status=504)
                continue
            errors = 0
            if resp.status_code != 200:
                raise self._error(resp, "status job video")
            job = resp.json()
            status = job.get("status")
            if status == "succeeded":
                if job.get("content_url"):
                    return VideoResult(self._download(job["content_url"]))
                url = (job.get("result") or {}).get("url")
                if url:
                    return VideoResult(self._download(url))
                raise ProviderError("job video selesai tanpa file")
            if status == "failed":
                err = job.get("error") or {}
                status_code = int(err.get("status") or 502)
                message = str(err.get("message") or "unknown")
                if is_policy_refusal(message):
                    raise ProviderError(f"ditolak filter konten/hak cipta model video — ubah prompt visual scene ini "
                                        f"({message[-220:]})", status=422, retryable=False)
                raise ProviderError(f"job video gagal: {message}", status=status_code,
                                    retryable=status_code >= 500 or status_code == 429)
        raise ProviderError("job video melebihi batas waktu", status=504)
