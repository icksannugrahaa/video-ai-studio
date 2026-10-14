"""Shared fixtures: isolated settings/data dir and a fake provider that
produces real (tiny) media with ffmpeg so the pipeline runs end to end."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.providers import ProviderError, VideoResult  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    import app.engine
    monkeypatch.setattr(app.engine, "CLIP_RETRY_DELAYS", (0, 0))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data", secret_key="x" * 40, admin_username="admin", admin_password="admin-pass-123",
        host="127.0.0.1", port=0, render_width=180, render_fps=12, ffmpeg_preset="ultrafast",
        clip_concurrency=1, cookie_secure=False,
    )


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


class FakeClient:
    """Stands in for ProviderClient; records calls."""

    calls: list = []
    storyboard: dict = {"title": "Kucing Astronot", "music_prompt": "Playful orchestral, 110 BPM", "scenes": [
        {"visual_prompt": "A cat astronaut floating in space, cinematic", "narration": "Halo semua. Ini kucing astronot.",
         "duration": 3},
        {"visual_prompt": "The cat astronaut lands on the moon, cinematic", "narration": "Dia mendarat di bulan!",
         "duration": 2},
    ]}
    edited: dict | None = None
    fail_video_times: int = 0
    fail_prompts: tuple = ()  # prompts containing one of these fail permanently (non-retryable)

    def __init__(self, base_url: str, api_key: str):
        self.base_url, self.api_key = base_url, api_key

    def chat(self, model, messages, temperature=0.7, max_tokens=4096):
        FakeClient.calls.append(("chat", model))
        if "songwriter" in messages[-1]["content"]:
            return json.dumps({"style": "Cheerful pop, 120 BPM, ukulele", "vocal": "bright female vocal", "sections": [
                {"name": "Intro", "lines": []},
                {"name": "Verse 1", "lines": [{"t": 0.5, "text": "Kucing kecil terbang tinggi"},
                                              {"t": 3, "text": "Menuju bulan yang sepi"}]},
                {"name": "Chorus", "lines": [{"t": 2, "text": "baris mundur dibuang"}, {"t": 4, "text": "Halo bulan!"}]}]})
        if "AI music generators" in messages[-1]["content"]:
            return '{"music_prompt": "Dreamy lo-fi piano, 80 BPM, full length 0:05"}'
        board = FakeClient.edited if ("Instruction:" in messages[-1]["content"] and FakeClient.edited) else FakeClient.storyboard
        return "```json\n" + json.dumps(board) + "\n```"

    def list_models(self):
        return [{"id": "kimi", "kind": "chat"}, {"id": "seedance-2.5", "kind": "video"},
                {"id": "edge-tts", "kind": "tts"}, {"id": "qwen3-tts-flash-realtime", "kind": "tts"}]

    def generate_video(self, model, prompt, *, seconds=None, aspect_ratio=None, resolution=None,
                       image_png=None, enable_audio=False, should_cancel=None):
        FakeClient.calls.append(("video", prompt, seconds, aspect_ratio, image_png is not None))
        if any(marker in prompt for marker in FakeClient.fail_prompts):
            raise ProviderError("ditolak filter konten", status=422, retryable=False)
        if FakeClient.fail_video_times > 0:
            FakeClient.fail_video_times -= 1
            raise ProviderError("upstream busy", status=503, retryable=True)
        out = Path(self._tmp()) / "clip.mp4"
        _ffmpeg(["-f", "lavfi", "-i", f"testsrc=size=160x284:rate=12:duration={seconds or 2}",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)])
        return VideoResult(out.read_bytes())

    def tts(self, model, text, voice="", language="", fmt="wav"):
        FakeClient.calls.append(("tts", text, voice))
        out = Path(self._tmp()) / "tts.wav"
        seconds = max(0.4, len(text) / 25)
        _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds:.2f}", "-ar", "24000", str(out)])
        return out.read_bytes()

    @staticmethod
    def _tmp() -> str:
        import tempfile
        return tempfile.mkdtemp(prefix="fake-provider-")


@pytest.fixture
def fake_client():
    FakeClient.calls = []
    FakeClient.edited = None
    FakeClient.fail_video_times = 0
    FakeClient.fail_prompts = ()
    return FakeClient


@pytest.fixture
def app(settings, fake_client):
    from app.main import create_app
    return create_app(settings, client_factory=fake_client, start_worker=False)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


def login(client, username="admin", password="admin-pass-123"):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    client.headers.update({"X-Requested-With": "sav"})
    return resp.json()
