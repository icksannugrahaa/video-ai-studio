"""ffmpeg/ffprobe wrappers (targets ffmpeg 4.4 on the PRoot server).

Every intermediate is normalised to one format (H.264 yuv420p, preset size and
fps, AAC 48 kHz stereo) so clips concatenate with stream copy, and audio
tracks are PCM 48 kHz so timelines stay sample-exact.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

AUDIO_RATE = 48000
_TIMEOUT = 1800


class MediaError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise MediaError("ffmpeg tidak ditemukan")
    return path


def _run(args: list, cwd: Path | None = None, timeout: int = _TIMEOUT) -> None:
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=str(cwd) if cwd else None)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffmpeg timeout") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise MediaError("ffmpeg gagal: " + " | ".join(tail)[:400])


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise MediaError("ffprobe tidak ditemukan")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,r_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe gagal untuk {Path(path).name}")
    return json.loads(proc.stdout or b"{}")


def duration(path: Path) -> float:
    return float((probe(path).get("format") or {}).get("duration") or 0.0)


def video_fps(path: Path) -> float:
    """Frame rate of the first video stream (0 when unknown)."""
    for stream in probe(path).get("streams") or []:
        if stream.get("codec_type") == "video":
            num, _, den = str(stream.get("r_frame_rate") or "0/1").partition("/")
            try:
                return float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                return 0.0
    return 0.0


_MOTION_RATES = (24.0, 25.0, 30.0)


def motion_fps(path: Path) -> float:
    """Rate at which the picture really changes. Models deliver 24 fps motion in
    a 60 fps file; only a rate that clearly matches a standard one is trusted, a
    still shot just has few changes and keeps the file's rate."""
    rate = video_fps(path)
    frames = _grey_frames(path)
    if rate <= 0 or len(frames) < 2:
        return rate
    steps = sum(a != b and sum(abs(x - y) for x, y in zip(a, b)) / len(a) > 0.02 for a, b in zip(frames, frames[1:]))
    seen = (steps + 1) * rate / len(frames)
    for standard in _MOTION_RATES:
        if standard < rate * 0.9 and abs(seen - standard) <= standard * 0.02:
            return standard
    return rate


def audible_end(path: Path) -> float:
    """Where the sound really ends: generated songs often close with seconds of
    silence that must not become a frozen end of the video."""
    length = duration(path)
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path), "-af", "silencedetect=n=-40dB:d=0.5",
                           "-f", "null", "-"], capture_output=True, timeout=_TIMEOUT)
    starts = re.findall(r"silence_start: ([\d.]+)", proc.stderr.decode("utf-8", "replace"))
    ends = re.findall(r"silence_end: ([\d.]+)", proc.stderr.decode("utf-8", "replace"))
    if starts and (len(ends) < len(starts) or float(ends[-1]) >= length - 0.1):
        return round(float(starts[-1]), 3)
    return round(length, 3)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams") or [])


def fit_image(src: Path, dst: Path, width: int, height: int) -> Path:
    """Scale and centre-crop an image to exactly ``width``×``height`` PNG: a
    keyframe must have the clip's size (a first frame fixes the clip's ratio)."""
    _run(["-i", src, "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1",
          "-frames:v", "1", dst])
    if not Path(dst).exists():
        raise MediaError("gagal menyesuaikan ukuran gambar")
    return Path(dst)


def image_size(path: Path) -> tuple[int, int]:
    """(width, height) of an image or a video's first stream."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise MediaError("ffprobe tidak ditemukan")
    proc = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "json", str(path)], capture_output=True, timeout=60)
    streams = json.loads(proc.stdout or b"{}").get("streams") or [] if proc.returncode == 0 else []
    if not streams or not streams[0].get("width"):
        raise MediaError("ukuran gambar tidak terbaca")
    return int(streams[0]["width"]), int(streams[0]["height"])


def last_frame_png(video: Path, out_png: Path) -> Path:
    """Grab the very last frame — continuity seed for the next clip. Decoding
    the tail and keeping the final image matters: a frame from 0.3 s earlier
    made the next clip jump back at every "continues" cut."""
    _run(["-sseof", "-0.5", "-i", video, "-update", "1", "-q:v", "2", out_png])
    if not Path(out_png).exists():
        raise MediaError("gagal mengambil frame terakhir")
    return Path(out_png)


def first_frame_png(video: Path, out_png: Path) -> Path:
    """The clip's first frame (what it started from)."""
    _run(["-i", video, "-frames:v", "1", out_png])
    if not Path(out_png).exists():
        raise MediaError("gagal mengambil frame pertama")
    return Path(out_png)


_SEAM_SIZE = (64, 36)  # tiny grey frames: enough to tell poses apart, cheap to compare in Python


