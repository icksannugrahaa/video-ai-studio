"""Job execution: plan, edit-by-prompt, render, regenerate.

Every step persists its result per scene (clip file + version, narration
audio + timings), so a job interrupted by a restart resumes and skips work
that is already done. Upstream/ffmpeg errors surface as job messages; API
keys never appear in them.
"""

from __future__ import annotations

import base64
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
from app.pipeline import media, planner, presets, rig, subtitles
from app.pipeline.text import split_sentences
from app.providers import ProviderClient, ProviderError
from app.repo import Repo
from app.security import SecretBox

log = logging.getLogger("sav.engine")
CLIP_ATTEMPTS = 3
# Back-off before retry 2 and 3: upstream rate limits / busy queues need time,
# instant retries just fail the same way (seen live: CodeBuddy 429 bursts).
CLIP_RETRY_DELAYS = (30, 90)
# Back-off before asking the chat model about a last frame again: a skipped check let a
# wrong first clip seed a whole chain (router accounts in cooldown, seen live).
END_CHECK_DELAYS = (20, 60)
KEYFRAME_TRIES = 3  # image-model attempts per keyframe before the clip goes without it
UNCHECKED_NOTE = ("Frame terakhir belum dicek: model chat tidak menjawab. Periksa clip ini, "
                  "scene berikutnya dimulai dari frame terakhirnya.")
NARRATION_TAIL = 0.4  # seconds of breathing room after the last sentence
SEAM_DISSOLVE = 0.2  # seconds, continuing shots
GAIN_LIMIT = 0.15  # most a chain's colour may be corrected
MAX_SLOWDOWN = 1.15  # more than this is noticeable
MIN_STILL_TAIL = 0.5  # seconds; a shorter hold reads as a natural beat
MIN_CUT_TAIL = 0.12  # seconds; before a continuing cut even a short hold reads as a stop


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


def render_fps(clips: list[Path], default: int) -> float:
    """Keep the clips' own motion rate when they share one at or below the
    configured rate: converting 24 fps motion to 30 fps repeats every 5th frame,
    which shows as a steady stutter."""
    rates = {round(media.motion_fps(c), 3) for c in clips if c.exists()}
    rate = rates.pop() if len(rates) == 1 else 0.0
    return rate if 0 < rate <= default else float(default)


def scene_transitions(scenes: list[dict], lengths: list[float], options: dict,
                      broken: frozenset | set = frozenset()) -> list[float]:
    """Crossfade seconds after each scene (last is 0). A shot that continues the
    previous one starts from its last frame, but models re-render that frame, so
    it gets just a short dissolve to hide the twitch; a full fade when the seam
    after scene ``i`` is in ``broken`` (the clip left its seed). Fades are capped
    at a third of the shorter neighbouring scene."""
    try:
        wanted = max(0.0, min(1.5, float(options.get("transition", 0.5) or 0)))
    except (TypeError, ValueError):
        wanted = 0.5
    fades = []
    for i in range(len(scenes)):
        if i == len(scenes) - 1 or not wanted:
            fades.append(0.0)
            continue
        fade = min(wanted, SEAM_DISSOLVE) if scenes[i + 1].get("continues") and i not in broken else wanted
        fades.append(round(min(fade, lengths[i] / 3, lengths[i + 1] / 3), 3))
    return fades


def trimmed_end(clip_seconds: float, active: float, target: float,
                min_tail: float = MIN_STILL_TAIL) -> float | None:
    """Where to end a clip that holds its pose after ``active`` seconds so the rest,
    slowed down at most ``MAX_SLOWDOWN``, still fills ``target``. ``None`` = keep it."""
    end = max(active, target / MAX_SLOWDOWN)
    return round(end, 3) if end < target and clip_seconds - end >= min_tail else None


def chain_gains(seams: list[tuple[float, float, float] | None]) -> list[tuple[float, float, float]]:
    """Colour gain per scene from the gain each seam needs (``None`` = the next
    scene is not seeded, so its chain starts clean). A chain is carried along so
    every clip lands on the colour of the one before it; capped because a larger
    difference is a real change of picture, not a colour shift."""
    gains = [(1.0, 1.0, 1.0)]
    for seam in seams:
        gains.append(tuple(max(1 - GAIN_LIMIT, min(1 + GAIN_LIMIT, g * s))
                           for g, s in zip(gains[-1], seam)) if seam else (1.0, 1.0, 1.0))
    return gains


