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
MIN_CLIP_SECONDS = 4

_SYSTEM = """You are a short-form video director. Plan a video as a sequence of scenes.
Each scene becomes ONE separately generated AI video clip. Clips are generated independently, so consistency
comes only from a fixed "bible" that the app prepends, word for word, to every clip prompt.

The idea may be one short, plain sentence: treat it as a client brief and direct it like a professional production.
Keep everything the user asked for exactly (characters, topic, place, style, language); decide everything they left
open: audience, tone, the hook of the first seconds, how the video builds, and how it ends. The result must feel
filmed and edited by a professional crew, with every shot having a reason to exist.

First turn the idea — however short or vague — into a concrete "concept" (English) and build every scene on it:
- "promise": the one thing the viewer must get from this video, as the title would promise it (e.g. "counting
  from 1 to 5 with fruit", "how a seed grows into a plant", "a cat's funny morning routine").
- "beats": the ordered steps that deliver the promise, one per scene, with no filler. For learning videos pick a
  clear, age-appropriate scope (e.g. counting 1-5, not 1-100) and teach it step by step with repetition: show
  it, say it, then recap it at the end.
Make the promise VISIBLE in every scene, not only spoken: the visual_prompt names the exact objects and how many
there are. Show a count as a state of the scene, because video models render that reliably: exactly that many
objects are on screen (counting 3 = exactly three apples on the table), and in a continuing shot the teacher or
character adds just one more object. NEVER ask for a number of raised fingers, hand signs, or touching an object
by its position ("the third from the left"): video models get these wrong and usually show an open waving hand.
Keep counted objects few (at most 5), large, identical and clearly separated so the video model can render them;
never rely on on-screen numbers or text.
The narration says exactly what is shown at that moment (the same number, the same object).
At most one intro scene and one closing/recap scene; every other scene delivers a beat.
One clear main action per scene (4-5 seconds is too short for more), described with concrete body movement.

"bible" (English):
- "character": the main character, 40-80 words — or, when the idea asks for several characters, a cast of 2-3,
  each with a name and 30-50 words of clearly different traits (refer to them by name in the scenes) — written
  once and never varied. Concrete, unambiguous traits:
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
- "style": one line that fixes the look of the whole video: the medium the user asked for (if they named none, choose
  what suits the idea), the lens look, lighting approach, colour palette and grade, and surface texture (e.g. live
  action: "documentary look on a 35mm lens, natural window light, muted warm grade, real skin texture, subtle film
  grain"; animation: "stylized 3D animated feature look, soft global illumination, warm pastel grade, shallow depth
  of field"). Never name studios, artists or franchises. No empty hype words ("masterpiece", "8K", "ultra realistic").

"scenes": each scene has
- "visual_prompt": English, 60-100 words, ONLY what is specific to this shot, in exactly this form, because each clip
  is generated without seeing the others and must be told everything it needs:
  "<exact spot inside the world; shot size and lens feel; one camera behaviour with its speed (locked-off, slow
  dolly, gentle handheld); the light and where it comes from>. START: <the first frame: where each person is, what
  their hands hold, and every story object with its exact count and position>. ACTION: <one physical action told
  from its first moment to its last (how the body moves and how much, e.g. "leans forward, lifts the cup with both
  hands, sips, then smiles"), including small natural behaviour such as a glance or a breath, and what stays
  untouched>. END: <the last frame, in the same terms as START>."
  Counted objects: START says "exactly three large red apples in a row on the table and no other apples"; ACTION brings
  exactly one more from a named place and says the others do not move; END says "exactly four ...". The count in END must
  equal the count in START plus what ACTION adds. The placing is done by the third second of the clip and the hands
  then leave the objects alone until END. The named place is a story object too: put it on the front edge of the same
  surface, closest to the camera with nobody in front of it, never behind a person or at the edge of the frame, always
  written with its full location (never a shorthand like "right-end basket"), and START and END of this shot and of every later shot in
  the sequence state where it is and how many objects are left in it (e.g. "exactly three large red apples in a row and
  exactly two more in a basket on the front right corner of the table, no other apples"), so it never vanishes and later shots take
  from the same spot. ACTION says the hand takes each object from it ("takes one apple from the basket, places it ...")
  so nothing appears from nowhere, and END is the pose ACTION finishes in. An emptied container is written as empty, never as "exactly 0". ACTION names each object's spot
  from the object before it ("directly to the right of the third apple"), never "the next empty spot". The first shot of
  a sequence gives every person's place on screen and nobody sits or stands between the camera and the objects (e.g. one
  child at each end of the table, turned three-quarters toward the camera). The first shot of a counting sequence leaves visible empty space, in the
  frame and on the surface, for the final count (e.g. a long table with the row starting at its far left), and ACTION
  names the free spot for each new object. Vary shot sizes between sequences
  (wide to establish, then medium, then a close detail) so the edit has rhythm, unless a rule below fixes the camera.
  Refer to the character as "the character" (or
  the cast by their names); do NOT re-describe the character, the world or the style (the bible is added automatically). Keep the time of day
  and weather progressing logically from scene to scene. No on-screen text, captions, logos or watermarks.
- "continues": true when this shot continues the previous one in the same place and moment (the app then starts
  this clip from the last frame of the previous clip), false when the location or time changes. Group the story
  into sequences of continuous shots per location; the first scene is always false. A continuing shot starts
  exactly where the previous one ended: its START repeats the previous END word for word, so keep its shot size, camera position and the characters' screen
  positions. Steps of one lesson or song at the same spot, including the closing shot, which shows the objects exactly
  as the last step left them, all stay continuous with a fixed camera ("the camera
  stays still"): no close-ups, no zooms or push-ins and no view from the other side, which flip the room and push
  the objects out of frame.
- "narration": voice-over spoken during the scene, in {language}. At most {words} words per scene
  ({wps} words per second of duration). May be empty for purely visual moments.
- "duration": seconds, integer between {min_s} and {max_s}.
Total duration should be close to {target} seconds (never above {limit}). Aspect ratio: {aspect}.
Also write "music_prompt": an English prompt for an AI music generator (background score for this video):
genre, mood, tempo in BPM, main instruments, "instrumental, no vocals", the exact total length of the video
(e.g. "full length 3:00"), and a short structure that follows the story with timestamps (e.g. "0:00-0:20 calm
intro, 0:20-1:30 playful build, ... 2:45-3:00 gentle outro with a soft fade-out ending").
If the idea asks for a song, lyrics, a sing-along or movements to music, the narration of each scene is the sung
lyric for that scene instead of a voice-over: short rhythmic lines that carry the beat (the counting words, the
names), a repeated catchy chorus line, and the visual_prompt shows the character doing exactly what the words
say, moving on the beat. {song}
The title must state the promise (e.g. "Ayo Berhitung 1 sampai 5 dengan Apel"), in {language}.
Reply with JSON only, no prose, no markdown:
{{"title": "...", "concept": {{"promise": "...", "beats": ["..."]}}, "music_prompt": "...",
"bible": {{"character": "...", "world": "...", "style": "..."}},
"scenes": [{{"visual_prompt": "...", "continues": false, "narration": "...", "duration": 5}}]}}"""

