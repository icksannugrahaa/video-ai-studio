# Sandroid AI Video

Bikin & edit video AI untuk TikTok, Reels, Shorts, Facebook, X, dan YouTube
dari sebuah prompt. Video dipecah per scene, tiap scene digenerate sebagai
clip, lalu digabung bersama narasi (TTS) dan subtitle yang sinkron, plus musik
latar opsional.

Aplikasi ini tidak punya AI sendiri: tiap user memasukkan **endpoint
OpenAI-compatible + API key** (disarankan Sandroid AI Router, yang punya
video async job, TTS, dan klasifikasi model).

## Fitur (MVP)

- Multi-user (admin + user), token API per user
- Profil provider per user: endpoint, API key (terenkripsi), model chat/video/TTS, voice
- Storyboard otomatis dari prompt (LLM), bisa diedit manual
- Generate clip per scene (async, retry, kontinuitas frame terakhir antar scene)
- Narasi TTS per kalimat → subtitle dengan timing tepat (burn-in ASS + file SRT)
- Musik latar upload dengan ducking otomatis, loudness −14 LUFS
- Preset platform: 9:16, 16:9, 1:1, 4:5 (+ batas durasi)
- Edit lewat prompt — hanya scene yang berubah yang digenerate ulang
- Render bisa dilanjutkan setelah restart

## Jalankan lokal

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cp .env.example .env   # isi SAV_SECRET_KEY, SAV_ADMIN_PASSWORD, SAV_COOKIE_SECURE=0
(cd ui && npm install && npm run build)
cd backend && ../.venv/bin/python -m app.main     # http://127.0.0.1:7300
```

Tes: `cd backend && ../.venv/bin/python -m pytest -q` (butuh ffmpeg untuk tes pipeline).

## Deploy (PRoot / PM2)

```bash
git clone <repo> /opt/sandroid-ai-video && cd /opt/sandroid-ai-video
bash deploy/install.sh      # pertama kali: membuat .env → isi SAV_ADMIN_PASSWORD → jalankan lagi
```

`ui/dist` ikut di-commit, jadi server tidak perlu Node. Arahkan Cloudflare
Tunnel / reverse proxy ke `127.0.0.1:7300`.

## API

Semua endpoint di bawah `/api` (dokumentasi interaktif: `/api/docs`). Klien
lain memakai `Authorization: Bearer sav_…` (buat token di Pengaturan).

**Panduan lengkap: [docs/API.md](docs/API.md)** — autentikasi, alur, job & polling,
referensi endpoint, kode error, contoh curl/Python. Isi yang sama tampil di web UI
(menu **API**, `/#/docs`) dengan contoh yang sudah memakai alamat server.

Alur singkat:

1. `POST /api/projects` `{prompt, preset, target_seconds, profile_id}`
2. `POST /api/projects/{id}/plan` → job; pantau `GET /api/jobs/{job_id}`
3. `POST /api/projects/{id}/render` `{}` (estimasi) lalu `{"confirm": true}`
4. `GET /api/projects/{id}/files/final.mp4` dan `final.srt`
5. `POST /api/projects/{id}/edit` `{instruction}` untuk revisi via prompt