def _bible_options(board: dict) -> dict:
    """Project option updates for a planner result's bible (empty fields skipped,
    so an edit that drops the bible keeps the stored one)."""
    bible = board.get("bible") or {}
    options = {f"bible_{key}": bible[key] for key in planner.BIBLE_KEYS if bible.get(key)}
    if board.get("concept"):  # what the video promises: edits keep building on it
        options["concept"] = board["concept"]
    return options


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
        project = self._song_first(job, project, profile, client)
        self._progress(job, 0.3, "Menyusun storyboard…")
        ws = Workspace(self.settings.projects_dir, project["id"])
        music = self._music_path(project, ws) if self._is_song(project) else None
        lyrics = project["options"].get("lyrics") or "" if self._is_song(project) else ""
        board = planner.plan_storyboard(
            client, profile["chat_model"], prompt=project["prompt"], language=project["language"],
            clip_seconds=int(profile["clip_seconds"]), target_seconds=int(project["target_seconds"]),
            limit_seconds=int(preset["max_seconds"]), aspect=preset["aspect"], song=self._is_song(project),
            lyrics=lyrics, song_seconds=media.audible_end(music) if music else None,
        )
        diff = self.repo.replace_scenes(project["id"], board["scenes"])
        update = {"status": "planned"}
        if board["title"] and not project["title"]:
            update["title"] = board["title"]
        update["options"] = _bible_options(board)
        if board.get("music_prompt") and not lyrics:  # a song prompt carries the lyrics: keep it
            update["options"]["music_prompt"] = board["music_prompt"]
        self.repo.update_project(job["user_id"], project["id"], update)
        return {"scenes": len(board["scenes"]), **diff}

    def _song_first(self, job, project, profile, client) -> dict:
        """Song mode: the scenes follow the lyrics, so missing lyrics come first. If
        they cannot be written the storyboard is still planned from the idea and
        the button (or the render) writes them later."""
        if not self._is_song(project) or (project["options"].get("lyrics") or "").strip():
            return project
        self._progress(job, 0.1, "Menulis lirik & prompt musik…")
        try:
            song = planner.song_from_idea(client, profile["chat_model"], idea=project["prompt"],
                                          language=project["language"], seconds=int(project["target_seconds"]))
        except (ProviderError, planner.PlanError) as exc:
            log.warning("project %s lyrics not written: %s", project["id"], type(exc).__name__)
            return project
        self.repo.update_project(job["user_id"], project["id"], {"options": song})
        return self.repo.project(job["user_id"], project["id"]) or project

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
                   "concept": opts.get("concept") or {},
                   "bible": {key: opts.get(f"bible_{key}") or "" for key in planner.BIBLE_KEYS},
                   "scenes": [{"visual_prompt": s["visual_prompt"], "continues": s["continues"],
                               "narration": s["narration"], "duration": s["duration"]}
                              for s in self.repo.scenes(project["id"])]}
        self._progress(job, 0.05, "Menerapkan instruksi edit…")
        board = planner.edit_storyboard(
            client, profile["chat_model"], storyboard=current, instruction=instruction,
            language=project["language"], clip_seconds=int(profile["clip_seconds"]),
            limit_seconds=int(preset["max_seconds"]), aspect=preset["aspect"], song=self._is_song(project),
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
            project = self._ensure_song(job, project, profile, client, scenes)
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

    def _ensure_song(self, job, project, profile, client, scenes) -> dict:
        """Song mode: fill in missing lyrics / music prompt before any clip is billed,
        since each clip is directed by the lines sung during it. Lyrics the user
        already has are kept."""
        opts = project["options"]
        if not self._is_song(project):
            return project
        lyrics, prompt = (opts.get("lyrics") or "").strip(), (opts.get("music_prompt") or "").strip()
        if lyrics and prompt:
            return project
        if lyrics:
            total = int(round(sum(float(s["duration"]) for s in scenes)))
            update = {"music_prompt": planner.song_prompt(
                style=f'Song for the video "{project["title"] or project["prompt"][:80]}"', vocal="",
                lyrics=lyrics, total=total)}
        else:
            if not profile["chat_model"]:
                raise JobFailed("profil belum memilih model chat (dibutuhkan untuk membuat lirik)")
            self._progress(job, self.repo.job(job["id"])["progress"], "Menulis lirik & prompt musik…")
            update = planner.song_plan(client, profile["chat_model"], title=project["title"], scenes=scenes,
                                       language=project["language"])
        self.repo.update_project(job["user_id"], project["id"], {"options": update})
        return self.repo.project(job["user_id"], project["id"]) or project

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
        work_chains = [c for c in chains if any(s["id"] in todo_ids for s in c)]
        state = {"done": 0, "running": 0, "total": len(todo_ids)}
        lock = threading.Lock()
        stop = threading.Event()  # first failure: no chain starts a new (billed) clip

        def report(note: str) -> None:
            with lock:
                n, running, total = state["done"], state["running"], state["total"]
            extra = f" · {running} berjalan paralel" if running > 1 else ""
            self._progress(job, p0 + (p1 - p0) * n / total, f"{note}{extra}")

        def run_chain(chain: list[dict]) -> None:
            remade = False  # the previous clip of this chain changed in this job
            counting: dict = {}  # rig per counted noun, built once a clip of the chain ends right
            for scene in chain:
                if stop.is_set():
                    return
                if scene["id"] not in todo_ids:
                    if not remade or not self._seed_went_stale(project, scene, ws):
                        remade = False
                        continue
                    # Its seed was replaced and it no longer connects. Bumping the
                    # version first lets a resumed job finish the remake.
                    scene = {**scene, "version": scene["version"] + 1}
                    self.repo.update_scene(scene["id"], version=scene["version"])
                    with lock:
                        state["total"] += 1
                remade = True
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
                    # A continuing counting shot starts and ends on frames drawn with
                    # the exact count, so one wrong clip is not carried into the next.
                    drawn = (self._rig_frames(job, project, profile, client, chain, scene, ws, counting)
                             if seed is not None else None)
                    if drawn:
                        seed, last = drawn
                    else:
                        seed, last = self._keyframes(job, project, profile, client, preset, scene, ws, seed)
                    self._generate_one(job, project, profile, client, preset, scene, ws, seed, last)
                    self._retake_broken(job, project, profile, client, preset, scene, ws, seed, last)
                except BaseException:
                    stop.set()
                    raise
                finally:
                    with lock:
                        state["running"] -= 1
                with lock:
                    state["done"] += 1
                    n, total = state["done"], state["total"]
                report(f"Clip {n}/{total} selesai")

        # One clip at a time unless the project opts in: the phone server cannot
        # take several video jobs at once. SAV_CLIP_CONCURRENCY caps the opt-in.
        limit = self.settings.clip_concurrency if project["options"].get("parallel_clips") else 1
        lanes = max(1, min(limit, len(work_chains)))
        report(f"Generate {len(todo_ids)} clip" + (f" ({lanes} jalur paralel)" if lanes > 1 else "") + "…")
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

    def _generate_one(self, job, project, profile, client, preset, scene, ws, seed, last=None) -> None:
        self.repo.update_scene(scene["id"], clip_status="running", clip_error=None)
        last_error = None
        started = time.monotonic()  # generation time shown per clip (includes retries/back-off)
        for attempt in range(1, CLIP_ATTEMPTS + 1):
            try:
                video = self._request_clip(job, project, profile, client, preset, scene, ws, seed, last)
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

    def _request_clip(self, job, project, profile, client, preset, scene, ws, seed, last=None):
        parts = planner.clip_prompt_parts(project["options"], scene["visual_prompt"],
                                          sung=self._sung_during(project, scene, ws), seeded=seed is not None,
                                          previous=self._previous_shot(project, scene),
                                          correction=scene.get("correction") or "",
                                          ends_on_image=last is not None and seed is not None)
        limit = planner.prompt_limit(profile["video_model"])
        prompt = planner.fit_prompt(parts, limit)
        full = planner.prompt_sizes(parts)[0]
        if len(prompt) < full:
            log.info("scene %s prompt trimmed %s -> %s chars (model limit %s)", scene["idx"], full, len(prompt), limit)
        return client.generate_video(
            profile["video_model"], prompt,
            seconds=self._clip_seconds(project, profile, scene, ws),
            aspect_ratio=preset["model_aspect"], image_png=seed, last_png=last if seed is not None else None,
            enable_audio=bool(project["options"].get("keep_clip_audio")),
            should_cancel=lambda: self.repo.job_status(job["id"]) == "canceled",
        )

    def _previous_shot(self, project: dict, scene: dict) -> str:
        prev = next((s for s in self.repo.scenes(project["id"]) if s["idx"] == scene["idx"] - 1), None)
        return prev["visual_prompt"] if prev else ""

    def _previous_clip(self, project: dict, scene: dict, ws) -> Path | None:
        prev = next((s for s in self.repo.scenes(project["id"]) if s["idx"] == scene["idx"] - 1), None)
        return ws.path(prev["clip_file"]) if prev and prev.get("clip_file") else None

    def _seed_went_stale(self, project: dict, scene: dict, ws) -> bool:
        prev = self._previous_clip(project, scene, ws)
        try:
            return bool(prev) and media.seam_gap(prev, ws.path(scene["clip_file"])) > media.SEAM_BREAK
        except media.MediaError:
            return False

    def _end_state_problems(self, job, profile, client, scene, clip: Path, checks: dict | None) -> list[str] | None:
        """What the clip's last frame lacks compared to its END. It seeds the next
        clip, so whatever is lost here stays lost. ``None`` when the chat model gave
        no usable answer after a few tries: unknown, never "fine"."""
        if not checks or not (profile.get("vision_model") or profile["chat_model"]):
            return []
        frame = clip.with_name(f"{clip.stem}_end.jpg")
        try:
            media.last_frame_png(clip, frame)
        except media.MediaError:
            log.warning("scene %s end state check skipped: last frame unreadable", scene["idx"])
            frame.unlink(missing_ok=True)
            return None
        try:
            return self._frame_problems(job, profile, client, scene, frame, checks)
        finally:
            frame.unlink(missing_ok=True)

    def _frame_problems(self, job, profile, client, scene, frame: Path, checks: dict | None) -> list[str] | None:
        """Ask the vision model (else the chat model) what one frame shows against
        ``checks``; ``None`` when it gave no usable answer after a few tries."""
        if not checks or not (profile.get("vision_model") or profile["chat_model"]):
            return []
        reply = self._ask_frame(job, profile, client, scene, frame, planner.end_question(checks))
        return None if reply is None else planner.end_problems(checks, reply)

    def _ask_frame(self, job, profile, client, scene, frame: Path, question: str,
                   delays: tuple = None) -> dict | None:
        """The vision model's (else the chat model's) JSON answer about one frame;
        ``None`` when it gave no usable answer after a few tries."""
        model = profile.get("vision_model") or profile["chat_model"]
        if not model:
            return None
        delays = END_CHECK_DELAYS if delays is None else delays
        mime = "image/png" if frame.suffix == ".png" else "image/jpeg"
        image = f"data:{mime};base64," + base64.b64encode(frame.read_bytes()).decode("ascii")
        for attempt in range(len(delays) + 1):
            if attempt:
                self._sleep(job, delays[attempt - 1])
            try:
                reply = client.chat(model, [{"role": "user", "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": image}}]}], temperature=0)
                return planner.extract_json(reply)
            except ProviderError as exc:
                if exc.status == 499:
                    raise
                reason = f"provider {exc.status}"
            except planner.PlanError:
                reason = "no JSON answer"
            log.warning("scene %s frame check attempt %s failed (%s)", scene["idx"], attempt + 1, reason)
        return None

    # counting rig -------------------------------------------------------
    def _rig_frames(self, job, project, profile, client, chain, scene, ws, state: dict):
        """(first, last) frames drawn by :mod:`rig` for a continuing counting shot:
        exactly the count its START and END name, cut from the last clip of the
        sequence that was checked to end right. ``None`` → the usual frames."""
        counts = planner.row_counts(scene["visual_prompt"])
        if not counts or not (profile.get("vision_model") or profile["chat_model"]):
            return None
        first, final, noun = counts
        made = state.get(noun)
        if made is None:
            made = self._build_rig(job, project, profile, client, chain, scene, ws, state, noun)
            if made is None:
                return None
            state[noun] = made
        if not made.count <= first <= final <= made.capacity:
            return None
        out = []
        for kind, count in (("start", first), ("end", final)):
            if kind == "end" and final == first:
                out.append(None)
                continue
            path = ws.path("keyframes", f"scene_{scene['idx']}_v{scene['version']}_rig_{kind}.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(rig.compose(made, count))
            out.append(path.read_bytes())
        log.info("scene %s: rig frames %s -> %s %s", scene["idx"], first, final, noun)
        return out[0], out[1]

    def _build_rig(self, job, project, profile, client, chain, scene, ws, state: dict, noun: str):
        """A rig from the latest earlier clip of the chain whose end was checked and
        counted right (a container the vision model did not recognise does not
        matter here) with a row of ``noun``; each clip is tried once per job."""
        total = max((c[1] for s in chain if (c := planner.row_counts(s["visual_prompt"])) and c[2] == noun),
                    default=0)
        current = {s["id"]: s for s in self.repo.scenes(project["id"])}
        tried = state.setdefault("_tried", set())
        for s in reversed([current[c["id"]] for c in chain if c["idx"] < scene["idx"] and c["id"] in current]):
            checks = planner.end_checks(s["visual_prompt"])
            if (s["clip_status"] != "done" or not planner.count_right(s.get("clip_error")) or not s.get("clip_file")
                    or not ws.path(s["clip_file"]).exists() or not checks or checks["noun"] != noun
                    or not checks["count"] or s["clip_file"] in tried):
                continue
            tried.add(s["clip_file"])
            self._progress(job, self.repo.job(job["id"])["progress"],
                           f"Scene {scene['idx'] + 1}: menyiapkan frame hitungan dari scene {s['idx'] + 1}…")
            made = self._rig_from(job, profile, client, s, ws, checks, total)
            if made is not None:
                return made
        return None

    def _rig_from(self, job, profile, client, scene, ws, checks: dict, total: int):
        clip = ws.path(scene["clip_file"])
        try:
            after = media.last_frame_png(clip, ws.path("frames", f"scene_{scene['idx']}_last.png"))
            before = media.first_frame_png(clip, ws.path("frames", f"scene_{scene['idx']}_first.png"))
            width, height = media.image_size(after)
        except media.MediaError:
            return None
        container = next(iter(checks.get("visible") or []), None)
        reply = self._ask_frame(job, profile, client, scene, after, planner.boxes_question(checks["noun"], container),
                                delays=(5,))
        if reply is None:
            return None
        boxes = rig.parse_boxes(reply.get("objects"), width, height)
        if len(boxes) != checks["count"]:
            log.info("scene %s rig: %s boxes for %s %s", scene["idx"], len(boxes), checks["count"], checks["noun"])
            return None
        holder = rig.parse_boxes([reply.get("container")], width, height)
        surface = rig.parse_boxes([reply.get("surface")], width, height)
        try:
            made = rig.build(after.read_bytes(), before.read_bytes(), boxes, holder[0] if holder else None,
                             total=total, surface=surface[0] if surface else None)
            sample = ws.path("keyframes", f"rig_scene_{scene['idx']}_full.png")
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_bytes(rig.compose(made, made.capacity))
        except rig.RigError as exc:
            log.info("scene %s rig not usable: %s", scene["idx"], exc)
            return None
        # the fullest row it can draw must read right too (a wrong box shows here)
        found = self._frame_problems(job, profile, client, scene, sample,
                                     {"count": made.capacity, "noun": checks["noun"], "visible": []})
        if found:
            log.info("scene %s rig rejected: %s", scene["idx"], ", ".join(found))
            return None
        log.info("scene %s rig ready: %s -> %s %s", scene["idx"], made.count, made.capacity, checks["noun"])
        return made

    # keyframes ----------------------------------------------------------
    def _keyframes(self, job, project, profile, client, preset, scene, ws, seed):
        """(first, last) frame for the clip. With an image model, a shot with no frame
        to start from gets a checked first frame drawn from its START, and a counting
        step gets a checked last frame edited from its first one, so the video model
        only moves between two right pictures. Anything that fails → the plain clip."""
        if not profile.get("image_model"):
            return seed, None
        shot, opts = scene["visual_prompt"], project["options"]
        if seed is None:
            checks = planner.start_checks(shot)
            if not (checks and planner.has_bible(opts)):
                return None, None
            width, height = preset["width"], preset["height"]
            size = "1536x1024" if width > height else "1024x1536" if height > width else "1024x1024"
            seed = self._keyframe(job, profile, client, scene, ws, "start", checks, (width, height),
                                  lambda: client.generate_image(profile["image_model"],
                                                                planner.start_frame_prompt(opts, shot), size=size))
            if seed is None:
                return None, None
        if not planner.moves_objects(shot):
            return seed, None
        checks = planner.sequence_checks(self.repo.scenes(project["id"]), scene)
        if not checks:
            return seed, None
        frame = ws.path("keyframes", f"scene_{scene['idx']}_seed.png")
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(seed)
        try:
            size = media.image_size(frame)
        except media.MediaError:
            return seed, None
        last = self._keyframe(job, profile, client, scene, ws, "end", checks, size,
                              lambda: client.edit_image(profile["image_model"], seed,
                                                        planner.end_frame_prompt(opts, shot)))
        return seed, last

    def _keyframe(self, job, profile, client, scene, ws, kind: str, checks: dict, size: tuple[int, int],
                  make) -> bytes | None:
        """One keyframe, made at most ``KEYFRAME_TRIES`` times until the chat model
        confirms it shows ``checks``; kept per scene version so a resumed job
        reuses it. ``None`` when no try passed (or the check could not run)."""
        path = ws.path("keyframes", f"scene_{scene['idx']}_v{scene['version']}_{kind}.png")
        if path.exists():
            return path.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = path.with_suffix(".raw")
        label = "awal" if kind == "start" else "akhir"
        for attempt in range(1, KEYFRAME_TRIES + 1):
            self._progress(job, self.repo.job(job["id"])["progress"],
                           f"Scene {scene['idx'] + 1}: membuat frame {label} ({attempt}/{KEYFRAME_TRIES})…")
            try:
                raw.write_bytes(make())
                media.fit_image(raw, path, *size)
            except ProviderError as exc:
                if exc.status == 499:
                    raise JobCanceled() from exc
                log.warning("scene %s %s keyframe attempt %s failed (%s)", scene["idx"], kind, attempt, exc.status)
                if not exc.retryable:
                    break
                continue
            except media.MediaError:
                log.warning("scene %s %s keyframe attempt %s unreadable", scene["idx"], kind, attempt)
                continue
            finally:
                raw.unlink(missing_ok=True)
            problems = self._frame_problems(job, profile, client, scene, path, checks)
            if problems == []:
                log.info("scene %s %s keyframe ok (attempt %s)", scene["idx"], kind, attempt)
                return path.read_bytes()
            log.info("scene %s %s keyframe attempt %s rejected: %s", scene["idx"], kind, attempt,
                     ", ".join(problems) if problems else "not checked")
            path.unlink(missing_ok=True)
            if problems is None:
                break
        log.warning("scene %s: no %s keyframe, clip made without it", scene["idx"], kind)
        return None

    def _retake_broken(self, job, project, profile, client, preset, scene, ws, seed, last=None) -> None:
        """A clip that left its seed or ends without what its shot promises gets one
        more (billed) try; the better of the two stays and what is still wrong is
        shown on the scene. The first clip is already saved, so a failed retake
        costs nothing. A last frame the chat model could not check is flagged on
        the scene (no retake is billed on a guess)."""
        prev = self._previous_clip(project, scene, ws)
        scenes = self.repo.scenes(project["id"])
        first = next(s for s in scenes if s["id"] == scene["id"])
        checks = planner.sequence_checks(scenes, first)

        def flaws(clip: Path) -> tuple[list[str] | None, float]:
            gap = media.seam_gap(prev, clip) if seed is not None and prev else 0.0
            return self._end_state_problems(job, profile, client, scene, clip, checks), gap

        def note(found: list[str] | None) -> str | None:
            if found is None:
                return UNCHECKED_NOTE
            return f"Frame terakhir: {', '.join(found)}"[:300] if found else None

        left: list[str] | None = []
        try:
            left, gap = flaws(ws.path(first["clip_file"]))
            if not left and gap <= media.SEAM_BREAK:
                return
            self._progress(job, self.repo.job(job["id"])["progress"],
                           f"Scene {scene['idx'] + 1} tidak sesuai, generate ulang sekali…")
            self.repo.update_scene(scene["id"], clip_status="running")  # the UI must not show it as finished
            video = self._request_clip(job, project, profile, client, preset, scene, ws, seed, last)
            name = f"clips/scene_{scene['idx']}_v{scene['version']}_retake.{video.ext}"
            ws.path(name).write_bytes(video.data)
            retake_left, retake_gap = flaws(ws.path(name))
            closer = (bool(retake_left), retake_gap) < (bool(left), gap)
            if closer:
                left = retake_left
        except ProviderError as exc:
            if exc.status == 499:
                raise JobCanceled() from exc
            log.warning("scene %s retake failed", scene["idx"])
            return
        except media.MediaError:
            log.warning("scene %s retake unreadable", scene["idx"])
            return
        finally:
            self.repo.update_scene(scene["id"], clip_status="done", clip_error=note(left))
        loser = first["clip_file"] if closer else name
        if closer:
            self.repo.update_scene(scene["id"], clip_file=name, clip_attempts=(first["clip_attempts"] or 0) + 1)
        ws.path(loser).unlink(missing_ok=True)

    def _seam(self, project: dict, scenes: list[dict], i: int, ws) -> int | None:
        """Frames of clip ``i`` to keep so it ends where the next, seeded clip
        starts (see :func:`media.seam_frames`); ``None`` = keep everything."""
        if i + 1 >= len(scenes) or not project["options"].get("continuity"):
            return None
        nxt = scenes[i + 1]
        if not (nxt.get("continues") or not planner.has_bible(project["options"])):
            return None  # not seeded from this clip
        if nxt["idx"] != scenes[i]["idx"] + 1 or not nxt.get("clip_file"):
            return None  # partial preview with a gap: the clips are not neighbours
        try:
            return media.seam_frames(ws.path(scenes[i]["clip_file"]), ws.path(nxt["clip_file"]),
                                     fps=media.video_fps(ws.path(scenes[i]["clip_file"])) or 24.0)
        except media.MediaError:
            return None

    def _broken_seams(self, project: dict, scenes: list[dict], ws) -> set[int]:
        """Seams after scene ``i`` where the seeded next clip does not match."""
        broken = set()
        for i in range(len(scenes) - 1):
            nxt = scenes[i + 1]
            if nxt.get("continues") and nxt["idx"] == scenes[i]["idx"] + 1 and nxt.get("clip_file"):
                try:
                    if media.seam_broken(ws.path(scenes[i]["clip_file"]), ws.path(nxt["clip_file"])):
                        broken.add(i)
                except media.MediaError:
                    pass
        return broken

    def _seam_gains(self, scenes: list[dict], ws) -> list[tuple[float, float, float]]:
        seams: list[tuple[float, float, float] | None] = []
        for i in range(len(scenes) - 1):
            nxt, gain = scenes[i + 1], None
            if nxt.get("continues") and nxt["idx"] == scenes[i]["idx"] + 1 and nxt.get("clip_file"):
                try:
                    gain = media.seam_colour_gain(ws.path(scenes[i]["clip_file"]), ws.path(nxt["clip_file"]))
                except media.MediaError:
                    pass
            seams.append(gain)
        return chain_gains(seams)

    @staticmethod
    def _music_path(project: dict, ws) -> Path | None:
        opts = project["options"]
        if opts.get("music_mode") != "none" and opts.get("music_file") and ws.path(opts["music_file"]).exists():
            return ws.path(opts["music_file"])
        return None

    def _song_timeline(self, project: dict, scenes: list[dict], ws) -> list[float] | None:
        """Song mode: scene lengths set by the song, so its whole length is used and
        it never gets cut or looped. ``None`` while there is no way to tell."""
        if not self._is_song(project):
            return None
        music = self._music_path(project, ws)
        seconds = media.audible_end(music) if music else None
        lengths = planner.song_lengths(scenes, project["options"].get("lyrics") or "", seconds)
        if not lengths and seconds:
            lengths = planner.fit_lengths([float(s["duration"]) for s in scenes], seconds)
        return lengths

    def _clip_seconds(self, project: dict, profile: dict, scene: dict, ws) -> int:
        """Length to request: the part of the song this clip covers, when known."""
        limit = int(profile["clip_seconds"])
        ordered = sorted(self.repo.scenes(project["id"]), key=lambda s: s["idx"])
        timeline = self._song_timeline(project, ordered, ws)
        at = next(i for i, s in enumerate(ordered) if s["idx"] == scene["idx"])
        wanted = min(timeline[at], limit) if timeline else scene["duration"]
        return max(int(round(wanted)), planner.min_clip_seconds(limit))

    def _sung_during(self, project: dict, scene: dict, ws) -> str:
        """Song mode: the lyric lines (and tempo) heard during this scene, so the
        clip acts out what is sung instead of a generic dance."""
        if not self._is_song(project):
            return ""
        ordered = sorted(self.repo.scenes(project["id"]), key=lambda s: s["idx"])
        lengths = self._song_timeline(project, ordered, ws) or [float(s["duration"]) for s in ordered]
        at = next(i for i, s in enumerate(ordered) if s["idx"] == scene["idx"])
        start = sum(lengths[:at])
        return planner.sung_direction(project["options"], start, start + lengths[at])

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
        music = self._music_path(project, ws)
        # Song mode: the uploaded song sets the timeline, not the planned durations.
        timeline = self._song_timeline(project, scenes, ws) if song and music else None
        if timeline:
            lengths = timeline
        fades = ([0.0] * len(scenes) if not media.has_filter("xfade")
                 else scene_transitions(scenes, lengths, opts, self._broken_seams(project, scenes, ws)))
        fps = render_fps([ws.path(s["clip_file"]) for s in scenes if s.get("clip_file")], settings.render_fps)
        gains = self._seam_gains(scenes, ws)
        p_start = max(0.3, self.repo.job(job["id"])["progress"])
        for n, scene in enumerate(scenes, 1):
            self._progress(job, p_start + (0.92 - p_start) * (n - 1) / len(scenes),
                           f"Menyiapkan scene {n}/{len(scenes)}…")
            info = {} if song else (scene.get("narration_info") or {})
            seconds = lengths[n - 1]
            # Faded sides need half a fade of extra picture (fades are centred on the cut).
            clip_seconds = media.crossfade_clip_seconds(lengths, fades, n - 1)
            lead = fades[n - 2] / 2 if n > 1 else 0.0
            retime = seconds if timeline else None
            active = None
            if n < len(scenes):
                try:
                    src = ws.path(scene["clip_file"])
                    active = trimmed_end(media.duration(src), media.active_seconds(src), retime or seconds)
                    if active is None and scenes[n].get("continues"):
                        # the next shot starts from this pose and moves at once: a held
                        # end reads as a stop before every cut, however short
                        clip = media.duration(src)
                        active = trimmed_end(clip, clip - media.still_tail(src), retime or seconds,
                                             min_tail=MIN_CUT_TAIL)
                except media.MediaError:
                    pass
            retime = (retime or seconds) if active else retime
            if retime and lead:
                # the clip starts under the incoming fade: play its first frame there
                # instead of holding it still (a held head reads as a stall at every cut)
                retime = round(retime + lead, 3)
            keep_frames = None if retime or fades[n - 1] else self._seam(project, scenes, n - 1, ws)
            key = hashlib.sha1(f"{media.NORMALIZE_VERSION}|{scene['clip_file']}|{clip_seconds}|{lead}|{keep_frames}|{retime}|"
                               f"{preset['width']}x{preset['height']}|"
                               f"{fps:g}|{keep_audio}|{gains[n - 1]}|{active}".encode()).hexdigest()[:10]
            norm = ws.path("norm", f"scene_{scene['idx']}_{key}.mp4")
            if not norm.exists():
                # Write under a unique name then rename: a preview and a render may
                # normalise the same clip at the same moment.
                part = norm.with_name(f"{norm.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
                media.normalize_clip(ws.path(scene["clip_file"]), part, width=preset["width"],
                                     height=preset["height"], fps=fps, seconds=clip_seconds,
                                     keep_audio=keep_audio, preset=settings.ffmpeg_preset, lead=lead,
                                     keep_frames=keep_frames, retime=retime,
                                     gain=None if gains[n - 1] == (1.0, 1.0, 1.0) else gains[n - 1], active=active)
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