_EDIT = """You edit an existing video storyboard. Apply the user's instruction and return the COMPLETE
updated storyboard in the same JSON format, including "concept" and "bible". Keep the concept's promise unless
the instruction changes what the video is about. Keep unchanged scenes exactly as they are (same
text and same "continues"), so only the scenes that really change get regenerated. Keep the bible word for word
unless the instruction explicitly changes the character, the world or the style. Same rules as before:
visual_prompt in English without re-describing the bible, narration in {language}, duration integer between
{min_s} and {max_s}, JSON only."""

BIBLE_KEYS = ("character", "world", "style")


# Added to every clip: what separates a filmed shot from typical AI video.
SHOT_CRAFT = ("Professional production: one continuous take with no cuts, believable weight and timing in every "
              "movement, smooth motivated camera work, steady light and exposure. Faces, hands and objects keep their "
              "shape from the first to the last frame, with no morphing or flicker, and the number of objects changes "
              "only by what the action itself adds or removes. Each object the action adds is brought in and placed once, "
              "never repeated, exactly at the spot the action names; a row only grows on the side the action says. After "
              "the last placing no further object enters the frame, none is stacked unless the shot says so, and the "
              "objects stay exactly as they are until the last frame. Every object and container named in the shot "
              "stays in view in its place.")
