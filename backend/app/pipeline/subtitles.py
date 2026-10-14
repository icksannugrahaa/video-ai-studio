"""Subtitle cues from narration timings → SRT + ASS (burned in by ffmpeg).

Timing comes from per-sentence TTS durations, so cues match the voice
exactly. ``bold_center`` (TikTok/Reels/Shorts) shows short, big, outlined
chunks; ``bottom`` (YouTube/FB/X) shows classic two-line captions.
"""

from __future__ import annotations

from app.pipeline.text import chunk_cue, wrap_lines

STYLES = {
    "bold_center": {"max_words": 4, "wrap": 18, "size": 0.058, "margin": 0.24, "outline": 4, "bold": -1},
    "bottom": {"max_words": 12, "wrap": 42, "size": 0.045, "margin": 0.07, "outline": 2, "bold": 0},
}


def build_cues(scene_timings: list[dict], style: str) -> list[tuple[float, float, str]]:
    """``scene_timings``: ``[{offset, sentences: [{text, start, end}]}]`` with
    sentence times relative to the scene start. Returns absolute cues."""
    max_words = STYLES[style]["max_words"]
    cues: list[tuple[float, float, str]] = []
    for scene in scene_timings:
        offset = float(scene.get("offset") or 0.0)
        for sentence in scene.get("sentences") or []:
            cues.extend(chunk_cue(sentence["text"], offset + sentence["start"], offset + sentence["end"], max_words))
    return cues


def _srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def to_srt(cues: list[tuple[float, float, str]], wrap: int = 42) -> str:
    blocks = []
    for i, (start, end, text) in enumerate(cues, 1):
        blocks.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{wrap_lines(text, wrap)}\n")
    return "\n".join(blocks)


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def to_ass(cues: list[tuple[float, float, str]], style: str, width: int, height: int) -> str:
    cfg = STYLES[style]
    size = max(18, int(height * cfg["size"]))
    margin_v = int(height * cfg["margin"])
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,{cfg['bold']},0,0,0,"
        f"100,100,0,0,1,{cfg['outline']},0,2,{int(width * 0.06)},{int(width * 0.06)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{_ass_escape(wrap_lines(t, cfg['wrap']))}"
        for s, e, t in cues
    ]
    return header + "\n".join(lines) + "\n"
