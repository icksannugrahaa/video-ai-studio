# Sandroid AI Video

Create and edit AI videos for TikTok, Reels, Shorts, Facebook, X, and YouTube from a single prompt. The video is split into scenes, each scene is generated as a clip, then assembled together with narration (TTS) and synchronized subtitles, plus optional background music.

The app has no AI of its own: each user supplies an **OpenAI-compatible endpoint + API key** (Sandroid AI Router is recommended, since it offers async video jobs, TTS, and model classification).

<p>
  <img alt="CI" src="https://github.com/icksannugrahaa/video-ai-studio/actions/workflows/ci.yml/badge.svg">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10-blue">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-%E2%89%A50.110-009688">
  <img alt="React" src="https://img.shields.io/badge/React-18-61dafb">
  <img alt="Vite" src="https://img.shields.io/badge/Vite-5-646cff">
</p>

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Run locally](#run-locally)
- [Configuration (.env)](#configuration-env)
- [Testing](#testing)
- [API](#api)
- [Deploy (PRoot / PM2)](#deploy-proot--pm2)
- [Project structure](#project-structure)
- [License](#license)

## Features

- **Multi-user** (admin + user) with a per-user API token
- **Per-user provider profiles**: endpoint, API key (Fernet-encrypted), chat/video/TTS models, voice
- **Automatic storyboard** from a prompt via an LLM, editable by hand
- **Per-scene clip generation** (async, retries, last-frame continuity across scenes)
- **Per-sentence TTS narration** → accurately timed subtitles (burned-in ASS + SRT file)
- **Background music** upload with automatic ducking, −14 LUFS loudness
- **Platform presets**: 9:16, 16:9, 1:1, 4:5 (+ duration limits)
- **Edit via prompt** — only the changed scenes are regenerated
- **Resumable renders** after a restart (per-scene state persisted in the DB)

## Architecture

| Layer | Technology | Location |
| --- | --- | --- |
| Backend | Python 3.10, FastAPI, SQLite (WAL), ffmpeg 4.4 | `backend/app/` |
| Worker | Thread inside the uvicorn process for plan/render/edit jobs | `backend/app/worker.py` |
| UI | React 18 + Vite 5 (build output in `ui/dist/`, committed) | `ui/` |
| Deploy | Single PM2 process (uvicorn) | `deploy/ecosystem.config.cjs` |

Render flow: `prompt → storyboard (LLM) → clip per scene → TTS narration → ASS/SRT subtitles → mux + music → final.mp4`. Subtitle timing comes from the **per-sentence** TTS duration (not STT).

## Prerequisites

- **Python 3.10** (production PRoot server = 3.10.12 — avoid syntax newer than 3.10)
- **ffmpeg 4.4+** with `ffprobe` on `PATH` (pipeline tests auto-skip if missing)
- **Node 18+** (only needed to build the UI; the server does not need Node because `ui/dist` is committed)

## Run locally

```bash
# 1. Virtualenv + dependencies
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt

# 2. Configuration
cp .env.example .env
#    set SAV_SECRET_KEY (>= 32 chars), SAV_ADMIN_PASSWORD, and SAV_COOKIE_SECURE=0 for local http

# 3. Build the UI
(cd ui && npm install && npm run build)

# 4. Run the backend (serves the UI from ui/dist)
cd backend && ../.venv/bin/python -m app.main
# → http://127.0.0.1:7300
```

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

UI development with hot reload:

```bash
cd ui && npm run dev   # Vite dev server, proxies the API to the backend
```

## Configuration (.env)

All variables are read from `.env` (see [`.env.example`](.env.example)) or the environment:

| Variable | Default | Description |
| --- | --- | --- |
| `SAV_SECRET_KEY` | — | **Required**, ≥ 32 chars. Fernet key for encrypting provider API keys. Changing it makes stored API keys unreadable. |
| `SAV_ADMIN_USERNAME` | `admin` | First admin username. |
| `SAV_ADMIN_PASSWORD` | — | First admin password. |
| `SAV_HOST` | `127.0.0.1` | uvicorn bind host. |
| `SAV_PORT` | `7300` | HTTP port. |
| `SAV_DATA_DIR` | `./data` | Location of SQLite + project files. |
| `SAV_RENDER_WIDTH` | `720` | Render short side (px) — the default for phone CPUs. |
| `SAV_RENDER_FPS` | `30` | Render frame rate. |
| `SAV_FFMPEG_PRESET` | `veryfast` | x264 preset. |
| `SAV_CLIP_CONCURRENCY` | `2` | Parallel clip generation when continuity is off. |
| `SAV_COOKIE_SECURE` | `1` | Set `0` only when serving over plain http (local testing). |

## Testing

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

Pipeline tests require `ffmpeg` (they auto-skip when it is unavailable). All other tests use isolated fixtures (a temporary data dir + a fake provider), so they never touch production data.

Build the UI: `cd ui && npm run build`.

## API

All endpoints live under `/api` (interactive docs: `/api/docs`). External clients use `Authorization: Bearer sav_…` (create a token in Settings).

**Full guide: [docs/API.md](docs/API.md)** — authentication, flow, jobs & polling, endpoint reference, error codes, curl/Python examples. The same content is shown in the web UI (the **API** menu, `/#/docs`) with examples already using the server address.

Quick flow:

1. `POST /api/projects` `{prompt, preset, target_seconds, profile_id}`
2. `POST /api/projects/{id}/plan` → job; poll `GET /api/jobs/{job_id}`
3. `POST /api/projects/{id}/render` `{}` (estimate) then `{"confirm": true}`
4. `GET /api/projects/{id}/files/final.mp4` and `final.srt`
5. `POST /api/projects/{id}/edit` `{instruction}` to revise via prompt

## Deploy (PRoot / PM2)

```bash
git clone https://github.com/icksannugrahaa/video-ai-studio.git /opt/sandroid-ai-video
cd /opt/sandroid-ai-video
bash deploy/install.sh   # first run: creates .env → fill SAV_ADMIN_PASSWORD → run again
```

`ui/dist` is committed, so the server does not need Node. Point a Cloudflare Tunnel / reverse proxy at `127.0.0.1:7300`.

## Project structure

```text
backend/
  app/
    api/          # FastAPI routers (auth, profiles, projects)
    pipeline/     # planner, media (ffmpeg), subtitles, text, presets
    providers/    # OpenAI-compatible client
    config.py db.py engine.py repo.py security.py worker.py main.py
  tests/          # pytest: api, pipeline, units
ui/               # React + Vite (builds to ui/dist)
deploy/           # ecosystem.config.cjs (PM2), install.sh
docs/             # API.md, specs/
```

## License

Not yet determined.