CAMERA_LOCK = ("The camera is fixed on a tripod: no pan, tilt, zoom, push-in, pull-back or drift; the walls, windows and "
               "table edges keep the same position in the frame from the first to the last frame.")
_STILL_CAMERA_RE = re.compile(r"\b(locked[- ]off|camera (?:stays )?still|fixed (?:camera|[\w-]* ?shot)|static camera)\b", re.I)
SEEDED_SHOT = ("Start exactly on the supplied image and continue it: same framing, camera side and characters' "
               "positions. Every object in the image is there from the first frame and stays in place; "
               "nothing disappears or resets.")


_SHOT_RE = re.compile(r"\bSTART:\s*.*?\s*(?=\bACTION:)", re.S)
_END_RE = re.compile(r"\bEND:\s*(.*)$", re.S)


_ACTION_RE = re.compile(r"\bACTION:\s*(.*?)\s*(?=\bEND:)", re.S)
_SOURCE_RE = re.compile(r"\b(?:lifts?|takes?|picks?|pulls?|grabs?|brings?|draws?)\b[^.;]*?\bfrom (?:(?:a|an|the) )?"
                        r"([a-z][a-z -]*?)( (?:at|on|in|beside|near|by|under|behind) [^,;.]+)?(?=[,;.]|$)", re.I)


def _is_placed(text: str, word: str) -> bool:
    """Whether the text says where the object is, not only that it exists."""
    return re.search(rf"\b{re.escape(word)}\b[^.;,]*\b(?:on|at|beside|near|under|behind)\b", text, re.I) is not None


def keep_sources(scenes: list[dict]) -> None:
    """A place the action takes objects from must stay in START and END of its
    sequence: left out of them, the model drops it mid clip and the next clip's
    seed frame no longer has it."""
    sources: dict[str, str] = {}
    for scene in scenes:
        if not scene.get("continues"):
            sources = {}
        text = scene["visual_prompt"]
        action, start = _ACTION_RE.search(text), _SHOT_RE.search(text)
        end = _END_RE.search(text)
        if not (action and start and end):
            continue
        for found in _SOURCE_RE.finditer(action.group(1)):
            sources.setdefault(found.group(1).split()[-1].lower(), f"{found.group(1)}{found.group(2) or ''}")
        for word, place in sources.items():
            spot = "" if " " in place else " on the front edge of the surface, closest to the camera with nobody in front of it"
            note = (f"The {place} stays in clear view{spot}, in the same spot, never hidden behind a person or out of "
                    "frame; what is still inside it is not counted above.")
            if not _is_placed(end.group(1), word):
                text = f"{text.rstrip()} {note}"
            if not _is_placed(start.group(0), word):
                text = f"{text[:start.end()].rstrip()} {note} {text[start.end():]}"
            start, end = _SHOT_RE.search(text), _END_RE.search(text)
        scene["visual_prompt"] = text


_NUMBERS = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split())}
_COUNT_RE = re.compile(r"\bexactly (\d+|" + "|".join(_NUMBERS) + r") (?:[a-z-]+ )*?([a-z]+s)\b", re.I)
_KEPT_RE = re.compile(r"\bThe ([a-z][a-z -]*?)(?: (?:at|on|in|beside|near|by|under|behind) [^;.]*?)? stays in clear view", re.I)
_LEFT_IN_RE = re.compile(r"\bexactly \w+(?: more)? in (?:(?:a|an|the) )?(?:[a-z-]+ )*?([a-z]+)\b"
                         r"(?=\s+(?:at|on|in|beside|near|by|under|behind)\b|[,;.]|$)"
                         r"|\b([a-z]+) empty\b", re.I)


