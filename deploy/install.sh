#!/usr/bin/env bash
# Install / update sandroid-ai-video on the PRoot server (Ubuntu 22.04).
# Run from the repo root:  bash deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

command -v ffmpeg >/dev/null || { echo "ffmpeg belum terpasang: apt install -y ffmpeg"; exit 1; }
command -v python3 >/dev/null || { echo "python3 tidak ditemukan"; exit 1; }
fc-list 2>/dev/null | grep -qi dejavu || echo "Saran: apt install -y fonts-dejavu-core (font subtitle)"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r backend/requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i "s|^SAV_SECRET_KEY=.*|SAV_SECRET_KEY=${secret}|" .env
  echo ">> .env dibuat. Isi SAV_ADMIN_PASSWORD lalu jalankan ulang script ini."
  exit 0
fi
grep -q '^SAV_ADMIN_PASSWORD=.\+' .env || { echo ">> Isi SAV_ADMIN_PASSWORD di .env dulu."; exit 1; }

mkdir -p data/logs
[ -f ui/dist/index.html ] || echo "Peringatan: ui/dist belum ada (build di Mac: cd ui && npm run build)"

if pm2 describe sandroid-ai-video >/dev/null 2>&1; then
  pm2 restart sandroid-ai-video --update-env
else
  pm2 start deploy/ecosystem.config.cjs
fi
pm2 save
echo ">> Jalan di http://127.0.0.1:$(grep '^SAV_PORT=' .env | cut -d= -f2) — arahkan reverse proxy / tunnel ke sana."
