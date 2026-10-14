# Instruksi Claude untuk sandroid-ai-video

Aplikasi pembuat & editor video AI untuk sosmed (TikTok/Reels/Shorts/FB/X) dan
YouTube. Video panjang dipecah per scene → tiap scene digenerate sebagai clip →
digabung dengan narasi (TTS) + subtitle (+ musik upload) dalam satu timeline.
Desain lengkap: `docs/specs/2026-10-13-mvp-design.md`.

## Teknologi

- Backend: Python **3.10** (server PRoot = 3.10.12, jangan pakai sintaks >3.10),
  FastAPI + SQLite (WAL) + ffmpeg 4.4. Kode di `backend/app/`.
- UI: React + Vite di `ui/`, hasil build `ui/dist/` **di-commit** (server tidak
  perlu build) dan disajikan oleh backend.
- Satu proses PM2 (`deploy/ecosystem.config.cjs`, uvicorn) + worker thread di
  dalamnya untuk job plan/render/edit.

## Konsep penting

- App tidak punya AI sendiri: tiap user mengisi **profil provider** (endpoint
  OpenAI-compatible + API key, terenkripsi Fernet dari `SECRET_KEY`). Biasanya
  endpoint = Sandroid AI Router (`https://ai.sandroid.works`) yang punya
  `/v1/videos/generations` (+ `"async": true` → `/v1/media/jobs/{id}`),
  `/v1/audio/speech`, `/v1/models` dengan field `kind`.
- Multi-user: semua data di-scope per `user_id`. Admin pertama dari `.env`.
- Timing subtitle diambil dari durasi TTS **per kalimat** (bukan STT).
- State render disimpan per scene/langkah di DB → render bisa resume setelah
  restart PM2; scene yang selesai dilewati.

## Aturan kerja

- **Jangan commit / push / deploy** — user melakukannya sendiri; biarkan
  perubahan uncommitted.
- Jangan pernah log/expose API key, token, atau traceback ke client.
- Render di HP: default 720p, `veryfast`, satu ffmpeg render sekaligus.
- Target deploy ada dua: **server Linux biasa** dan **PRoot di HP Android**. Jangan
  bergantung pada fitur khusus Mac/distro: filter ffmpeg opsional (mis. `xfade`)
  dideteksi via `media.has_filter()` dengan fallback; venv lokal Mac (Py 3.14 +
  SQLite 3.51) bukan acuan produksi.
- Tes: `cd backend && ../.venv/bin/python -m pytest -q` (tes ffmpeg auto-skip
  jika ffmpeg tidak ada). UI: `cd ui && npm run build`.

## Server produksi (PRoot di HP)

Akses dari Mac via USB: `adb -s 100019012C80000M forward tcp:18022 tcp:8022`
lalu `ssh -p 18022 127.0.0.1 'cd ~ && bash ./start-ubuntu22.sh "<cmd>"'`.
Target deploy: `/opt/sandroid-ai-video`. Detail lengkap ada di repo
bot-sandroid `docs/PROOT_ACCESS.md`. Minta izin sebelum restart proses PM2.

## Proyek terkait

- Router: `~/Documents/Project/bot-sandroid` (core/router/*). Fitur audio router
  (TTS adapter, `/v1/music/generations`, async media jobs) dibuat 2026-10-13
  khusus untuk app ini. Musik Lyria butuh Gemini paid tier (free tier = 429).