def _grey_frames(path: Path, first_only: bool = False) -> list[bytes]:
    w, h = _SEAM_SIZE
    args = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", str(path),
            *(["-frames:v", "1"] if first_only else []),
            "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffmpeg timeout") from exc
    if proc.returncode != 0:
        raise MediaError("gagal membaca frame clip")
    size = w * h
    return [proc.stdout[i:i + size] for i in range(0, len(proc.stdout) - size + 1, size)]


def seam_frames(prev: Path, nxt: Path, *, window: float = 0.6, fps: float = 24.0) -> int | None:
    """Frames of ``prev`` to keep so it ends on the pose ``nxt`` starts from.

    A "continues" clip is seeded with a frame of the previous one, but not
    always its very last frame (older seeds were taken 0.3 s early, and some
    models re-render the seed slightly). Cutting the previous clip at the
    best-matching frame removes the backward jump at the cut. ``None`` when the
    last frame already matches best (nothing to cut)."""
    frames = _grey_frames(prev)
    first = _grey_frames(nxt, first_only=True)
    if len(frames) < 3 or not first:
        return None

    def diff(a: bytes, b: bytes) -> float:
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

    tail = max(2, int(window * fps))
    scores = [(diff(frames[k], first[0]), -k) for k in range(max(0, len(frames) - tail), len(frames))]
    best, k = min(scores)  # ties → the latest frame (cut as little as possible)
    k, last = -k, scores[-1][0]
    if k == len(frames) - 1 or best > 0.7 * last:  # no clearly better match than the real end
        return None
    return k + 1


SEAM_BREAK = 15.0  # worst block's mean grey difference (0-255); good seeded seams measure 10-11, broken ones 20+


def seam_gap(prev: Path, nxt: Path) -> float:
    """How far a seeded clip's first frame is from the end of the previous clip.
    Compared per block: a small object changing barely moves the whole-frame mean."""
    frames, first = _grey_frames(prev), _grey_frames(nxt, first_only=True)
    if not frames or not first:
        return 0.0
    w, h = _SEAM_SIZE
    cols, rows = 8, 4
    totals = [0] * (cols * rows)
    for i, (x, y) in enumerate(zip(frames[-1], first[0])):
        totals[(i % w) * cols // w + (i // w) * rows // h * cols] += abs(x - y)
    return max(totals) / (w * h / (cols * rows))


def seam_broken(prev: Path, nxt: Path) -> bool:
    """Whether a seeded clip visibly left its seed (an apple gone, an arm moved)."""
    return seam_gap(prev, nxt) > SEAM_BREAK


STILL_MOTION = 4.5  # grey change per second (0-255); idle poses measure about 3, acted ones 6+


def active_seconds(path: Path, *, window: float = 0.25) -> float:
    """Where a clip's action ends: models often finish early and hold the pose,
    which plays as a stall right before the next clip starts moving again."""
    rate = video_fps(path)
    frames = _grey_frames(path)
    if rate <= 0 or len(frames) < 2:
        return duration(path)
    steps = [sum(abs(x - y) for x, y in zip(a, b)) / len(a) for a, b in zip(frames, frames[1:])]
    size = max(1, round(window * rate))
    end = len(steps)
    while end >= size and sum(steps[end - size:end]) / window < STILL_MOTION:
        end -= size
    return (end + 1) / rate


def seam_colour_mean(path: Path, *, last: bool = False) -> tuple[float, float, float]:
    """Mean red, green and blue of a clip's first or last frame."""
    w, h = _SEAM_SIZE
    args = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *(["-sseof", "-0.5"] if last else []), "-i", str(path),
            *([] if last else ["-frames:v", "1"]), "-vf", f"scale={w}:{h},format=rgb24", "-f", "rawvideo", "-"]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffmpeg timeout") from exc
    size = w * h * 3
    if proc.returncode != 0 or len(proc.stdout) < size:
        raise MediaError("gagal membaca frame clip")
    frame = proc.stdout[-size:]
    return tuple(sum(frame[c::3]) / (w * h) for c in range(3))


def seam_colour_gain(prev: Path, nxt: Path) -> tuple[float, float, float]:
    """Per-channel gain that gives a seeded clip's first frame the colour of the
    previous clip's end: models re-render the seed slightly darker every time."""
    before, after = seam_colour_mean(prev, last=True), seam_colour_mean(nxt)
    return tuple(b / a if a else 1.0 for b, a in zip(before, after))


