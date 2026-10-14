# Dokumentasi API — Sandroid AI Video

API HTTP/JSON untuk membuat video dari prompt dari aplikasi lain (mis. bot WhatsApp,
script, atau backend sendiri). Semua yang bisa dilakukan di web UI juga bisa lewat API.

- **Base URL:** `https://<host-kamu>/api` (lokal: `http://127.0.0.1:7300/api`)
- **Format:** JSON (UTF-8), kecuali upload musik (multipart) dan unduh file (biner)
- **Referensi interaktif (Swagger):** `https://<host-kamu>/api/docs` — skema lengkap
  setiap endpoint, bisa dicoba langsung dari browser

---

## 1. Autentikasi

1. Login ke web UI → **Pengaturan → Token API → Token baru**.
2. Salin token (`sav_…`). Token **hanya ditampilkan sekali**; yang disimpan server
   hanya hash-nya.
3. Kirim di setiap request:

```http
Authorization: Bearer sav_xxxxxxxxxxxxxxxxxxxxxxxx
```

- Token mewakili user pembuatnya: hanya melihat project & profil milik user itu.
- Request dengan token **tidak** perlu header `X-Requested-With` (header itu hanya
  untuk sesi cookie browser, sebagai perlindungan CSRF).
- Cabut token kapan saja di Pengaturan; request berikutnya langsung `401`.
- Jangan taruh token di kode frontend publik / repo — perlakukan seperti password.

## 2. Konvensi

| Hal | Aturan |
|---|---|
| Waktu | Unix epoch **detik** (`created_at`, `updated_at`) |
| Durasi | detik, desimal (`duration`, `total_seconds`) |
| Error | status HTTP ≠ 2xx dengan body `{"error": "pesan"}` |
| Job berjalan lama | endpoint aksi mengembalikan **job**; pantau dengan polling (lihat §4) |
| Satu job per project | job utama (plan/render/edit/compose/regenerate) berjalan satu per project; job kedua → `409` |

Kode status yang perlu ditangani:

| Status | Arti |
|---|---|
| `400` | Permintaan tidak bisa diproses (mis. storyboard kosong, profil belum dipilih) |
| `401` | Token tidak ada / tidak valid / user dinonaktifkan |
| `403` | Bukan admin (endpoint admin) |
| `404` | Project/profil/job/file tidak ditemukan (atau milik user lain) |
| `409` | Masih ada job berjalan untuk project ini |
| `413` | File musik > 30 MB |
| `422` | Validasi input gagal, mis. `{"error": "target_seconds: Input should be greater than or equal to 5"}` |
| `502` | Provider AI (router) gagal — pesan aman untuk ditampilkan, tanpa detail internal |

## 3. Alur singkat (dari prompt ke MP4)

```text
POST /projects                     → buat project (prompt, platform, durasi, profil)
POST /projects/{id}/plan           → job: AI menyusun storyboard (± 10–60 dtk)
GET  /projects/{id}                → (poll) tunggu job selesai, baca scenes
POST /projects/{id}/render  {}     → estimasi: berapa clip yang akan dibuat (gratis)
POST /projects/{id}/render  {"confirm": true} → job: buat clip + narasi + gabung
GET  /projects/{id}                → (poll) progres; selesai jika files berisi final.mp4
GET  /projects/{id}/files/final.mp4 → unduh video
```

> **Biaya & waktu.** Membuat clip memakai kredit provider video (mis. seedance-2.5 ±20,8
> kredit per detik video) dan butuh waktu ±5–10 menit per clip. Karena itu render
> **wajib** dikonfirmasi dengan `{"confirm": true}`; tanpa itu endpoint hanya
> mengembalikan estimasi.

## 4. Job & polling

Aksi panjang (plan, render, edit, compose, preview, regenerate) membuat **job**:

```json
{
  "id": 26, "project_id": 3, "kind": "render",
  "status": "running", "progress": 0.45, "message": "Clip 3/6 selesai",
  "payload": {}, "result": {}, "created_at": 1791971195, "updated_at": 1791972101
}
```

| `status` | Arti |
|---|---|
| `queued` | Menunggu giliran (render dijalankan satu per satu di server) |
| `running` | Sedang diproses; `progress` 0–1 dan `message` diperbarui |
| `succeeded` | Selesai; ringkasan di `result` |
| `failed` | Gagal; alasan di `message`. Clip yang sudah jadi **tetap tersimpan** |
| `canceled` | Dibatalkan pengguna |

