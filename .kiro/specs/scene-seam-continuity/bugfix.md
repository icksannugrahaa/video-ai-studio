# Bugfix: picture changes at seams between continuous scenes

Status: not started. Written before implementation.

## Current behavior

- WHEN a scene with `continues` is generated from the previous clip's last frame,
  the first frames of the new clip can show a different picture.
- WHEN that happens, the seam is visible in the final video even after colour
  matching, because colour gain cannot correct a different picture.
- WHEN a seam gap stays above `media.SEAM_BREAK` after one retake, the render hides
  it with a full crossfade instead of fixing it.

The root cause is not confirmed. Video models re-render the seed frame, but the
router or model may also treat the seed as a reference image instead of a first
frame. `client.py` sends the seed as the `image` field of the generation request.

## Expected behavior

- WHEN a clip is generated with a seed, THE system SHALL record how the provider
  used that seed, when the provider reports it.
- WHEN a continuous scene is generated, its first frame SHALL match the seed frame
  closely enough that `media.seam_gap` is at or below `media.SEAM_BREAK`.
- WHEN a seam still exceeds `media.SEAM_BREAK` after the retake, THE system SHALL
  show that on the scene so the user can decide whether to regenerate it.

## Unchanged behavior

- Scenes without `continues` SHALL NOT receive a seed.
- A scene SHALL be retaken at most once automatically, because each clip costs
  credits.
- Finished scenes SHALL still be skipped when a render resumes.
- Colour matching SHALL stay capped by `GAIN_LIMIT`.
- Renders SHALL still work when ffmpeg has no `xfade` filter.
- Logs SHALL NOT contain API keys, tokens, or seed image data.
