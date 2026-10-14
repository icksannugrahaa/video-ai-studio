"""Storyboard planning and prompt-based editing with the user's chat model.

The LLM returns JSON ``{"title", "bible", "scenes": [{"visual_prompt",
"continues", "narration", "duration"}]}``. The bible (character, world,
style) is stored once and prepended verbatim to every clip prompt by
:func:`clip_prompt`, so separately generated clips share one character and
one place; scene prompts only describe the shot. Visual prompts are English
(video models follow English best); narration is in the project language.
"""

from __future__ import annotations

import json
import re

WORDS_PER_SECOND = 2.4  # comfortable narration pace (id/en)

_SYSTEM = """You are a short-form video director. Plan a video as a sequence of scenes.
Each scene becomes ONE separately generated AI video clip. Clips are generated independently, so consistency
comes only from a fixed "bible" that the app prepends, word for word, to every clip prompt:

"bible" (English):
- "character": the main character, 40-80 words, written once and never varied. Concrete, unambiguous traits:
  species/type, age, body shape and size, fur/skin/hair colour and exact pattern, eye colour, one or two unique
  markings, clothing/accessory with exact colour, pattern and where it is worn. Make it ORIGINAL and clearly
  different from famous copyrighted characters (e.g. Garfield, Disney/Pixar/DreamWorks characters).
  If the story has no single main character, describe the recurring subject instead.
- "world": the ONE place the whole story happens in, 40-80 words: city/region and country, era, architecture,
  building materials, colour palette, vehicles, signage language, vegetation, climate. Every scene stays inside
  this world: if the story is in Jakarta, every street, shop, train and skyline must look like Jakarta, Indonesia
  (Indonesian-language signs, local vehicles) — never like another country. Describe only the general look of the
  place; do NOT list story props or room-specific objects here (it is pasted into every shot, so a sink or a broom
  named here would appear in every room). Props belong in the visual_prompt of the scenes that need them.
- "style": one line for the visual style and rendering (e.g. "stylized 3D animated feature film look, soft global
  illumination, warm colour grading, shallow depth of field"). Never name studios, artists or franchises.

"scenes": each scene has
- "visual_prompt": English, ONLY what is specific to this shot: the exact spot inside the world, what the character
  does, camera shot size and movement, time of day and lighting. Refer to the character as "the character"; do
  NOT re-describe the character, the world or the style (the bible is added automatically). Keep the time of day
  and weather progressing logically from scene to scene. No on-screen text, captions, logos or watermarks.
- "continues": true when this shot continues the previous one in the same place and moment (the app then starts
  this clip from the last frame of the previous clip), false when the location or time changes. Group the story
  into short sequences of 2-3 continuous shots per location; the first scene is always false.
- "narration": voice-over spoken during the scene, in {language}. At most {words} words per scene
  ({wps} words per second of duration). May be empty for purely visual moments.
- "duration": seconds, integer between {min_s} and {max_s}.
Total duration should be close to {target} seconds (never above {limit}). Aspect ratio: {aspect}.
Also write "music_prompt": an English prompt for an AI music generator (background score for this video):
genre, mood, tempo in BPM, main instruments, "instrumental, no vocals", the exact total length of the video
(e.g. "full length 3:00"), and a short structure that follows the story with timestamps (e.g. "0:00-0:20 calm
intro, 0:20-1:30 playful build, ... 2:45-3:00 gentle outro with a soft fade-out ending").
Reply with JSON only, no prose, no markdown:
{{"title": "...", "music_prompt": "...", "bible": {{"character": "...", "world": "...", "style": "..."}},
"scenes": [{{"visual_prompt": "...", "continues": false, "narration": "...", "duration": 5}}]}}"""

_EDIT = """You edit an existing video storyboard. Apply the user's instruction and return the COMPLETE
updated storyboard in the same JSON format, including "bible". Keep unchanged scenes exactly as they are (same
text and same "continues"), so only the scenes that really change get regenerated. Keep the bible word for word
unless the instruction explicitly changes the character, the world or the style. Same rules as before:
visual_prompt in English without re-describing the bible, narration in {language}, duration integer between
{min_s} and {max_s}, JSON only."""

BIBLE_KEYS = ("character", "world", "style")


def clip_prompt(options: dict, visual_prompt: str) -> str:
    """Final prompt for one clip: fixed bible + the shot. Projects planned
    before the bible existed have empty bible fields and keep their prompt."""
    style = (options.get("bible_style") or "").strip().rstrip(".")
    character = (options.get("bible_character") or "").strip().rstrip(".")
    world = (options.get("bible_world") or "").strip().rstrip(".")
    shot = (visual_prompt or "").strip()
    if not (style or character or world):
        return shot
    parts = []
    if style:
        parts.append(f"{style}.")
    if character:
        parts.append(f"Main character, identical in every shot: {character}.")
    if world:
        parts.append(f"Setting: {world}.")
    parts.append(f"Shot: {shot}")
    parts.append("No on-screen text, captions or watermarks.")
    return " ".join(parts)


def has_bible(options: dict) -> bool:
    return any((options.get(f"bible_{key}") or "").strip() for key in BIBLE_KEYS)