Cara memantau (pilih salah satu):

- `GET /projects/{id}` → field `active_job` (job utama yang sedang berjalan, `null` jika
  tidak ada) dan `jobs` (5 job terakhir, terbaru di depan).
- `GET /jobs/{job_id}` → satu job.

Polling yang disarankan: setiap **5–10 detik** selama render (render bisa puluhan menit).

**Melanjutkan setelah gagal:** panggil lagi `POST /projects/{id}/render {"confirm": true}`.
Clip yang sudah jadi tidak dibuat ulang — render lanjut dari scene yang gagal/belum jadi.
Job yang terputus karena server restart juga otomatis dilanjutkan.

## 5. Referensi endpoint

Semua path relatif ke `/api`. 🔒 = butuh token. 👑 = khusus admin.

### Akun & token

| Method | Path | Keterangan |
|---|---|---|
| GET | `/auth/me` 🔒 | User saat ini |
| GET | `/auth/tokens` 🔒 | Daftar token (tanpa nilai token; hanya `prefix`) |
| POST | `/auth/tokens` 🔒 | Buat token. Body `{"name": "bot-wa"}` → `{"id","name","prefix","token",…}` |
| DELETE | `/auth/tokens/{id}` 🔒 | Cabut token |
| GET | `/users` 🔒👑 | Daftar user |
| POST | `/users` 🔒👑 | Buat user `{"username","password","role":"user"\|"admin"}` |
| PATCH | `/users/{id}` 🔒👑 | `{"active": false}` / `{"password": "…"}` |
| GET / PUT | `/settings` 🔒👑 | `{"registration_open": true}` |

### Profil provider (endpoint AI + model)

| Method | Path | Keterangan |
|---|---|---|
| GET | `/profiles` 🔒 | Daftar profil (`api_key_masked`, key asli tidak pernah dikirim) |
| POST | `/profiles` 🔒 | Buat profil (lihat body di bawah) |
| PATCH | `/profiles/{id}` 🔒 | Ubah sebagian field; `api_key` kosong/tidak dikirim = tidak diganti |
| DELETE | `/profiles/{id}` 🔒 | Hapus profil |
| GET | `/profiles/{id}/models` 🔒 | Model dari endpoint, dikelompokkan: `by_field.chat/video/tts` |
| POST | `/profiles/models` 🔒 | Probe model sebelum profil disimpan: `{"base_url","api_key"}` atau `{"base_url","profile_id"}` |

```json
POST /profiles
{
  "name": "router", "base_url": "https://ai.sandroid.works", "api_key": "sk-…",
  "chat_model": "cbi/kimi-k3", "video_model": "cbi/seedance-2.5",
  "tts_model": "ali/qwen3-tts-flash", "tts_voice": "Cherry", "clip_seconds": 10
}
```

### Project

| Method | Path | Keterangan |
|---|---|---|
| GET | `/presets` 🔒 | Platform: `tiktok`, `reels`, `shorts`, `youtube`, `facebook`, `instagram`, `x` (rasio & durasi maks) |
| GET | `/projects` 🔒 | Daftar project + ringkasan (`scene_count`, `clips_ready`, `files`, `active_job`) |
| POST | `/projects` 🔒 | Buat project |
| GET | `/projects/{id}` 🔒 | Detail lengkap: `scenes`, `files`, `active_job`, `preview_job`, `jobs`, `stats` |
| PATCH | `/projects/{id}` 🔒 | Ubah judul/prompt/preset/durasi/bahasa/profil/`options` (boleh saat render berjalan) |
| DELETE | `/projects/{id}` 🔒 | Hapus project + semua file (batalkan job dulu) |

```json
POST /projects
{
  "title": "Bersih Bersih",
  "prompt": "Video lagu anak 30 detik: Bima (3 th) merapikan mainan, menyapu, cuci tangan…",
  "preset": "shorts", "target_seconds": 30, "language": "id-ID", "profile_id": 1,
  "options": {"continuity": true, "transition": 0.5, "burn_subtitles": true}
}
```

`options` (semua opsional):

