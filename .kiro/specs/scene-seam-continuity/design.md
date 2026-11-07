# Design: scene seam continuity

## Current flow

1. `Engine` extracts the previous clip's last frame with `media.last_frame_png`.
2. `_generate_one` passes that frame as `seed`, and `client.py` sends it as `image`.
3. `_retake_broken` measures `media.seam_gap` and retakes the clip once if the gap
   is above `media.SEAM_BREAK`, keeping the closer result.
4. `_seam_gains` corrects colour along a chain of continuous scenes.
5. `scene_transitions` uses a short dissolve on good seams and a full crossfade on
   broken seams.

## Step 1: find the cause

Measure before changing behavior:

- Read the router's video adapter to see how it maps `image` for the selected model.
- Generate one seeded clip and compare its first frame with the seed using
  `media.seam_gap`.
- Record the outcome in this file before choosing the fix below.

## Step 2: choose the fix

| Finding | Fix |
| --- | --- |
| The router sends the seed as a reference image | Send it as a first frame, using the provider's supported field |
| The model supports no first-frame mode | Mark the seam as unsupported and show that on the scene |
| The seed is used, but the model drifts | Keep the retake and show the remaining gap on the scene |

## Error handling

A failed measurement or retake must not fail the render. The saved clip stays in
place and the failure is logged without request data.

## Testing

- Unit tests use a fake provider client, so tests never spend credits.
- ffmpeg tests use synthetic clips with a known first-frame difference.
- Live clip generation is a manual check, because it costs credits.
