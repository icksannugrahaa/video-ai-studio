"""ffmpeg/ffprobe wrappers (targets ffmpeg 4.4 on the PRoot server).

Every intermediate is normalised to one format (H.264 yuv420p, preset size and
fps, AAC 48 kHz stereo) so clips concatenate with stream copy, and audio
tracks are PCM 48 kHz so timelines stay sample-exact.
"""

from __future__ import annotations

import json
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
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)],
        capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe gagal untuk {Path(path).name}")
    return json.loads(proc.stdout or b"{}")


def duration(path: Path) -> float:
    return float((probe(path).get("format") or {}).get("duration") or 0.0)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams") or [])


def last_frame_png(video: Path, out_png: Path) -> Path:
    """Grab (approximately) the last frame — continuity seed for the next clip."""
    _run(["-sseof", "-0.3", "-i", video, "-frames:v", "1", "-q:v", "2", out_png])
    if not Path(out_png).exists():
        raise MediaError("gagal mengambil frame terakhir")
    return Path(out_png)


def normalize_clip(src: Path, dst: Path, *, width: int, height: int, fps: int, seconds: float,
                   keep_audio: bool, preset: str = "veryfast") -> Path:
    """Scale/crop ``src`` to fill ``width``×``height``, hold the last frame up
    to ``seconds`` and always emit a stereo AAC track (silent if needed)."""
    src_seconds = duration(src)
    pad = max(0.0, seconds - src_seconds) + 0.1
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
          f"setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={pad:.3f}")
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