def end_checks(visual_prompt: str) -> dict | None:
    """What a clip's last frame must show, read from the shot's END and ACTION;
    ``None`` when the shot promises nothing that can be counted or looked for."""
    end, action = _END_RE.search(visual_prompt), _ACTION_RE.search(visual_prompt)
    if not end:
        return None
    count = _COUNT_RE.search(end.group(1))
    words = [m.group(1).split()[-1].lower() for m in _SOURCE_RE.finditer(action.group(1))] if action else []
    words += [m.group(1).split()[-1].lower() for m in _KEPT_RE.finditer(end.group(1))]
    words += [(m.group(1) or m.group(2)).lower() for m in _LEFT_IN_RE.finditer(end.group(1))]
    number = count and (int(count.group(1)) if count.group(1).isdigit() else _NUMBERS[count.group(1).lower()])
    if not (count or words):
        return None
    return {"count": number or None, "noun": count.group(2).lower() if count else "", "visible": list(dict.fromkeys(words))}


def sequence_checks(scenes: list[dict], scene: dict) -> dict | None:
    """``end_checks`` plus the containers of the earlier shots of its sequence:
    they are still in the room even when this shot's wording does not mention them."""
    checks = end_checks(scene["visual_prompt"]) or {"count": None, "noun": "", "visible": []}
    ordered = sorted(scenes, key=lambda s: s["idx"])
    at = next(i for i, s in enumerate(ordered) if s["idx"] == scene["idx"])
    while at > 0 and ordered[at].get("continues"):
        at -= 1
        earlier = end_checks(ordered[at]["visual_prompt"])
        checks["visible"] += [w for w in (earlier["visible"] if earlier else []) if w not in checks["visible"]]
    return checks if checks["count"] or checks["visible"] else None


def end_question(checks: dict) -> str:
    """One frame at a time on purpose: seen live, the chat model reads a single
    frame reliably but misreads the same objects in a grid of frames."""
    asks, keys = ["Look at this single video frame."], []
    if checks["count"]:
        asks.append(f"Count the {checks['noun']} lying in view (not in a hand, not inside a container).")
        keys.append('"count":0')
    for word in checks["visible"]:
        asks.append(f"Is a {word} visible anywhere, even partly?")
    if checks["visible"]:
        keys.append('"visible":{' + ",".join(f'"{word}":false' for word in checks["visible"]) + "}")
    return " ".join(asks) + " Reply with JSON only: {" + ",".join(keys) + "}"


def end_problems(checks: dict, reply: dict) -> list[str]:
    """Differences between the promised end state and what was seen. A missing or
    malformed answer is no finding: only a clear mismatch may bill a retake."""
    problems = []
    seen = reply.get("count")
    if checks["count"] and isinstance(seen, int) and not isinstance(seen, bool) and seen != checks["count"]:
        problems.append(f"{checks['noun']} {seen}, seharusnya {checks['count']}")
    visible = reply.get("visible") if isinstance(reply.get("visible"), dict) else {}
    problems += [f"{word} tidak terlihat" for word in checks["visible"] if visible.get(word) is False]
    return problems


def link_shots(scenes: list[dict]) -> None:
    """Make every continuing shot start in the exact state the previous one ends
    in, so a lapse of the planner cannot lose an object between two clips."""
    for prev, scene in zip(scenes, scenes[1:]):
        end = _END_RE.search(prev["visual_prompt"])
        if scene.get("continues") and end and _SHOT_RE.search(scene["visual_prompt"]):
            scene["visual_prompt"] = _SHOT_RE.sub(lambda _: f"START: {end.group(1).strip()} ", scene["visual_prompt"], count=1)


