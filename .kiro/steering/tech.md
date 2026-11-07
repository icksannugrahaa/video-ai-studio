---
inclusion: always
---

# Tech

- Backend: Python 3.10, FastAPI, SQLite (WAL), ffmpeg 4.4. Do not use syntax
  newer than Python 3.10.
- UI: React and Vite. The build output in `ui/dist/` is committed, because the
  server does not build the UI.
- Runtime: one PM2 process running uvicorn, with a worker thread inside it for
  plan, render, and edit jobs.

## Deploy targets

The app runs on a regular Linux server and in PRoot on an Android phone.

- Do not depend on Mac-only or distro-only features. The local Mac virtualenv is
  not a reference for production.
- Detect optional ffmpeg filters such as `xfade` with `media.has_filter()` and
  provide a fallback.
- Render on phones with 720p, the `veryfast` preset, and one ffmpeg render at a
  time by default.

## Security

Never log or expose API keys, tokens, or tracebacks to clients.

## Commands

- Backend tests: `cd backend && ../.venv/bin/python -m pytest -q`. ffmpeg tests
  skip automatically when ffmpeg is missing.
- UI build: `cd ui && npm run build`.

## Working rules

Do not commit, push, or deploy. Leave changes uncommitted for the maintainer.
