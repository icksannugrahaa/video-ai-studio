"""Platform presets: aspect ratio, max length and subtitle style.

Resolution is derived from ``SAV_RENDER_WIDTH`` (the *short* side, default
720) so the phone CPU renders 720p unless the operator raises it.
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "tiktok": {"label": "TikTok", "aspect": "9:16", "max_seconds": 600, "subtitle": "bold_center"},
    "reels": {"label": "Instagram Reels", "aspect": "9:16", "max_seconds": 180, "subtitle": "bold_center"},
    "shorts": {"label": "YouTube Shorts", "aspect": "9:16", "max_seconds": 180, "subtitle": "bold_center"},
    "youtube": {"label": "YouTube", "aspect": "16:9", "max_seconds": 3600, "subtitle": "bottom"},
    "facebook": {"label": "Facebook (1:1)", "aspect": "1:1", "max_seconds": 600, "subtitle": "bottom"},
    "instagram": {"label": "Instagram Feed (4:5)", "aspect": "4:5", "max_seconds": 60, "subtitle": "bottom"},
    "x": {"label": "X / Twitter", "aspect": "16:9", "max_seconds": 140, "subtitle": "bottom"},
}

# Video models only accept these aspect ratios; 4:5 renders from a 1:1 clip.
MODEL_ASPECT = {"9:16": "9:16", "16:9": "16:9", "1:1": "1:1", "4:5": "1:1"}


def _even(value: float) -> int:
    return int(round(value / 2.0)) * 2


def resolve(preset_id: str, short_side: int = 720) -> dict:
    """Preset dict with ``width``/``height`` computed for ``short_side``."""
    if preset_id not in PRESETS:
        raise ValueError(f"preset tidak dikenal: {preset_id}")
    preset = dict(PRESETS[preset_id], id=preset_id)
    w_ratio, h_ratio = (int(x) for x in preset["aspect"].split(":"))
    if w_ratio >= h_ratio:
        height = short_side
        width = _even(short_side * w_ratio / h_ratio)
    else:
        width = short_side
        height = _even(short_side * h_ratio / w_ratio)
    preset.update(width=width, height=height, model_aspect=MODEL_ASPECT[preset["aspect"]])
    return preset


def public_list(short_side: int = 720) -> list[dict]:
    return [resolve(pid, short_side) for pid in PRESETS]