| Field | Default | Arti |
|---|---|---|
| `continuity` | `true` | Scene bertanda `continues` dimulai dari frame terakhir scene sebelumnya |
| `transition` | `0.5` | Crossfade antar scene (detik, 0–1.5; `0` = potong langsung) |
| `burn_subtitles` | `true` | Tempel subtitle ke video (SRT selalu dibuat) |
| `keep_clip_audio` | `false` | Campur audio bawaan clip (jika model menghasilkan suara) |
| `voice` | `""` | Override voice TTS profil |
| `music_mode` | `"external"` | `none` \| `external` (musik dibuat di luar lalu di-upload) |
| `music_style` | `"instrumental"` | `instrumental` (backsound di bawah narasi) \| `song` (lirik menggantikan narasi) |
| `music_volume` | `0.25` | Volume backsound 0–1 (otomatis turun saat narasi) |
| `bible_character` / `bible_world` / `bible_style` | dibuat AI | Deskripsi tetap yang ditempel ke prompt **setiap** clip agar karakter & lokasi konsisten |

### Storyboard & render

| Method | Path | Keterangan |
|---|---|---|
| POST | `/projects/{id}/plan` 🔒 | Job: AI menyusun storyboard + bible dari `prompt` |
| PUT | `/projects/{id}/scenes` 🔒 | Ganti storyboard manual (lihat body). Scene yang visual/durasi/`continues`-nya berubah perlu clip baru |
| POST | `/projects/{id}/render` 🔒 | `{}` → estimasi; `{"confirm": true}` → job render (lanjut dari clip yang belum jadi) |
| POST | `/projects/{id}/edit` 🔒 | Job: ubah storyboard via instruksi lalu render bagian yang berubah. `{"instruction": "ganti scene 2 jadi malam hari"}` |
| POST | `/projects/{id}/scenes/{idx}/regenerate` 🔒 | Job: buat ulang clip satu scene (`idx` mulai 0) |
| POST | `/projects/{id}/compose` 🔒 | Job: gabung ulang `final.mp4` tanpa membuat clip baru (setelah ganti musik/volume/subtitle/transisi). `{"partial": true}` = `preview.mp4` |
| POST | `/projects/{id}/preview` 🔒 | Job "render sementara": `preview.mp4` dari clip yang sudah jadi. **Boleh saat render berjalan** (jalur terpisah); status di `preview_job` |

```json
PUT /projects/{id}/scenes
{
  "scenes": [
    {"visual_prompt": "Wide shot of the character's bedroom, toys on the floor…",
     "narration": "Pagi cerah, kamar Bima penuh mainan.", "duration": 6, "continues": false},
    {"visual_prompt": "The character puts toys into the red toy box…",
     "narration": "Ayo rapikan!", "duration": 6, "continues": true}
  ]
}
```

Field scene di `GET /projects/{id}` → `scenes[]`:

| Field | Arti |
|---|---|
| `idx`, `visual_prompt`, `narration`, `duration`, `continues` | Isi storyboard |
| `clip_status` | `pending` \| `running` \| `done` \| `failed` |
| `clip_version` vs `version` | Clip valid jika `clip_status == "done"` **dan** `clip_version == version` |
| `clip_file` | Path clip (unduh via `/files/{clip_file}`) |
| `clip_error` | Alasan gagal (mis. ditolak filter hak cipta) |
| `clip_gen_seconds`, `clip_attempts` | Lama pembuatan clip & jumlah percobaan |

### Musik

| Method | Path | Keterangan |
|---|---|---|
| POST | `/projects/{id}/music-prompt` 🔒 | Tulis ulang prompt musik (sinkron, ±30 dtk). `{"hint": "lebih ceria"}` |
| POST | `/projects/{id}/song` 🔒 | Tulis lirik bertimestamp + prompt lagu (mode lagu, sinkron) |
| POST | `/projects/{id}/music` 🔒 | Upload musik, `multipart/form-data` field `file` (mp3/wav/m4a/aac/ogg/flac, ≤ 30 MB) |
| DELETE | `/projects/{id}/music` 🔒 | Hapus musik |

Setelah upload/ganti musik, panggil `POST /projects/{id}/compose` agar masuk ke video.

### File & job

