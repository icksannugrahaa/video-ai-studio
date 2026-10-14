"""Job execution: plan, edit-by-prompt, render, regenerate.

Every step persists its result per scene (clip file + version, narration
audio + timings), so a job interrupted by a restart resumes and skips work
that is already done. Upstream/ffmpeg errors surface as job messages; API
keys never appear in them.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import Settings
from app.pipeline import media, planner, presets, subtitles
from app.pipeline.text import split_sentences
from app.providers import ProviderClient, ProviderError
from app.repo import Repo
from app.security import SecretBox

log = logging.getLogger("sav.engine")
CLIP_ATTEMPTS = 3
# Back-off before retry 2 and 3: upstream rate limits / busy queues need time,
# instant retries just fail the same way (seen live: CodeBuddy 429 bursts).
CLIP_RETRY_DELAYS = (30, 90)
NARRATION_TAIL = 0.4  # seconds of breathing room after the last sentence


def clip_chains(scenes: list[dict], *, continuity: bool, bible: bool) -> list[list[dict]]:
    """Split scenes into chains that must be generated in order.

    A scene joins the previous scene's chain when it is seeded with that clip's
    last frame (continuity on and the scene ``continues`` — or, for projects
    planned before the bible existed, every scene). Different chains have no
    dependency and can be generated in parallel.
    """
    chains: list[list[dict]] = []
    for scene in sorted(scenes, key=lambda s: s["idx"]):
        linked = continuity and chains and (scene.get("continues") or not bible)
        if linked:
            chains[-1].append(scene)
        else:
            chains.append([scene])
    return chains


def scene_transitions(scenes: list[dict], lengths: list[float], options: dict) -> list[float]:
    """Crossfade seconds after each scene (last is 0). A shot that continues the
    previous one already starts from its last frame, so it gets a hard cut;
    fades are capped at a third of the shorter neighbouring scene."""
    try:
        wanted = max(0.0, min(1.5, float(options.get("transition", 0.5) or 0)))
    except (TypeError, ValueError):
        wanted = 0.5
    fades = []
    for i in range(len(scenes)):
        if i == len(scenes) - 1 or not wanted or scenes[i + 1].get("continues"):
            fades.append(0.0)
        else:
            fades.append(round(min(wanted, lengths[i] / 3, lengths[i + 1] / 3), 3))
    return fades


def _bible_options(board: dict) -> dict:
    """Project option updates for a planner result's bible (empty fields skipped,
    so an edit that drops the bible keeps the stored one)."""
    bible = board.get("bible") or {}
    return {f"bible_{key}": bible[key] for key in planner.BIBLE_KEYS if bible.get(key)}


class JobCanceled(Exception):
    pass


class JobFailed(Exception):
    pass


_NARRATION_LOCKS: dict[int, threading.Lock] = {}
_NARRATION_LOCKS_GUARD = threading.Lock()


def _narration_lock(project_id: int) -> threading.Lock:
    """One TTS pass per project at a time (a preview may run next to a render)."""
    with _NARRATION_LOCKS_GUARD:
        return _NARRATION_LOCKS.setdefault(project_id, threading.Lock())


class Workspace:
    def __init__(self, root: Path, project_id: int):
        self.root = Path(root) / str(project_id)
        for sub in ("clips", "frames", "narration", "norm", "tmp", "tmp_preview"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)


class Engine:
    def __init__(self, settings: Settings, repo: Repo, box: SecretBox, client_factory=ProviderClient):
        self.settings = settings
        self.repo = repo
        self.box = box
        self.client_factory = client_factory

    # ── plumbing ───────────────────────────────────────────────────────
    def _progress(self, job: dict, progress: float, message: str) -> None:
        if self.repo.job_status(job["id"]) == "canceled":
            raise JobCanceled()
        self.repo.update_job(job["id"], progress=round(progress, 3), message=message)

    def _context(self, job: dict) -> tuple[dict, dict, ProviderClient, dict]:
        project = self.repo.project(job["user_id"], job["project_id"])
        if not project:
            raise JobFailed("project tidak ditemukan")
        profile = self.repo.profile(job["user_id"], project["profile_id"]) if project["profile_id"] else None
        if not profile:
            raise JobFailed("project belum memilih profil provider")
        client = self.client_factory(profile["base_url"], self.box.decrypt(profile["api_key_enc"]))
        preset = presets.resolve(project["preset"], self.settings.render_width)
        return project, profile, client, preset

    def run(self, job: dict) -> dict:
        handlers = {"plan": self.run_plan, "edit": self.run_edit, "render": self.run_render,
                    "regenerate": self.run_regenerate, "compose": self.run_compose,
                    "music_prompt": self.run_music_prompt, "preview": self.run_preview}
        if job["kind"] not in handlers:
            raise JobFailed(f"jenis job tidak dikenal: {job['kind']}")
        return handlers[job["kind"]](job)

    # ── plan / edit ────────────────────────────────────────────────────
    def run_plan(self, job: dict) -> dict:
        project, profile, client, preset = self._context(job)
        if not profile["chat_model"]:
            raise JobFailed("profil belum memilih model chat")
        self._progress(job, 0.1, "Menyusun storyboard…")
        board = planner.plan_storyboard(
            client, profile["chat_model"], prompt=project["prompt"], language=project["language"],
            clip_seconds=int(profile["clip_seconds"]), target_seconds=int(project["target_seconds"]),
            limit_seconds=int(preset["max_seconds"]), aspect=preset["aspect"],
        )
        diff = self.repo.replace_scenes(project["id"], board["scenes"])
        update = {"status": "planned"}
        if board["title"] and not project["title"]:
            update["title"] = board["title"]
        update["options"] = _bible_options(board)
        if board.get("music_prompt"):
            update["options"]["music_prompt"] = board["music_prompt"]
        self.repo.update_project(job["user_id"], project["id"], update)
        return {"scenes": len(board["scenes"]), **diff}

    def run_music_prompt(self, job: dict) -> dict:
        project, profile, client, _preset = self._context(job)
        scenes = self.repo.scenes(project["id"])
        if not scenes:
            raise JobFailed("storyboard kosong — jalankan Plan dulu")
        self._progress(job, 0.2, "Menyusun prompt musik…")
        prompt = planner.music_prompt(client, profile["chat_model"], title=project["title"], scenes=scenes,
                                      hint=(job["payload"].get("hint") or "").strip())
        self.repo.update_project(job["user_id"], project["id"], {"options": {"music_prompt": prompt}})
        return {"music_prompt": prompt}

    def run_compose(self, job: dict) -> dict:
        """Re-mix only (new music / volume / subtitle option): no clip is generated.

        ``payload.partial`` builds ``preview.mp4`` from the scenes whose clip is
        ready (e.g. while provider credits are exhausted); otherwise every clip
        must exist and the result is ``final.mp4``.
        """
        project, profile, client, preset = self._context(job)
        scenes = self.repo.scenes(project["id"])
        ready = [s for s in scenes if s["clip_status"] == "done" and s["clip_version"] == s["version"]
                 and s["clip_file"]]
        partial = bool(job["payload"].get("partial"))
        if partial:
            if not ready:
                raise JobFailed("belum ada clip yang jadi")
        elif len(ready) != len(scenes):
            missing = [s["idx"] + 1 for s in scenes if s not in ready]
            raise JobFailed(f"clip scene {missing[:5]} belum jadi — pakai Lanjutkan render")
        ws = Workspace(self.settings.projects_dir, project["id"])
        if not self._is_song(project):
            self._narrate(job, project, profile, client, ready, ws, 0.0, 0.3)
        ids = {s["id"] for s in ready}
        chosen = [s for s in self.repo.scenes(project["id"]) if s["id"] in ids]
        result = self._compose(job, project, preset, chosen, ws, out_name="preview" if partial else "final",
                               tmp_dir="tmp_preview" if job["kind"] == "preview" else "tmp")
        if not partial:
            self.repo.update_project(job["user_id"], project["id"], {"status": "done"})
        return {**result, "partial": partial, "scenes_used": [s["idx"] + 1 for s in chosen]}

    def run_preview(self, job: dict) -> dict:
        """"Render sementara": ``preview.mp4`` from the clips ready right now.
        Runs in the preview lane, so it works while a render is still going."""
        job["payload"] = {**(job.get("payload") or {}), "partial": True}
        return self.run_compose(job)

    def run_edit(self, job: dict) -> dict:
        project, profile, client, preset = self._context(job)
        instruction = (job["payload"].get("instruction") or "").strip()
        if not instruction:
            raise JobFailed("instruksi edit kosong")
        if job["result"].get("edited"):  # resumed after restart: never apply the edit twice
            diff = job["result"]["edited"]
            return {**diff, **self._render(job, project, profile, client, preset, start=0.1)}
        opts = project["options"]
        current = {"title": project["title"],
                   "bible": {key: opts.get(f"bible_{key}") or "" for key in planner.BIBLE_KEYS},
                   "scenes": [{"visual_prompt": s["visual_prompt"], "continues": s["continues"],
                               "narration": s["narration"], "duration": s["duration"]}
                              for s in self.repo.scenes(project["id"])]}
        self._progress(job, 0.05, "Menerapkan instruksi edit…")
        board = planner.edit_storyboard(
            client, profile["chat_model"], storyboard=current, instruction=instruction,
            language=project["language"], clip_seconds=int(profile["clip_seconds"]),
            limit_seconds=int(preset["max_seconds"]), aspect=preset["aspect"],
        )
        diff = self.repo.replace_scenes(project["id"], board["scenes"])
        options = _bible_options(board)
        if board.get("music_prompt"):
            options["music_prompt"] = board["music_prompt"]
        if options:
            self.repo.update_project(job["user_id"], project["id"], {"options": options})
        self.repo.update_job(job["id"], result={"edited": diff})
        project = self.repo.project(job["user_id"], project["id"]) or project
        result = self._render(job, project, profile, client, preset, start=0.1)
        return {**diff, **result}

    # ── render ─────────────────────────────────────────────────────────
    def run_render(self, job: dict) -> dict:
        project, profile, client, preset = self._context(job)
        return self._render(job, project, profile, client, preset, start=0.0)

    def run_regenerate(self, job: dict) -> dict:
        # The API bumps the scene version when queuing, so a resumed job does
        # not regenerate twice; rendering skips every up-to-date scene.
        project, profile, client, preset = self._context(job)
        return self._render(job, project, profile, client, preset, start=0.0)

    def _render(self, job, project, profile, client, preset, *, start: float) -> dict:
        if not profile["video_model"]:
            raise JobFailed("profil belum memilih model video")
        scenes = self.repo.scenes(project["id"])
        if not scenes:
            raise JobFailed("storyboard kosong — jalankan Plan dulu")
        ws = Workspace(self.settings.projects_dir, project["id"])
        self.repo.update_project(job["user_id"], project["id"], {"status": "rendering"})
        try:
            self._generate_clips(job, project, profile, client, preset, scenes, ws, start, 0.65)
            scenes = self.repo.scenes(project["id"])
            if not self._is_song(project):  # song mode: the lyrics are the voice, no TTS
                self._narrate(job, project, profile, client, scenes, ws, 0.65, 0.8)
            scenes = self.repo.scenes(project["id"])
            # Re-read options: music may have been uploaded (or the volume /
            # subtitle switches changed) while the clips were generating.
            project = self.repo.project(job["user_id"], project["id"]) or project
            result = self._compose(job, project, preset, scenes, ws)
        except Exception:
            self.repo.update_project(job["user_id"], project["id"], {"status": "error"})
            raise
        self.repo.update_project(job["user_id"], project["id"], {"status": "done"})
        return result

    # clips ------------------------------------------------------------
    def _generate_clips(self, job, project, profile, client, preset, scenes, ws, p0, p1) -> None:
        todo_ids = {s["id"] for s in scenes if not (s["clip_status"] == "done" and s["clip_version"] == s["version"]
                                                     and s["clip_file"] and ws.path(s["clip_file"]).exists())}
        if not todo_ids:
            return
        continuity = bool(project["options"].get("continuity"))
        # With a story bible the planner marks which shots continue the previous
        # one; only those start from its last frame (a new location must not
        # inherit the old background). Older projects seed every scene.
        bible = planner.has_bible(project["options"])
        chains = clip_chains(scenes, continuity=continuity, bible=bible)
        # Chains are independent and run side by side; scenes inside a chain wait
        # for the previous clip (its last frame seeds the next one).
        work_chains = [[s for s in chain if s["id"] in todo_ids] for chain in chains]
        work_chains = [c for c in work_chains if c]
        total = len(todo_ids)
        state = {"done": 0, "running": 0}
        lock = threading.Lock()
        stop = threading.Event()  # first failure: no chain starts a new (billed) clip

        def report(note: str) -> None:
            with lock:
                n, running = state["done"], state["running"]
            extra = f" · {running} berjalan paralel" if running > 1 else ""
            self._progress(job, p0 + (p1 - p0) * n / total, f"{note}{extra}")

        def run_chain(chain: list[dict]) -> None:
            for scene in chain:
                if stop.is_set():
                    return
                seed = None
                if continuity and scene["idx"] > 0 and (scene.get("continues") or not bible):
                    prev = next((s for s in self.repo.scenes(project["id"]) if s["idx"] == scene["idx"] - 1), None)
                    if prev and prev.get("clip_file") and ws.path(prev["clip_file"]).exists():
                        frame = media.last_frame_png(ws.path(prev["clip_file"]),
                                                     ws.path("frames", f"scene_{prev['idx']}_last.png"))
                        seed = frame.read_bytes()
                with lock:
                    state["running"] += 1
                try:
                    self._generate_one(job, project, profile, client, preset, scene, ws, seed)
                except BaseException:
                    stop.set()
                    raise
                finally:
                    with lock:
                        state["running"] -= 1
                with lock:
                    state["done"] += 1
                    n = state["done"]
                report(f"Clip {n}/{total} selesai")

        lanes = max(1, min(self.settings.clip_concurrency, len(work_chains)))
        report(f"Generate {total} clip" + (f" ({lanes} jalur paralel)" if lanes > 1 else "") + "…")
        if lanes == 1:
            for chain in work_chains:
                run_chain(chain)
            return
        errors: list[BaseException] = []
        with ThreadPoolExecutor(lanes) as pool:
            for future in [pool.submit(run_chain, c) for c in work_chains]:
                try:
                    future.result()
                except BaseException as exc:  # noqa: BLE001 — re-raised below, cancel wins
                    errors.append(exc)
        if errors:
            raise next((e for e in errors if isinstance(e, JobCanceled)), errors[0])

    def _generate_one(self, job, project, profile, client, preset, scene, ws, seed) -> None:
        self.repo.update_scene(scene["id"], clip_status="running", clip_error=None)
        last_error = None
        started = time.monotonic()  # generation time shown per clip (includes retries/back-off)
        for attempt in range(1, CLIP_ATTEMPTS + 1):
            try:
                video = client.generate_video(
                    profile["video_model"], planner.clip_prompt(project["options"], scene["visual_prompt"]),
                    seconds=int(round(scene["duration"])),
                    aspect_ratio=preset["model_aspect"], image_png=seed,
                    enable_audio=bool(project["options"].get("keep_clip_audio")),
                    should_cancel=lambda: self.repo.job_status(job["id"]) == "canceled",
                )
                name = f"clips/scene_{scene['idx']}_v{scene['version']}.{video.ext}"
                ws.path(name).write_bytes(video.data)
                media.duration(ws.path(name))  # validate it is a real video
                self.repo.update_scene(scene["id"], clip_status="done", clip_file=name,
                                       clip_version=scene["version"], clip_error=None,
                                       clip_gen_seconds=round(time.monotonic() - started, 1), clip_attempts=attempt)
                log.info("scene %s clip done in %.0fs (attempt %s)", scene["idx"], time.monotonic() - started, attempt)
                return
            except ProviderError as exc:
                last_error = exc.message
                if exc.status == 499:
                    raise JobCanceled() from exc
                if not exc.retryable:
                    break
            except media.MediaError as exc:
                last_error = f"file video tidak valid: {exc}"
            log.warning("scene %s attempt %s failed", scene["idx"], attempt)
            if attempt < CLIP_ATTEMPTS:
                delay = CLIP_RETRY_DELAYS[min(attempt, len(CLIP_RETRY_DELAYS)) - 1]
                self._progress(job, self.repo.job(job["id"])["progress"],
                               f"Scene {scene['idx'] + 1} gagal ({(last_error or '')[:80]}), coba lagi dalam {delay} detik…")
                self._sleep(job, delay)
        self.repo.update_scene(scene["id"], clip_status="failed", clip_error=(last_error or "gagal")[:300])
        raise JobFailed(f"Scene {scene['idx'] + 1} gagal: {last_error}")

    @staticmethod
    def _is_song(project: dict) -> bool:
        return project["options"].get("music_style") == "song" and project["options"].get("music_mode") != "none"

    def _sleep(self, job: dict, seconds: float) -> None:
        """Wait in small steps so a cancel request is honoured quickly."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.repo.job_status(job["id"]) == "canceled":
                raise JobCanceled()
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))

    # narration --------------------------------------------------------
    def _narrate(self, job, project, profile, client, scenes, ws, p0, p1) -> None:
        with _narration_lock(project["id"]):
            self._narrate_locked(job, project, profile, client, scenes, ws, p0, p1)

    def _narrate_locked(self, job, project, profile, client, scenes, ws, p0, p1) -> None:
        # Re-read: another lane may have just narrated some of these scenes.
        ids = {s["id"] for s in scenes}
        scenes = [s for s in self.repo.scenes(project["id"]) if s["id"] in ids]
        voice = project["options"].get("voice") or profile["tts_voice"]
        signature = f"{profile['tts_model']}|{voice}|{project['language']}"
        todo = []
        for scene in scenes:
            info = scene.get("narration_info") or {}
            fresh = (info.get("text") == scene["narration"] and info.get("signature") == signature
                     and (not scene["narration"] or (scene["narration_file"]
                                                     and ws.path(scene["narration_file"]).exists())))
            if not fresh:
                todo.append(scene)
        if todo and any(s["narration"] for s in todo) and not profile["tts_model"]:
            raise JobFailed("profil belum memilih model TTS (narasi diisi)")
        for n, scene in enumerate(todo, 1):
            self._progress(job, p0 + (p1 - p0) * (n - 1) / max(1, len(todo)), f"Narasi scene {scene['idx'] + 1}…")
            if not scene["narration"]:
                self.repo.update_scene(scene["id"], narration_file=None, narration_info={
                    "text": "", "signature": signature, "duration": 0.0, "sentences": []})
                continue
            parts, sentences, cursor = [], [], 0.0
            for i, sentence in enumerate(split_sentences(scene["narration"])):
                audio = client.tts(profile["tts_model"], sentence, voice=voice, language=project["language"])
                raw = ws.path("narration", f".tts_{scene['idx']}_{i}.bin")
                raw.write_bytes(audio)
                wav = media.to_wav(raw, ws.path("narration", f".tts_{scene['idx']}_{i}.wav"))
                raw.unlink(missing_ok=True)
                length = media.duration(wav)
                sentences.append({"text": sentence, "start": round(cursor, 3), "end": round(cursor + length, 3)})
                cursor += length
                parts.append(wav)
            name = f"narration/scene_{scene['idx']}.wav"
            media.concat_audio(parts, ws.path(name))
            for part in parts:
                part.unlink(missing_ok=True)
            self.repo.update_scene(scene["id"], narration_file=name, narration_info={
                "text": scene["narration"], "signature": signature, "duration": round(cursor, 3),
                "sentences": sentences})

    # compose ----------------------------------------------------------
    def _compose(self, job, project, preset, scenes, ws, out_name: str = "final", tmp_dir: str = "tmp") -> dict:
        opts = project["options"]
        song = self._is_song(project)
        keep_audio = bool(opts.get("keep_clip_audio"))
        settings = self.settings
        norm_clips, narr_parts, timings, offset = [], [], [], 0.0
        lengths = []
        for scene in scenes:
            info = {} if song else (scene.get("narration_info") or {})
            lengths.append(round(max(float(scene["duration"]), float(info.get("duration") or 0) + NARRATION_TAIL), 2))
        fades = scene_transitions(scenes, lengths, opts) if media.has_filter("xfade") else [0.0] * len(scenes)
        p_start = max(0.3, self.repo.job(job["id"])["progress"])
        for n, scene in enumerate(scenes, 1):
            self._progress(job, p_start + (0.92 - p_start) * (n - 1) / len(scenes),
                           f"Menyiapkan scene {n}/{len(scenes)}…")
            info = {} if song else (scene.get("narration_info") or {})
            seconds = lengths[n - 1]
            # Faded sides need half a fade of extra picture (fades are centred on the cut).
            clip_seconds = media.crossfade_clip_seconds(lengths, fades, n - 1)
            key = hashlib.sha1(f"{scene['clip_file']}|{clip_seconds}|{preset['width']}x{preset['height']}|"
                               f"{settings.render_fps}|{keep_audio}".encode()).hexdigest()[:10]
            norm = ws.path("norm", f"scene_{scene['idx']}_{key}.mp4")
            if not norm.exists():
                # Write under a unique name then rename: a preview and a render may
                # normalise the same clip at the same moment.
                part = norm.with_name(f"{norm.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
                media.normalize_clip(ws.path(scene["clip_file"]), part, width=preset["width"],
                                     height=preset["height"], fps=settings.render_fps, seconds=clip_seconds,
                                     keep_audio=keep_audio, preset=settings.ffmpeg_preset)
                os.replace(part, norm)
            norm_clips.append(norm)
            narr_src = ws.path(scene["narration_file"]) if scene.get("narration_file") and not song else None
            narr_parts.append(media.fit_audio(narr_src, ws.path(tmp_dir, f"narr_fit_{scene['idx']}.wav"), seconds))
            timings.append({"offset": offset, "sentences": info.get("sentences") or []})
            offset += seconds

        self._progress(job, 0.93, "Menggabungkan video…")
        if any(fades):
            video = media.crossfade_videos(norm_clips, lengths, fades, ws.path(tmp_dir, "video.mp4"),
                                           preset=settings.ffmpeg_preset)
        else:
            video = media.concat_videos(norm_clips, ws.path(tmp_dir, "video.mp4"))
        narration = media.concat_audio(narr_parts, ws.path(tmp_dir, "narration.wav"))

        style = preset["subtitle"]
        if song:  # subtitles follow the sung lyrics, not the narration
            cues = planner.parse_lyrics(opts.get("lyrics") or "", offset)
        else:
            cues = subtitles.build_cues(timings, style)
        ws.path(f"{out_name}.srt").write_text(subtitles.to_srt(cues), encoding="utf-8")
        ass_name = None
        if opts.get("burn_subtitles") and cues:
            ws.path(f"{out_name}.ass").write_text(subtitles.to_ass(cues, style, preset["width"], preset["height"]),
                                                  encoding="utf-8")
            ass_name = f"{out_name}.ass"

        music = None
        if opts.get("music_mode") != "none" and opts.get("music_file") and ws.path(opts["music_file"]).exists():
            music = ws.path(opts["music_file"])
        self._progress(job, 0.95, "Mixing audio & subtitle…")
        tmp_final = ws.path(tmp_dir, f"{out_name}.mp4")
        volume = 1.0 if song else float(opts.get("music_volume") or 0.25)  # a song is the main audio
        media.compose_final(video, narration, tmp_final, total_seconds=offset, music=music,
                            music_volume=volume, keep_clip_audio=keep_audio,
                            subtitles_ass=ass_name, preset=settings.ffmpeg_preset, cwd=ws.root)
        shutil.move(str(tmp_final), str(ws.path(f"{out_name}.mp4")))
        for leftover in ws.path(tmp_dir).glob("*"):
            leftover.unlink(missing_ok=True)
        return {"duration": round(offset, 2), "scenes": len(scenes), "cues": len(cues),
                "files": [f"{out_name}.mp4", f"{out_name}.srt"]}