def clip_prompt(options: dict, visual_prompt: str, sung: str = "", seeded: bool = False, previous: str = "") -> str:
    """Final prompt for one clip: fixed bible + the shot (+ in song mode what is
    sung during it, + for a seeded clip the order to continue its image and,
    when the shot does not spell out its START, what the previous shot showed).
    Projects planned before the bible existed have empty bible fields and keep
    their prompt."""
    style = (options.get("bible_style") or "").strip().rstrip(".")
    character = (options.get("bible_character") or "").strip().rstrip(".")
    world = (options.get("bible_world") or "").strip().rstrip(".")
    shot = (visual_prompt or "").strip()
    if not (style or character or world):
        return f"{shot} {sung}".strip()
    parts = []
    if style:
        parts.append(f"{style}.")
    if character:
        parts.append(f"Main character, identical in every shot: {character}.")
    if world:
        parts.append(f"Setting: {world}.")
    parts.append(f"Shot: {shot}")
    if seeded:
        if previous and "START:" not in shot:
            end = _END_RE.search(previous)
            parts.append(f"It continues directly from the previous shot, which showed: {(end.group(1) if end else previous).strip()}")
        parts.append(SEEDED_SHOT)
    if sung:
        parts.append(sung)
    if _STILL_CAMERA_RE.search(shot.split("START:")[0]):
        parts.append(CAMERA_LOCK)
    parts.append(SHOT_CRAFT)
    parts.append("No on-screen text, captions or watermarks.")
    return " ".join(parts)


_BPM_RE = re.compile(r"(\d{2,3})\s*BPM", re.I)


def sung_direction(options: dict, start: float, end: float) -> str:
    """Song mode: lyric lines heard between ``start`` and ``end`` (timeline
    seconds), timed from the clip's own start, plus the tempo — the video model
    otherwise invents a generic dance that ignores the words and the beat."""
    heard = [(s, text) for s, e, text in parse_lyrics(options.get("lyrics") or "", end) if e > start + 0.25]
    # Lines starting in this shot; a line carried over from the previous shot
    # only when nothing new starts here (it was mostly sung back there).
    lines = [(s - start, text) for s, text in heard if s >= start - 0.25] or [(0.0, t) for _, t in heard[-1:]]
    bpm = _BPM_RE.search(options.get("music_prompt") or "")
    tempo = f" at {bpm.group(1)} BPM" if bpm else ""
    if not lines:
        return f"Music plays (instrumental); the character moves on the beat{tempo}." if tempo else ""
    timed = "; ".join(f'{t:.0f}s "{text}"' for t, text in lines)
    return (f"A song is sung during this shot ({timed}): the character sings along with simple, happy body movement "
            f"on the beat{tempo}, without hand signs, finger counting or waving.")


def has_bible(options: dict) -> bool:
    return any((options.get(f"bible_{key}") or "").strip() for key in BIBLE_KEYS)


class PlanError(ValueError):
    pass


def extract_json(text: str) -> dict:
    """Parse the first JSON object in an LLM reply (tolerates code fences/prose
    and trailing commas — a common LLM slip in long replies)."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise PlanError("model tidak mengembalikan JSON storyboard")
    body = cleaned[start:end + 1]
    try:
        data = json.loads(body)
    except ValueError:
        try:
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", body))
        except ValueError as exc:
            raise PlanError("JSON storyboard tidak valid") from exc
    if not isinstance(data, dict):
        raise PlanError("JSON storyboard tidak valid")
    return data


def min_clip_seconds(clip_seconds: int) -> int:
    """Shortest clip to plan / request. Video models commonly reject < 4 s
    (seen live: "supported range: 4-30 seconds")."""
    return min(MIN_CLIP_SECONDS, clip_seconds)


def normalize(data: dict, *, clip_seconds: int, limit_seconds: int) -> dict:
    """Clamp durations, drop empty scenes, and stop before the preset limit."""
    min_s = min_clip_seconds(clip_seconds)
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
    keep_sources(scenes)
    link_shots(scenes)
    raw_bible = data.get("bible") if isinstance(data.get("bible"), dict) else {}
    bible = {key: str(raw_bible.get(key) or "").strip()[:1200] for key in BIBLE_KEYS}
    raw_concept = data.get("concept") if isinstance(data.get("concept"), dict) else {}
    beats = raw_concept.get("beats") if isinstance(raw_concept.get("beats"), list) else []
    concept = {"promise": str(raw_concept.get("promise") or "").strip()[:300],
               "beats": [str(b).strip()[:200] for b in beats if str(b).strip()][:30]}
    return {"title": str(data.get("title") or "").strip()[:120], "scenes": scenes, "bible": bible,
            "concept": concept if concept["promise"] else {},
            "music_prompt": str(data.get("music_prompt") or "").strip()[:2000]}


_SONG_MODE = ("This project is a music video with a sung song: write every narration as sung lyrics, and make the "
              "music_prompt a song (vocals) rather than instrumental background music.")


def _rules(language: str, clip_seconds: int, target: int, limit: int, aspect: str, song: bool = False) -> dict:
    return {
        "song": _SONG_MODE if song else "",
        "language": language, "min_s": min_clip_seconds(clip_seconds), "max_s": clip_seconds,
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


_FROM_SONG = """