| Method | Path | Keterangan |
|---|---|---|
| GET | `/projects/{id}/files/final.mp4` 🔒 | Video final (juga `final.srt`, `preview.mp4`, `preview.srt`, `music.<ext>`, `clips/scene_N_vM.mp4`) |
| GET | `/projects/{id}/jobs` 🔒 | Riwayat job project |
| GET | `/jobs/{id}` 🔒 | Satu job |
| POST | `/jobs/{id}/cancel` 🔒 | Batalkan job (clip yang sudah jadi tetap tersimpan) |
| GET | `/health` | Cek server hidup (tanpa token) |

## 6. Contoh

### curl

```bash
BASE=https://video.example.com/api
TOKEN=sav_xxxxxxxx
AUTH=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")

# 1. buat project
PID=$(curl -s "${AUTH[@]}" -X POST $BASE/projects -d '{
  "title": "Bersih Bersih", "prompt": "Video lagu anak 30 detik tentang bersih-bersih kamar",
  "preset": "shorts", "target_seconds": 30, "profile_id": 1}' | jq -r .id)

# 2. susun storyboard, tunggu selesai
curl -s "${AUTH[@]}" -X POST $BASE/projects/$PID/plan > /dev/null
until [ "$(curl -s "${AUTH[@]}" $BASE/projects/$PID | jq -r '.active_job')" = "null" ]; do sleep 5; done

# 3. estimasi lalu render
curl -s "${AUTH[@]}" -X POST $BASE/projects/$PID/render -d '{}' | jq .estimate
curl -s "${AUTH[@]}" -X POST $BASE/projects/$PID/render -d '{"confirm": true}' > /dev/null

# 4. tunggu final.mp4 lalu unduh
until curl -s "${AUTH[@]}" $BASE/projects/$PID | jq -e '.files | index("final.mp4")' > /dev/null; do sleep 10; done
curl -s -H "Authorization: Bearer $TOKEN" -o bersih-bersih.mp4 $BASE/projects/$PID/files/final.mp4
```

### Python (requests)

```python
import time
import requests

BASE = "https://video.example.com/api"
S = requests.Session()
S.headers["Authorization"] = "Bearer sav_xxxxxxxx"


def call(method, path, **kw):
    r = S.request(method, BASE + path, timeout=60, **kw)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.json().get('error')}")
    return r.json()


def wait_idle(pid, every=10):
    """Tunggu sampai tidak ada job utama; kembalikan detail project terakhir."""
    while True:
        p = call("GET", f"/projects/{pid}")
        job = p["active_job"]
        if job is None:
            return p
        print(f"{job['kind']}: {job['progress']:.0%} — {job['message']}")
        time.sleep(every)


project = call("POST", "/projects", json={
    "prompt": "Video lagu anak 30 detik tentang bersih-bersih kamar",
    "preset": "shorts", "target_seconds": 30, "profile_id": 1})
pid = project["id"]

call("POST", f"/projects/{pid}/plan")
p = wait_idle(pid, every=5)
print(len(p["scenes"]), "scene;", p["options"]["bible_character"])

print(call("POST", f"/projects/{pid}/render", json={})["estimate"])
call("POST", f"/projects/{pid}/render", json={"confirm": True})
p = wait_idle(pid)

last = p["jobs"][0]
if last["status"] != "succeeded":
    raise SystemExit(f"render {last['status']}: {last['message']}")  # bisa dilanjutkan: render confirm lagi
with open("video.mp4", "wb") as f:
    f.write(S.get(f"{BASE}/projects/{pid}/files/final.mp4", timeout=300).content)
```

## 7. Tips integrasi

- **Mulai dari video pendek** (15–30 dtk) untuk menguji prompt; video panjang = banyak clip,
  lama dan mahal.
- **Konsistensi karakter:** cek/ubah `options.bible_*` setelah plan, sebelum render.
  Jangan sebut nama karakter/studio terkenal di prompt — model video menolak (hak cipta).
- **Ganti musik/subtitle/transisi** cukup `PATCH` options lalu `compose` — tidak memakai
  kredit video.
- **Preview cepat** selama render panjang: `POST /projects/{id}/preview`, pantau
  `preview_job`, lalu unduh `preview.mp4`.
- **Bot WA:** simpan `project_id` per percakapan, polling di background, kirim
  `final.mp4` saat `files` berisi `final.mp4`; tampilkan `message` job saat gagal
  (pesannya aman untuk pengguna, tanpa detail internal).
