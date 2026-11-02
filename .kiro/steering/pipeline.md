---
inclusion: fileMatch
fileMatchPattern: ["backend/app/engine.py", "backend/app/pipeline/**/*.py", "backend/app/providers/**/*.py"]
---

# Video pipeline

- Clip generation costs credits. Do not add automatic retries or regeneration
  without a limit, and do not regenerate finished scenes unless their inputs changed.
- Tests must use the fake provider client, not a live provider.
- Keep render state in the database per scene and step, so a render can resume.
- Measure problems on real clips with the helpers in `media.py` before changing
  thresholds such as `SEAM_BREAK` or `GAIN_LIMIT`.
- Keep ffmpeg 4.4 compatibility, and check optional filters with
  `media.has_filter()`.