The song already exists, so the picture follows it. Write exactly {count} scenes, one for each part below and in this
order. Each visual_prompt shows what is sung in that part, at the moment it is sung, keeping its numbers, names and
objects exact; a part with no words shows a matching instrumental moment. Copy each part's words into "narration".
{parts}"""


def plan_storyboard(client, model: str, *, prompt: str, language: str, clip_seconds: int, target_seconds: int,
                    limit_seconds: int, aspect: str, song: bool = False, lyrics: str = "",
                    song_seconds: float | None = None) -> dict:
    """Scenes for an idea. With timed lyrics they follow the song: its lines decide
    how many scenes there are, what each says and how long it lasts."""
    total = song_seconds or target_seconds
    parts = lyric_parts(lyrics, total, clip_seconds) if lyrics else []
    request = "Video idea: " + prompt
    if parts:
        listed = "\n".join(f"{i + 1}. {_clock(start)}-{_clock(end)}: {words or '(instrumental)'}"
                           for i, (start, end, words) in enumerate(parts))
        request += _FROM_SONG.format(count=len(parts), parts=listed)
    rules = _rules(language, clip_seconds, min(total, limit_seconds), limit_seconds, aspect, song)
    data = _ask_json(client, model, _SYSTEM.format(**rules), request, temperature=0.7)
    board = normalize(data, clip_seconds=clip_seconds, limit_seconds=limit_seconds)
    if len(board["scenes"]) == len(parts):
        for scene, (start, end, words) in zip(board["scenes"], parts):
            scene["duration"], scene["narration"] = round(end - start, 3), words
    return board


def edit_storyboard(client, model: str, *, storyboard: dict, instruction: str, language: str,
                    clip_seconds: int, limit_seconds: int, aspect: str, song: bool = False) -> dict:
    rules = _rules(language, clip_seconds, limit_seconds, limit_seconds, aspect, song)
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
at least 2.5 seconds apart, lines short and singable (max 9 words), with rhymes. Each scene's first line starts
at that scene's start second, so picture and words change together. Build each scene's lines from its text below
(when it is already a lyric, keep it nearly word for word) and keep the learning content exact: the same numbers,
names and objects at the same moment the scene shows them. Leave the last 5-8 seconds for an instrumental outro,
unless the video is shorter than 40 seconds (then at most 2-3 seconds). {hint}
"style": English music style for the generator (genre, mood, tempo BPM, instruments).
"vocal": English vocal description (e.g. "cheerful young female vocal").
Reply with JSON only:
{{"style": "...", "vocal": "...", "sections": [{{"name": "Verse 1", "lines": [{{"t": 4, "text": "..."}}]}}]}}"""

