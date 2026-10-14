# sandroid-ai-video — MVP design

Status: approved in chat 2026-10-13. Author: Icksan Nugraha (with Claude).

## Goal

Create and edit short/long AI videos for social media (TikTok, Reels,
Shorts, Facebook, X) and YouTube from a prompt. Video models only produce a
few seconds per clip, so a video is planned as scenes, each scene is
generated as its own clip, and the clips are stitched into one video with
narration (TTS) and subtitles aligned on one timeline.

The app has no AI of its own: every user brings an **OpenAI-compatible
endpoint + API key** (normally the Sandroid AI Router, which exposes chat,
`/v1/videos/generations` with async jobs, `/v1/audio/speech`, and model
`kind` metadata in `/v1/models`).

## Decisions

| Topic | Decision |
|-------|----------|
| Stack | Python 3.10+ FastAPI + SQLite (WAL) + ffmpeg; React/Vite UI built to `ui/dist` and served by the backend |
| Users | Multi-user. First admin from `.env`; admin manages users; public registration off by default (setting) |
| Credentials | Per-user provider profiles (endpoint, API key encrypted with Fernet derived from `SECRET_KEY`, chosen models, voice, clip seconds) |
| API auth | Session cookie for the UI, `Authorization: Bearer <token>` (per-user API tokens, SHA-256 stored) for clients |
| Runtime | One PM2 process (uvicorn) on the PRoot phone server; background worker thread inside it |
| Render | 720p default, 30 fps, libx264 `veryfast`, one ffmpeg render at a time (phone CPU) |

## MVP scope

In: prompt → storyboard (LLM) → per-scene clip generation (async, optional
continuity from the previous clip's last frame) → narration TTS per sentence →
subtitles (burned ASS + `.srt`) → uploaded background music with ducking →
platform presets → export. Editing: edit storyboard by hand, regenerate one
scene, or **edit by prompt** (LLM rewrites the storyboard; only changed scenes
are regenerated).

Music (added 2026-10-14): the planner also writes a `music_prompt` (English,
full video length, timestamped structure, instrumental). Mode per project:
`none` / `external` (default — user copies the prompt to Gemini web, which
renders >1 min tracks, and uploads the file) / `generate` (reserved for a
provider music API). Music can be swapped any time: `POST /projects/{id}/compose`
re-mixes the final video without generating clips; music fades in 0.5 s / out
2 s and loops if shorter than the video. `POST /projects/{id}/music-prompt`
rewrites the brief synchronously (works during a render).

Music style: `instrumental` (backsound under the TTS narration, ducked) or
`song` (added 2026-10-14). Song mode: `POST /projects/{id}/song` writes lyrics
from the scenes as LRC text (`[Section]` headers + `[m:ss] line`, timed inside
each scene's range) plus a Gemini prompt (style, vocal, exact length, timed
lyrics). At render the TTS step is skipped, the song plays at full volume and
the subtitles come from the LRC lines (user can nudge the timestamps after
hearing the song, then re-compose).

Out: provider music generation (waits for a paid Lyria tier), video-to-video editing,
auto-publishing, thumbnails, metadata/hashtags.

## Data model (SQLite)

- `users(id, username, password_hash, role[admin|user], active, created_at)`
- `api_tokens(id, user_id, name, token_hash, prefix, created_at, last_used_at)`
- `settings(key, value)` — `registration_open`
- `profiles(id, user_id, name, base_url, api_key_enc, chat_model, video_model,
  tts_model, tts_voice, clip_seconds, created_at)`
- `projects(id, user_id, profile_id, title, prompt, preset, target_seconds,
  language, options_json, status, created_at, updated_at)`
- `scenes(id, project_id, idx, visual_prompt, narration, duration, version,
  clip_status, clip_file, clip_error, clip_version, narration_file,
  narration_json)`
- `jobs(id, user_id, project_id, kind[plan|render|edit|regenerate], status,
  progress, message, payload_json, result_json, created_at, updated_at)`

Every row is scoped by `user_id` (projects/scenes/jobs through their project).

## Pipeline

1. **Plan** — chat model returns JSON `{title, scenes:[{visual_prompt,
   narration, duration}]}`; durations are clamped to the profile's clip length
   and the preset's max length; the total aims at `target_seconds`.
2. **Clips** — `POST {endpoint}/v1/videos/generations` with `async: true`
   (router job → poll `/v1/media/jobs/{id}` → `/content`); providers without
   jobs fall back to a synchronous call. Continuity: last frame of clip N is
   sent as `image` for clip N+1.
3. **Narration** — TTS per sentence (`/v1/audio/speech`, wav), durations from
   ffprobe; scene narration = sentences joined; cue timings are exact.
4. **Subtitles** — cues from narration timings (+ scene offsets); TikTok-style
   presets use short, centred, bold cues; YouTube uses bottom two-line cues.
5. **Compose** — per scene: scale/crop to the preset, hold the last frame when
   narration is longer than the clip; concat; narration track aligned to scene
   starts; music looped/trimmed with sidechain ducking; loudness −14 LUFS;
   subtitles burned; outputs `final.mp4`, `final.srt`.
6. **Edit by prompt** — LLM gets the storyboard + instruction, returns a new
   storyboard; scenes whose visual prompt or duration changed get a new
   version (re-generated); narration changes only redo TTS; then re-compose.

State lives in the DB per scene/step, so a render resumes after a PM2 restart
(finished scenes are skipped). Clip generation retries twice per scene.

## API (all under `/api`, JSON)

- auth: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`,
  `POST /auth/register`, `GET|POST /auth/tokens`, `DELETE /auth/tokens/{id}`
- users (admin): `GET|POST /users`, `PATCH /users/{id}`, `GET|PUT /settings`
- profiles: `GET|POST /profiles`, `PATCH|DELETE /profiles/{id}`,
  `GET /profiles/{id}/models`
- presets: `GET /presets`
- projects: `GET|POST /projects`, `GET|PATCH|DELETE /projects/{id}`,
  `PUT /projects/{id}/scenes`, `POST /projects/{id}/plan|render|edit`,
  `POST /projects/{id}/scenes/{idx}/regenerate`, `POST /projects/{id}/music`,
  `GET /projects/{id}/files/{name}`
- jobs: `GET /projects/{id}/jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`

## Testing

pytest with a fake provider client; real ffmpeg tests on synthetic lavfi
clips (skipped without ffmpeg); API tests including cross-user isolation.

## Build phases

1. Skeleton, config, DB, auth/users/tokens, profiles (+ encryption)
2. Provider client (chat, models, video async/sync, TTS)
3. Pipeline: presets, planner, narration, subtitles, media (ffmpeg), compose
4. Worker + projects/jobs/files API, resume
5. React UI
6. Deploy (PM2 ecosystem, install script, README)