def normalize_clip(src: Path, dst: Path, *, width: int, height: int, fps: float, seconds: float,
                   keep_audio: bool, preset: str = "veryfast", lead: float = 0.0,
                   keep_frames: int | None = None, retime: float | None = None,
                   gain: tuple[float, float, float] | None = None, active: float | None = None) -> Path:
    """Scale/crop ``src`` to fill ``width``×``height``, pad it to ``seconds``
    and always emit a stereo AAC track (silent if needed).

    A clip shorter than ``seconds`` is padded by holding its first frame for up
    to ``lead`` seconds (the part hidden under the incoming crossfade), and only
    the rest by holding its last frame — a frozen tail before a "continues" cut
    shows as a stall.

    ``keep_frames`` (from :func:`seam_frames`) drops the frames after the seam
    and slows the rest down a little so the clip keeps its length. ``retime``
    plays the clip over that many seconds, so it fills a sung section without
    a frozen tail (kept to a speed change that still looks natural); a section
    too long for that plays the clip forward and back instead of freezing.
    ``gain`` multiplies red, green and blue (see :func:`seam_colour_gain`).
    ``active`` drops the picture after that second (see :func:`active_seconds`)."""
    src_seconds = duration(src)
    stretch = ""
    cut = ""
    if active:
        cut = f"trim=end={active:.3f},setpts=PTS-STARTPTS,"
        src_seconds = active
    if keep_frames:
        kept = keep_frames / (video_fps(src) or 24.0)
        factor = src_seconds / kept if kept else 1.0
        if 1.0 < factor <= 1.15:  # ≤ 15 % slower is not noticeable; more would be
            stretch = f"trim=end_frame={keep_frames},setpts=(PTS-STARTPTS)*{factor:.5f},"
    bounce = ""
    if retime and src_seconds and 0.9 <= retime / src_seconds <= 1.8:
        stretch = f"setpts=(PTS-STARTPTS)*{retime / src_seconds:.5f},"
        src_seconds = retime
    elif retime and src_seconds and retime / src_seconds > 1.8:
        factor = min(1.8, max(1.0, retime / (2 * src_seconds)))
        # After scaling: reverse buffers every frame, keep that small on a phone.
        bounce = (f"split[fwd][back];[back]reverse[rev];[fwd][rev]concat=n=2:v=1:a=0,"
                  f"setpts=(PTS-STARTPTS)*{factor:.5f},fps={fps:g},")
        src_seconds = 2 * src_seconds * factor
    missing = max(0.0, seconds - src_seconds)
    head = min(missing, max(0.0, lead))
    pad = missing - head + 0.1
    tpad = f"tpad=start_mode=clone:start_duration={head:.3f}:" if head > 0 else "tpad="
    tint = f"colorchannelmixer=rr={gain[0]:.4f}:gg={gain[1]:.4f}:bb={gain[2]:.4f}," if gain else ""
    vf = (f"{tint}{cut}{stretch}scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
          f"setsar=1,fps={fps:g},{bounce}{tpad}stop_mode=clone:stop_duration={pad:.3f}")
    args: list = ["-i", src]
    if keep_audio and has_audio(src):
        audio = ["-map", "0:a:0", "-af", f"aresample={AUDIO_RATE},apad"]
    else:
        args += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
        audio = ["-map", "1:a:0"]
    args += ["-map", "0:v:0", *audio, "-vf", vf, "-t", f"{seconds:.3f}",
             "-c:v", "libx264", "-preset", preset, "-crf", "23", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", AUDIO_RATE, "-ac", "2", dst]
    _run(args)
    return Path(dst)


def concat_videos(clips: list[Path], dst: Path) -> Path:
    """Stream-copy concat of already normalised clips."""
    listing = Path(dst).with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(c).resolve().as_posix()}'\n" for c in clips), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", "-movflags", "+faststart", dst])
    listing.unlink(missing_ok=True)
    return Path(dst)


_FILTER_CACHE: dict[str, bool] = {}


def has_filter(name: str) -> bool:
    """Whether this ffmpeg build has filter ``name`` (``xfade`` needs ffmpeg >= 4.3;
    distro builds on plain Linux servers and in PRoot may be older)."""
    if name not in _FILTER_CACHE:
        try:
            proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, timeout=30)
            names = {line.split()[1] for line in proc.stdout.decode("utf-8", "replace").splitlines()
                     if len(line.split()) >= 3 and not line.startswith(" ---")}
            _FILTER_CACHE[name] = name in names
        except (MediaError, OSError, subprocess.TimeoutExpired):
            _FILTER_CACHE[name] = False
    return _FILTER_CACHE[name]


def crossfade_clip_seconds(seconds: list[float], transitions: list[float], i: int) -> float:
    """Length clip ``i`` needs for :func:`crossfade_videos`: its scene plus half
    of the fade on each side that has one."""
    before = transitions[i - 1] / 2 if i else 0.0
    return round(seconds[i] + before + transitions[i] / 2, 3)