class PlanError(ValueError):
    pass


def extract_json(text: str) -> dict:
    """Parse the first JSON object in an LLM reply (tolerates code fences/prose)."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise PlanError("model tidak mengembalikan JSON storyboard")
    try:
        data = json.loads(cleaned[start:end + 1])
    except ValueError as exc:
        raise PlanError("JSON storyboard tidak valid") from exc
    if not isinstance(data, dict):
        raise PlanError("JSON storyboard tidak valid")
    return data


def normalize(data: dict, *, clip_seconds: int, limit_seconds: int) -> dict:
    """Clamp durations, drop empty scenes, and stop before the preset limit."""
    min_s = min(3, clip_seconds)
    scenes, total = [], 0.0
    for raw in data.get("scenes") or []:
        if not isinstance(raw, dict):
            continue
        visual = str(raw.get("visual_prompt") or "").strip()
        if not visual:
            continue
        try:
            seconds = float(raw.get("duration") or clip_seconds)
        except (TypeError, ValueError):
            seconds = float(clip_seconds)
        seconds = float(max(min_s, min(clip_seconds, round(seconds))))
        if total + seconds > limit_seconds:
            break
        scenes.append({"visual_prompt": visual, "narration": str(raw.get("narration") or "").strip(),
                       "duration": seconds, "continues": bool(scenes) and raw.get("continues") is True})
        total += seconds
    if not scenes:
        raise PlanError("storyboard kosong")
    raw_bible = data.get("bible") if isinstance(data.get("bible"), dict) else {}
    bible = {key: str(raw_bible.get(key) or "").strip()[:1200] for key in BIBLE_KEYS}
    return {"title": str(data.get("title") or "").strip()[:120], "scenes": scenes, "bible": bible,
            "music_prompt": str(data.get("music_prompt") or "").strip()[:2000]}


def _rules(language: str, clip_seconds: int, target: int, limit: int, aspect: str) -> dict:
    return {
        "language": language, "min_s": min(3, clip_seconds), "max_s": clip_seconds,
        "words": int(clip_seconds * WORDS_PER_SECOND), "wps": WORDS_PER_SECOND,
        "target": target, "limit": limit, "aspect": aspect,
    }


_REPAIR = ("Convert your previous answer into the required JSON only — no prose, no markdown. "
           'Format: {"title": "...", "bible": {"character": "...", "world": "...", "style": "..."}, '
           '"scenes": [{"visual_prompt": "...", "continues": false, "narration": "...", "duration": 5}]}')


def _ask_json(client, model: str, instructions: str, request: str, temperature: float) -> dict:
    """Ask for storyboard JSON with the rules inside the *user* message.

    Some gateways drop or replace client system prompts (the CodeBuddy
    transport does), so rules in ``system`` never reach the model. One repair
    turn converts a prose reply into JSON before giving up.
    """
    messages = [{"role": "user", "content": instructions + "\n\n---\n\n" + request}]
    reply = client.chat(model, messages, temperature=temperature)
    try:
        return extract_json(reply)
    except PlanError:
        messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": _REPAIR}]
        return extract_json(client.chat(model, messages, temperature=0.2))


def plan_storyboard(client, model: str, *, prompt: str, language: str, clip_seconds: int,
                    target_seconds: int, limit_seconds: int, aspect: str) -> dict:
    rules = _rules(language, clip_seconds, min(target_seconds, limit_seconds), limit_seconds, aspect)
    data = _ask_json(client, model, _SYSTEM.format(**rules), "Video idea: " + prompt, temperature=0.7)
    return normalize(data, clip_seconds=clip_seconds, limit_seconds=limit_seconds)


def edit_storyboard(client, model: str, *, storyboard: dict, instruction: str, language: str,
                    clip_seconds: int, limit_seconds: int, aspect: str) -> dict:
    rules = _rules(language, clip_seconds, limit_seconds, limit_seconds, aspect)
    instructions = _SYSTEM.format(**rules) + "\n\n" + _EDIT.format(**rules)
    request = ("Current storyboard:\n" + json.dumps(storyboard, ensure_ascii=False)
               + "\n\nInstruction: " + instruction)
    data = _ask_json(client, model, instructions, request, temperature=0.4)
    return normalize(data, clip_seconds=clip_seconds, limit_seconds=limit_seconds)


_MUSIC = """You write prompts for AI music generators (Gemini / Lyria, Suno, Udio).
Write ONE English prompt for the instrumental background music of the video below: genre, mood, tempo in BPM,
main instruments, "instrumental, no vocals", the exact full length {length} ({total} seconds), and a short
structure with timestamps that follows the story beats, ending with a soft fade-out (no abrupt ending).
It must sit under a voice-over, so keep it uncluttered. {hint}
Reply with JSON only: {{"music_prompt": "..."}}"""


def music_prompt(client, model: str, *, title: str, scenes: list[dict], hint: str = "") -> str:
    """Re-create only the music brief from the current storyboard."""
    total = int(round(sum(float(s["duration"]) for s in scenes)))
    outline, cursor = [], 0.0
    for scene in scenes:
        outline.append(f"{cursor:.0f}-{cursor + float(scene['duration']):.0f}s: {scene['visual_prompt'][:160]}")
        cursor += float(scene["duration"])
    request = (f"Video title: {title or '-'}\nScenes:\n" + "\n".join(outline))
    instructions = _MUSIC.format(total=total, length=f"{total // 60}:{total % 60:02d}", hint=("Extra direction from the user: " + hint) if hint else "")
    data = _ask_json(client, model, instructions, request, temperature=0.7)
    prompt = str(data.get("music_prompt") or "").strip()
    if not prompt:
        raise PlanError("model tidak mengembalikan prompt musik")
    return prompt[:2000]


_SONG = """You are a songwriter for short videos. Write an original song whose lyrics follow the video scene by scene.
Lyrics language: {language}. Total length {length} ({total} seconds). Group scenes into sections
(e.g. Intro (instrumental), Verse 1, Chorus, Verse 2, Chorus, Bridge, Final Chorus, Outro). The chorus may repeat.
Every lyric line has "t": the second (from 0) it starts, placed inside the time range of the scenes it describes,
at least 2.5 seconds apart, lines short and singable (max 9 words), with rhymes. Leave the last 5-8 seconds
for an instrumental outro. {hint}
"style": English music style for the generator (genre, mood, tempo BPM, instruments).
"vocal": English vocal description (e.g. "cheerful young female vocal").
Reply with JSON only:
{{"style": "...", "vocal": "...", "sections": [{{"name": "Verse 1", "lines": [{{"t": 4, "text": "..."}}]}}]}}"""

_LRC_RE = re.compile(r"^\[(\d+):(\d{1,2}(?:\.\d+)?)\]\s*(.*)$")


def _clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def song_plan(client, model: str, *, title: str, scenes: list[dict], language: str, hint: str = "") -> dict:
    """Lyrics (timed to the scenes) + a ready-to-paste song prompt.

    Returns ``{"lyrics": "<LRC text>", "music_prompt": "..."}``. The LRC text
    keeps section headers (``[Verse 1]``) and timed lines (``[0:12] …``); it is
    what the user edits and what the subtitles are built from.
    """
    total = int(round(sum(float(s["duration"]) for s in scenes)))
    outline, cursor = [], 0.0
    for scene in scenes:
        end = cursor + float(scene["duration"])
        outline.append(f"{cursor:.0f}-{end:.0f}s: {scene.get('narration') or scene['visual_prompt'][:160]}")
        cursor = end
    instructions = _SONG.format(language=language, length=_clock(total), total=total,
                                hint=("Extra direction from the user: " + hint) if hint else "")
    data = _ask_json(client, model, instructions, f"Video title: {title or '-'}\nScenes:\n" + "\n".join(outline),
                     temperature=0.8)
    blocks: list[str] = []
    last_t = -1.0
    for section in data.get("sections") or []:
        lines = []
        for line in section.get("lines") or []:
            try:
                t = float(line.get("t"))
            except (TypeError, ValueError, AttributeError):
                continue
            text = str(line.get("text") or "").strip()
            if not text or t <= last_t or t >= total:
                continue
            last_t = t
            lines.append(f"[{_clock(t)}] {text}")
        name = str(section.get("name") or "").strip()
        if lines or "intro" in name.lower() or "outro" in name.lower():
            blocks.append("\n".join([f"[{name}]" if name else "", *lines]).strip())
    lyrics = "\n\n".join(b for b in blocks if b)
    if not re.search(r"^\[\d+:\d", lyrics, re.M):
        raise PlanError("model tidak mengembalikan lirik bertimestamp")
    return {"lyrics": lyrics[:6000], "music_prompt": song_prompt(
        style=str(data.get("style") or "").strip(), vocal=str(data.get("vocal") or "").strip(),
        lyrics=lyrics, total=total)}


def song_prompt(*, style: str, vocal: str, lyrics: str, total: int) -> str:
    """Prompt for Gemini/Suno: style + vocal + exact length + timestamped lyrics."""
    head = ", ".join(p for p in (style, vocal) if p)
    return (f"{head}. Full song, exact total length {_clock(total)} ({total} seconds), sing each lyric line at "
            f"its timestamp, instrumental intro/outro where marked, gentle fade-out ending.\n\nLyrics:\n{lyrics}")[:6000]


def parse_lyrics(lyrics: str, total: float, max_line: float = 6.0) -> list[tuple[float, float, str]]:
    """Timed lines from LRC text → cues ``(start, end, text)``; a cue lasts
    until the next line (max ``max_line`` seconds). Section headers are skipped."""
    timed = []
    for raw in (lyrics or "").splitlines():
        match = _LRC_RE.match(raw.strip())
        if match and match.group(3).strip():
            timed.append((int(match.group(1)) * 60 + float(match.group(2)), match.group(3).strip()))
    timed.sort(key=lambda item: item[0])
    cues = []
    for i, (start, text) in enumerate(timed):
        if start >= total:
            break
        nxt = timed[i + 1][0] if i + 1 < len(timed) else total
        cues.append((round(start, 3), round(min(nxt, start + max_line, total), 3), text))
    return cues