_SONG_FIRST = """You are a songwriter for short videos. Write an original song from the video idea below; the video will
later be cut to this song. Lyrics language: {language}. Total length {length} ({total} seconds). Group the lines into
sections (e.g. Intro (instrumental), Verse, Chorus, Outro). The chorus may repeat. Every lyric line has "t": the second
(from 0) it starts, at least 2.5 seconds apart, lines short and singable (max 9 words), with rhymes. Each line names
something that can be shown on screen, and keeps learning content exact and in order. Leave the last 5-8 seconds for
an instrumental outro, unless the song is shorter than 40 seconds (then at most 2-3 seconds). {hint}
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
    return _song_result(data, total)


def song_from_idea(client, model: str, *, idea: str, language: str, seconds: int, hint: str = "") -> dict:
    """Lyrics + song prompt written before any scene exists (same result as
    :func:`song_plan`), for the flow where the scenes follow the song."""
    instructions = _SONG_FIRST.format(language=language, length=_clock(seconds), total=seconds,
                                      hint=("Extra direction from the user: " + hint) if hint else "")
    return _song_result(_ask_json(client, model, instructions, "Video idea: " + idea, temperature=0.8), seconds)


def _song_result(data: dict, total: int) -> dict:
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


def _timed_lines(lyrics: str) -> list[tuple[float, str]]:
    """Sorted ``(second, text)`` of LRC lines; a timestamp with no text marks
    where the singing stops."""
    timed = []
    for raw in (lyrics or "").splitlines():
        match = _LRC_RE.match(raw.strip())
        if match:
            timed.append((int(match.group(1)) * 60 + float(match.group(2)), match.group(3).strip()))
    return sorted(timed, key=lambda item: item[0])


SONG_FADE_SECONDS = 2.0  # music left to fade out after the last sung word


def song_lengths(scenes: list[dict], lyrics: str, music_seconds: float | None = None) -> list[float] | None:
    """Scene lengths that put each cut on the sung line nearest its planned start,
    the same timestamps the subtitles use. A scene with no line near it keeps its
    planned start. The video ends after the last sung word when an empty timed
    line marks it, else with the song (``music_seconds``), else as planned.
    ``None`` without timed lyrics or when the song is too short for the scenes."""
    timed = _timed_lines(lyrics)
    lines = [t for t, text in timed if text]
    ordered = sorted(scenes, key=lambda s: s["idx"])
    if not lines or not ordered:
        return None
    planned = [float(s.get("duration") or 0) for s in ordered]
    edges, at = [0.0], 0.0
    for before, length in zip(planned, planned[1:]):
        at += before
        near = [t for t in lines if abs(t - at) <= min(before, length) / 2 and t > edges[-1]]
        edges.append(min(near, key=lambda t: abs(t - at)) if near else at)
    if not timed[-1][1]:
        end = timed[-1][0] + SONG_FADE_SECONDS
        end = min(end, music_seconds) if music_seconds else end
    else:
        end = music_seconds or sum(planned)
    edges.append(end)
    lengths = [round(b - a, 3) for a, b in zip(edges, edges[1:])]
    return lengths if min(lengths) >= 1.0 else None


def lyric_parts(lyrics: str, total: float, clip_seconds: int) -> list[tuple[float, float, str]]:
    """The song cut into clip-sized parts ``(start, end, words)``. Cuts fall on
    the start of a sung line when one fits; a long instrumental stretch is split
    evenly by clip length. A tail too short to film joins the part before it."""
    timed = _timed_lines(lyrics)
    lines = [(t, text) for t, text in timed if text and t < total]
    if not lines or total <= 0:
        return []
    edges = [0.0]
    while total - edges[-1] > clip_seconds:
        fits = [t for t, _ in lines if edges[-1] < t <= edges[-1] + clip_seconds]
        edges.append(fits[-1] if fits else edges[-1] + clip_seconds)
    if len(edges) > 1 and total - edges[-1] < min_clip_seconds(clip_seconds):
        edges.pop()
    edges.append(float(total))
    return [(a, b, " ".join(text for t, text in lines if a <= t < b)) for a, b in zip(edges, edges[1:])]


def fit_lengths(durations: list[float], total: float) -> list[float]:
    """Planned scene lengths scaled to fill ``total`` seconds (no timed lyrics to
    follow: the video still lasts exactly as long as the song)."""
    planned = sum(durations) or 1.0
    return [round(d * total / planned, 3) for d in durations]


def parse_lyrics(lyrics: str, total: float, max_line: float = 6.0) -> list[tuple[float, float, str]]:
    """Timed lines from LRC text → cues ``(start, end, text)``; a cue lasts
    until the next line (max ``max_line`` seconds). Section headers are skipped."""
    timed = _timed_lines(lyrics)
    cues = []
    for i, (start, text) in enumerate(timed):
        if start >= total:
            break
        if not text:
            continue
        nxt = timed[i + 1][0] if i + 1 < len(timed) else total
        cues.append((round(start, 3), round(min(nxt, start + max_line, total), 3), text))
    return cues
