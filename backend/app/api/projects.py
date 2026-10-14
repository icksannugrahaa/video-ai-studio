"""Projects, storyboard scenes, jobs, music upload and output files."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import current_user, services
from app.pipeline import planner, presets
from app.providers import ProviderError

router = APIRouter()
MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MUSIC_MAX_BYTES = 30 * 1024 * 1024
_FILE_RE = re.compile(r"^((final|preview)\.(mp4|srt)|clips/scene_\d+_v\d+\.mp4|music\.(mp3|wav|m4a|aac|ogg|flac))$")
_MEDIA_TYPES = {".srt": "text/plain; charset=utf-8", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
                ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac"}


class Options(BaseModel):
    continuity: bool | None = None
    burn_subtitles: bool | None = None
    keep_clip_audio: bool | None = None
    music_volume: float | None = Field(default=None, ge=0, le=1)
    voice: str | None = Field(default=None, max_length=120)
    music_mode: str | None = Field(default=None, pattern="^(none|external|generate)$")
    music_prompt: str | None = Field(default=None, max_length=6000)
    music_style: str | None = Field(default=None, pattern="^(instrumental|song)$")
    lyrics: str | None = Field(default=None, max_length=6000)
    bible_character: str | None = Field(default=None, max_length=1200)
    bible_world: str | None = Field(default=None, max_length=1200)
    bible_style: str | None = Field(default=None, max_length=600)
    transition: float | None = Field(default=None, ge=0, le=1.5)


class ProjectBody(BaseModel):
    title: str = Field(default="", max_length=120)
    prompt: str = Field(default="", max_length=8000)
    preset: str = "tiktok"
    target_seconds: int = Field(default=30, ge=5, le=3600)
    language: str = Field(default="id-ID", max_length=20)
    profile_id: int | None = None
    options: Options | None = None


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=8000)
    preset: str | None = None
    target_seconds: int | None = Field(default=None, ge=5, le=3600)
    language: str | None = Field(default=None, max_length=20)
    profile_id: int | None = None
    options: Options | None = None


class SceneBody(BaseModel):
    visual_prompt: str = Field(min_length=1, max_length=2000)
    narration: str = Field(default="", max_length=2000)
    duration: float = Field(ge=1, le=30)
    continues: bool = False  # starts from the previous clip's last frame (same place & moment)


class ScenesBody(BaseModel):
    scenes: list[SceneBody] = Field(min_length=1, max_length=200)


class RenderBody(BaseModel):
    confirm: bool = False


class EditBody(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


class ComposeBody(BaseModel):
    partial: bool = False  # preview.mp4 from the clips that are ready


class MusicPromptBody(BaseModel):
    hint: str = Field(default="", max_length=500)


def _project(svc, user: dict, project_id: int) -> dict:
    project = svc.repo.project(user["id"], project_id)
    if not project:
        raise HTTPException(404, "project tidak ditemukan")
    return project


def _validate(svc, user: dict, data: dict) -> dict:
    if data.get("preset") is not None and data["preset"] not in presets.PRESETS:
        raise HTTPException(400, "preset tidak dikenal")
    if data.get("profile_id") is not None and not svc.repo.profile(user["id"], data["profile_id"]):
        raise HTTPException(400, "profil tidak ditemukan")
    if data.get("options") is not None:
        data["options"] = {k: v for k, v in data["options"].items() if v is not None}
    return data


def _detail(svc, user: dict, project: dict) -> dict:
    scenes = svc.repo.scenes(project["id"])
    root = svc.settings.projects_dir / str(project["id"])
    files = [name for name in ("final.mp4", "final.srt", "preview.mp4", "preview.srt") if (root / name).exists()]
    active = svc.repo.active_job(project["id"])
    if active and active["status"] == "queued":
        active["queue_ahead"] = svc.repo.jobs_ahead(active["id"])
    clips_ready = sum(1 for s in scenes if s["clip_status"] == "done" and s["clip_version"] == s["version"])
    return {**project, "scenes": scenes, "files": files, "clips_ready": clips_ready,
            "active_job": active, "preview_job": svc.repo.latest_preview_job(project["id"]),
            "stats": _stats(svc, user, project, scenes),
            "jobs": [j for j in svc.repo.jobs_for_project(user["id"], project["id"], limit=8)
                     if j["kind"] != "preview"][:5]}


def _stats(svc, user: dict, project: dict, scenes: list[dict]) -> dict:
    """Production summary for the "Ringkasan" card: time spent per job kind,
    clip generation times and the final video. Credits are tracked elsewhere."""
    jobs = svc.repo.jobs_for_project(user["id"], project["id"], limit=500)
    finished = [j for j in jobs if j["status"] in ("succeeded", "failed", "canceled")]
    by_kind: dict[str, dict] = {}
    for job in finished:
        entry = by_kind.setdefault(job["kind"], {"count": 0, "seconds": 0, "failed": 0})
        entry["count"] += 1
        entry["seconds"] += max(0, int(job["updated_at"]) - int(job["created_at"]))
        entry["failed"] += job["status"] != "succeeded"
    timed = [float(s["clip_gen_seconds"]) for s in scenes
             if s["clip_status"] == "done" and s["clip_version"] == s["version"] and s.get("clip_gen_seconds") is not None]
    last_final = next((j for j in jobs if j["status"] == "succeeded" and j["kind"] in ("render", "edit", "regenerate", "compose")
                       and "final.mp4" in ((j.get("result") or {}).get("files") or [])), None)
    return {
        "jobs": by_kind,
        "job_seconds": sum(e["seconds"] for e in by_kind.values()),
        "failed_jobs": sum(e["failed"] for e in by_kind.values()),
        "clips": {"count": len(timed), "total": round(sum(timed), 1),
                  "avg": round(sum(timed) / len(timed), 1) if timed else None,
                  "min": round(min(timed), 1) if timed else None, "max": round(max(timed), 1) if timed else None,
                  "retried": sum(1 for s in scenes if (s.get("clip_attempts") or 1) > 1)},
        "first_at": min((int(j["created_at"]) for j in jobs), default=None),
        "final_at": int(last_final["updated_at"]) if last_final else None,
        "final": (last_final or {}).get("result") or None,
    }


def _queue(svc, user: dict, project: dict, kind: str, payload: dict | None = None) -> dict:
    if svc.repo.active_job(project["id"]):
        raise HTTPException(409, "masih ada job berjalan untuk project ini")
    if not project["profile_id"]:
        raise HTTPException(400, "pilih profil provider dulu")
    job_id = svc.repo.create_job(user["id"], project["id"], kind, payload)
    svc.worker.notify()
    return svc.repo.job(job_id, user["id"])


@router.get("/presets")
def list_presets(svc=Depends(services)):
    return presets.public_list(svc.settings.render_width)


@router.get("/projects")
def list_projects(user: dict = Depends(current_user), svc=Depends(services)):
    """Projects plus a small summary (thumbnail clip, progress) for the dashboard cards."""
    out = []
    for project in svc.repo.projects(user["id"]):
        scenes = svc.repo.scenes(project["id"])
        root = svc.settings.projects_dir / str(project["id"])
        ready = [s for s in scenes if s["clip_status"] == "done" and s["clip_version"] == s["version"]]
        active = svc.repo.active_job(project["id"])
        out.append({**project,
                    "files": [n for n in ("final.mp4", "preview.mp4") if (root / n).exists()],
                    "scene_count": len(scenes), "clips_ready": len(ready),
                    "total_seconds": round(sum(float(s["duration"]) for s in scenes), 1),
                    "thumb_clip": ready[0]["clip_file"] if ready and ready[0]["clip_file"] else None,
                    "active_job": {k: active[k] for k in ("id", "kind", "status", "progress", "message")} if active else None})
    return out


@router.post("/projects")
def create_project(body: ProjectBody, user: dict = Depends(current_user), svc=Depends(services)):
    data = _validate(svc, user, body.model_dump())
    project_id = svc.repo.create_project(user["id"], data)
    return _detail(svc, user, svc.repo.project(user["id"], project_id))


@router.get("/projects/{project_id}")
def get_project(project_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    return _detail(svc, user, _project(svc, user, project_id))


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectPatch, user: dict = Depends(current_user), svc=Depends(services)):
    _project(svc, user, project_id)
    svc.repo.update_project(user["id"], project_id, _validate(svc, user, body.model_dump(exclude_unset=True)))
    return _detail(svc, user, _project(svc, user, project_id))


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    if svc.repo.active_job(project["id"]):
        raise HTTPException(409, "batalkan job yang berjalan dulu")
    svc.repo.delete_project(user["id"], project_id)
    shutil.rmtree(svc.settings.projects_dir / str(project_id), ignore_errors=True)
    return {"ok": True}


@router.put("/projects/{project_id}/scenes")
def put_scenes(project_id: int, body: ScenesBody, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    if svc.repo.active_job(project["id"]):
        raise HTTPException(409, "storyboard tidak bisa diubah saat job berjalan")
    diff = svc.repo.replace_scenes(project_id, [s.model_dump() for s in body.scenes])
    if project["status"] == "draft":
        svc.repo.update_project(user["id"], project_id, {"status": "planned"})
    return {**_detail(svc, user, _project(svc, user, project_id)), "diff": diff}


@router.post("/projects/{project_id}/plan")
def plan(project_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    if not project["prompt"].strip():
        raise HTTPException(400, "isi prompt / ide video dulu")
    return _queue(svc, user, project, "plan")


@router.post("/projects/{project_id}/render")
def render(project_id: int, body: RenderBody, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    scenes = svc.repo.scenes(project_id)
    if not scenes:
        raise HTTPException(400, "storyboard kosong — jalankan Plan dulu")
    pending = [s["idx"] for s in scenes if not (s["clip_status"] == "done" and s["clip_version"] == s["version"])]
    estimate = {"clips_to_generate": len(pending), "scenes": len(scenes), "pending_idx": pending,
                "total_seconds": round(sum(float(s["duration"]) for s in scenes), 1)}
    if not body.confirm:
        return {"estimate": estimate}
    return {"estimate": estimate, "job": _queue(svc, user, project, "render")}


@router.post("/projects/{project_id}/edit")
def edit(project_id: int, body: EditBody, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    if not svc.repo.scenes(project_id):
        raise HTTPException(400, "storyboard kosong — jalankan Plan dulu")
    return _queue(svc, user, project, "edit", {"instruction": body.instruction})


@router.post("/projects/{project_id}/compose")
def compose(project_id: int, body: ComposeBody | None = None, user: dict = Depends(current_user),
            svc=Depends(services)):
    """Re-mix without new clips: ``final.mp4`` (all clips ready) or, with
    ``partial``, ``preview.mp4`` from the clips that are ready so far."""
    project = _project(svc, user, project_id)
    partial = bool(body and body.partial)
    scenes = svc.repo.scenes(project_id)
    ready = [s for s in scenes if s["clip_status"] == "done" and s["clip_version"] == s["version"]]
    if partial and not ready:
        raise HTTPException(400, "belum ada clip yang jadi")
    if not partial and (not scenes or len(ready) != len(scenes)):
        raise HTTPException(400, "semua clip harus sudah jadi — pakai Lanjutkan render atau preview")
    return _queue(svc, user, project, "compose", {"partial": partial})


@router.post("/projects/{project_id}/preview")
def preview(project_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    """"Render sementara": compose the clips that are ready into ``preview.mp4``.
    Runs in its own worker lane, so it also works while a render is going."""
    project = _project(svc, user, project_id)
    if not project["profile_id"]:
        raise HTTPException(400, "pilih profil provider dulu")
    scenes = svc.repo.scenes(project_id)
    if not any(s["clip_status"] == "done" and s["clip_version"] == s["version"] for s in scenes):
        raise HTTPException(400, "belum ada clip yang jadi")
    last = svc.repo.latest_preview_job(project_id)
    if last and last["status"] in ("queued", "running"):
        raise HTTPException(409, "render sementara sedang dibuat")
    job_id = svc.repo.create_job(user["id"], project_id, "preview", {"partial": True})
    svc.worker.notify()
    return svc.repo.job(job_id, user["id"])


@router.post("/projects/{project_id}/music-prompt")
def regenerate_music_prompt(project_id: int, body: MusicPromptBody, user: dict = Depends(current_user),
                            svc=Depends(services)):
    """Write a new music brief now (one chat call, ~30 s). Runs outside the job
    queue so it works while a long render is in progress."""
    project = _project(svc, user, project_id)
    scenes = svc.repo.scenes(project_id)
    if not scenes:
        raise HTTPException(400, "storyboard kosong — jalankan Plan dulu")
    profile = svc.repo.profile(user["id"], project["profile_id"]) if project["profile_id"] else None
    if not profile or not profile["chat_model"]:
        raise HTTPException(400, "profil provider / model chat belum diatur")
    client = svc.client_factory(profile["base_url"], svc.box.decrypt(profile["api_key_enc"]))
    try:
        prompt = planner.music_prompt(client, profile["chat_model"], title=project["title"], scenes=scenes,
                                      hint=body.hint.strip())
    except (ProviderError, planner.PlanError) as exc:
        raise HTTPException(502, getattr(exc, "message", None) or str(exc)) from exc
    svc.repo.update_project(user["id"], project_id, {"options": {"music_prompt": prompt}})
    return _detail(svc, user, _project(svc, user, project_id))


@router.post("/projects/{project_id}/song")
def generate_song(project_id: int, body: MusicPromptBody, user: dict = Depends(current_user),
                  svc=Depends(services)):
    """Write timed lyrics from the scenes + a song prompt (sync, works during a render)."""
    project = _project(svc, user, project_id)
    scenes = svc.repo.scenes(project_id)
    if not scenes:
        raise HTTPException(400, "storyboard kosong — jalankan Plan dulu")
    profile = svc.repo.profile(user["id"], project["profile_id"]) if project["profile_id"] else None
    if not profile or not profile["chat_model"]:
        raise HTTPException(400, "profil provider / model chat belum diatur")
    client = svc.client_factory(profile["base_url"], svc.box.decrypt(profile["api_key_enc"]))
    try:
        song = planner.song_plan(client, profile["chat_model"], title=project["title"], scenes=scenes,
                                 language=project["language"], hint=body.hint.strip())
    except (ProviderError, planner.PlanError) as exc:
        raise HTTPException(502, getattr(exc, "message", None) or str(exc)) from exc
    svc.repo.update_project(user["id"], project_id, {"options": {
        "music_style": "song", "music_mode": "external", "lyrics": song["lyrics"], "music_prompt": song["music_prompt"],
    }})
    return _detail(svc, user, _project(svc, user, project_id))


@router.post("/projects/{project_id}/scenes/{idx}/regenerate")
def regenerate(project_id: int, idx: int, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    if svc.repo.active_job(project["id"]):
        raise HTTPException(409, "masih ada job berjalan untuk project ini")
    if not svc.repo.bump_scene(project_id, idx):
        raise HTTPException(404, "scene tidak ditemukan")
    return _queue(svc, user, project, "regenerate", {"idx": idx})


@router.post("/projects/{project_id}/music")
async def upload_music(project_id: int, file: UploadFile = File(...), user: dict = Depends(current_user),
                       svc=Depends(services)):
    project = _project(svc, user, project_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in MUSIC_EXTS:
        raise HTTPException(400, f"format musik harus salah satu dari {', '.join(sorted(MUSIC_EXTS))}")
    data = await file.read(MUSIC_MAX_BYTES + 1)
    if len(data) > MUSIC_MAX_BYTES:
        raise HTTPException(413, "file musik maksimal 30 MB")
    root = svc.settings.projects_dir / str(project_id)
    root.mkdir(parents=True, exist_ok=True)
    for old in root.glob("music.*"):
        old.unlink(missing_ok=True)
    (root / f"music{ext}").write_bytes(data)
    svc.repo.update_project(user["id"], project_id, {"options": {**project["options"], "music_file": f"music{ext}", "music_mode": "external"}})
    return _detail(svc, user, _project(svc, user, project_id))


@router.delete("/projects/{project_id}/music")
def delete_music(project_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    project = _project(svc, user, project_id)
    root = svc.settings.projects_dir / str(project_id)
    for old in root.glob("music.*"):
        old.unlink(missing_ok=True)
    svc.repo.update_project(user["id"], project_id, {"options": {**project["options"], "music_file": ""}})
    return _detail(svc, user, _project(svc, user, project_id))


@router.get("/projects/{project_id}/files/{name:path}")
def get_file(project_id: int, name: str, user: dict = Depends(current_user), svc=Depends(services)):
    _project(svc, user, project_id)
    if not _FILE_RE.match(name):
        raise HTTPException(404, "file tidak ditemukan")
    root = (svc.settings.projects_dir / str(project_id)).resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "file tidak ditemukan")
    media = _MEDIA_TYPES.get(path.suffix.lower(), "video/mp4")
    return FileResponse(path, media_type=media, filename=f"project{project_id}-{Path(name).name}")


@router.get("/projects/{project_id}/jobs")
def project_jobs(project_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    _project(svc, user, project_id)
    return svc.repo.jobs_for_project(user["id"], project_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    job = svc.repo.job(job_id, user["id"])
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    job = svc.repo.job(job_id, user["id"])
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    if job["status"] in ("queued", "running"):
        svc.repo.update_job(job_id, status="canceled", message="Dibatalkan pengguna")
    return svc.repo.job(job_id, user["id"])
