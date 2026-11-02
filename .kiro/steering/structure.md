---
inclusion: always
---

# Structure

- `backend/app/api/`: HTTP routes for auth, profiles, and projects
- `backend/app/pipeline/`: planner, media (ffmpeg), presets, subtitles, and text
- `backend/app/providers/client.py`: client for the OpenAI-compatible provider
- `backend/app/engine.py`: render steps
- `backend/app/worker.py`: background jobs
- `backend/app/repo.py`, `backend/app/db.py`: data access and SQLite setup
- `backend/tests/`: API, pipeline, and unit tests
- `ui/src/pages/`, `ui/src/components/`: React screens and components
- `ui/src/i18n.jsx`: UI translations
- `deploy/`: PM2 config and install script
- `docs/`: API reference and design specs
