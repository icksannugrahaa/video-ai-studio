"""Runtime configuration from environment variables (``.env`` is loaded by the
process manager or ``load_dotenv`` below — no extra dependency)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal ``KEY=VALUE`` loader; existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    secret_key: str
    admin_username: str
    admin_password: str
    host: str
    port: int
    render_width: int
    render_fps: int
    ffmpeg_preset: str
    clip_concurrency: int
    cookie_secure: bool

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


def load_settings() -> Settings:
    _load_dotenv(ROOT_DIR / ".env")
    data_dir = Path(os.environ.get("SAV_DATA_DIR") or ROOT_DIR / "data")
    secret = os.environ.get("SAV_SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("SAV_SECRET_KEY must be set (>= 32 chars) — see .env.example")
    return Settings(
        data_dir=data_dir,
        secret_key=secret,
        admin_username=os.environ.get("SAV_ADMIN_USERNAME", "admin"),
        admin_password=os.environ.get("SAV_ADMIN_PASSWORD", ""),
        host=os.environ.get("SAV_HOST", "127.0.0.1"),
        port=int(os.environ.get("SAV_PORT", "7300")),
        render_width=int(os.environ.get("SAV_RENDER_WIDTH", "720")),
        render_fps=int(os.environ.get("SAV_RENDER_FPS", "30")),
        ffmpeg_preset=os.environ.get("SAV_FFMPEG_PRESET", "veryfast"),
        clip_concurrency=max(1, int(os.environ.get("SAV_CLIP_CONCURRENCY", "2"))),
        cookie_secure=os.environ.get("SAV_COOKIE_SECURE", "1") not in ("0", "false", "no"),
    )
