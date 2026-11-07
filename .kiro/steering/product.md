---
inclusion: always
---

# Product

Video AI Studio creates and edits AI videos for TikTok, Reels, Shorts, Facebook,
X, and YouTube from a single prompt. Video models only produce a few seconds per
clip, so a video is planned as scenes, each scene is generated as a clip, and the
clips are joined with narration (TTS), subtitles, and optional music on one
timeline.

- The app has no AI of its own. Each user adds a provider profile: an
  OpenAI-compatible endpoint and an API key, encrypted with Fernet from
  `SECRET_KEY`.
- The app is multi-user. All data is scoped by `user_id`. The first admin comes
  from `.env`.
- Subtitle timing comes from the TTS duration of each sentence, not from STT.
- Render state is stored per scene and step in the database. A render resumes
  after a PM2 restart and skips finished scenes.

The full design is in `docs/specs/2026-10-13-mvp-design.md`.