def crossfade_videos(clips: list[Path], seconds: list[float], transitions: list[float], dst: Path, *,
                     preset: str = "veryfast") -> Path:
    """Join normalised clips with crossfades, keeping the scene timeline exact.

    ``transitions[i]`` is the fade between clip ``i`` and ``i + 1`` (0 = hard
    cut, last is 0). Each fade is centred on the scene boundary
    ``sum(seconds[:i + 1])``, so picture and narration/subtitles change
    together; clip ``i`` must therefore be ``crossfade_clip_seconds(...)``
    long (half a fade of extra picture on each faded side). Total length is
    ``sum(seconds)``; audio is each clip's track cut to its scene.
    """
    args: list = []
    for clip in clips:
        args += ["-i", clip]
    graph, cursor = [], 0.0
    for i in range(len(clips)):
        lead = transitions[i - 1] / 2 if i else 0.0  # picture shown before the scene starts
        graph.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[v{i}]")
        graph.append(f"[{i}:a]atrim={lead:.3f}:{lead + seconds[i]:.3f},asetpts=PTS-STARTPTS[a{i}]")
    current = "[v0]"
    for i in range(1, len(clips)):
        cursor += seconds[i - 1]
        fade = transitions[i - 1]
        out = f"[x{i}]"
        if fade > 0:
            graph.append(f"{current}[v{i}]xfade=transition=fade:duration={fade:.3f}:"
                         f"offset={cursor - fade / 2:.3f}{out}")
        else:
            graph.append(f"{current}[v{i}]concat=n=2:v=1:a=0{out}")
        current = out
    graph.append(f"{current}null[vout]")
    graph.append("".join(f"[a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=0:a=1[aout]")
    total = sum(seconds)
    _run([*args, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
          "-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-ar", AUDIO_RATE, "-ac", "2", "-movflags", "+faststart", dst])
    return Path(dst)


def to_wav(src: Path, dst: Path) -> Path:
    _run(["-i", src, "-ar", AUDIO_RATE, "-ac", "1", "-c:a", "pcm_s16le", dst])
    return Path(dst)


def concat_audio(parts: list[Path], dst: Path) -> Path:
    """Join WAV parts (same format) into one WAV."""
    if len(parts) == 1:
        shutil.copyfile(parts[0], dst)
        return Path(dst)
    listing = Path(dst).with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(p).resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", dst])
    listing.unlink(missing_ok=True)
    return Path(dst)


def fit_audio(src: Path | None, dst: Path, seconds: float) -> Path:
    """Exactly ``seconds`` of mono PCM: ``src`` padded/trimmed, or silence."""
    if src is None:
        args = ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=mono"]
    else:
        args = ["-i", src, "-af", "apad"]
    _run([*args, "-t", f"{seconds:.3f}", "-ar", AUDIO_RATE, "-ac", "1", "-c:a", "pcm_s16le", dst])
    return Path(dst)


def compose_final(video: Path, narration: Path, dst: Path, *, total_seconds: float,
                  music: Path | None = None, music_volume: float = 0.25, keep_clip_audio: bool = False,
                  subtitles_ass: str | None = None, preset: str = "veryfast", cwd: Path | None = None) -> Path:
    """Mix narration (+ ducked music, + optional clip audio), normalise loudness
    to -14 LUFS and burn the ASS subtitles (path relative to ``cwd``)."""
    args: list = ["-i", video, "-i", narration]
    if music is not None:
        args += ["-stream_loop", "-1", "-i", music]
    graph = [f"[1:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,asplit=2[nar][narsc]"]
    mix = ["[nar]"]
    if music is not None:
        fade = min(2.0, total_seconds / 4)
        graph.append(f"[2:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
                     f"volume={music_volume:.3f},atrim=0:{total_seconds:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.5,afade=t=out:st={total_seconds - fade:.3f}:d={fade:.3f}[mus]")
        graph.append("[mus][narsc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=500[duck]")
        mix.append("[duck]")
    else:
        graph.append("[narsc]anullsink")
    if keep_clip_audio:
        graph.append("[0:a]volume=0.35[clip]")
        mix.append("[clip]")
    # amix divides by the input count; scale back so narration stays at 0 dB.
    graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=longest:dropout_transition=0,"
                 f"volume={len(mix)},loudnorm=I=-14:TP=-1.5:LRA=11,aresample={AUDIO_RATE}[aout]")
    graph.append(f"[0:v]ass={subtitles_ass}[vout]" if subtitles_ass else "[0:v]null[vout]")
    args += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
             "-t", f"{total_seconds:.3f}", "-c:v", "libx264", "-preset", preset, "-crf", "22",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst]
    _run(args, cwd=cwd)
    return Path(dst)
