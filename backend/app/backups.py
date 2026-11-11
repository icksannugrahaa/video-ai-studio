"""Project backups: a snapshot of a project's result that can be put back.

A backup holds the project row (idea, preset, options with lyrics / bible /
music settings, status), every scene row as stored (prompts, versions, clip
status, corrections) and the result files (clips, keyframes, frames, normalised
clips, narration, final video + subtitles, the song). Restoring replaces the
current scenes and files with the snapshot. Files are copied, never linked:
the server's PRoot forbids hard links.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

RESULT_DIRS = ("clips", "frames", "keyframes", "narration", "norm")
RESULT_FILES = ("final.mp4", "final.srt", "final.ass", "preview.mp4", "preview.srt", "preview.ass")
WORK_DIRS = ("tmp", "tmp_preview")
_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class BackupError(Exception):
    pass


def _root(project_dir: Path) -> Path:
    return Path(project_dir) / "backups"


def _folder(project_dir: Path, backup_id: str) -> Path:
    if not _ID_RE.match(backup_id or ""):
        raise BackupError("backup tidak ditemukan")
    folder = _root(project_dir) / backup_id
    if not (folder / "manifest.json").is_file():
        raise BackupError("backup tidak ditemukan")
    return folder


def _music_file(options: dict) -> str | None:
    name = (options or {}).get("music_file") or ""
    # only a plain file name inside the project folder
    return name if name and "/" not in name and "\\" not in name and not name.startswith(".") else None


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def create(project_dir: Path, project_row: dict, scenes: list[dict], *, label: str = "") -> dict:
    """Copy the project's result into a new backup and return its summary."""
    project_dir = Path(project_dir)
    backup_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    folder = _root(project_dir) / backup_id
    folder.mkdir(parents=True)
    try:
        options = json.loads(project_row.get("options_json") or "{}")
        files = []
        for name in RESULT_DIRS:
            src = project_dir / name
            if src.is_dir() and any(src.iterdir()):
                shutil.copytree(src, folder / name)
                files.append(name)
        for name in (*RESULT_FILES, _music_file(options)):
            if name and (project_dir / name).is_file():
                shutil.copy2(project_dir / name, folder / name)
                files.append(name)
        manifest = {
            "id": backup_id,
            "label": label.strip()[:80],
            "created_at": round(time.time(), 3),
            "project": {k: project_row.get(k) for k in
                        ("title", "prompt", "preset", "target_seconds", "language", "options_json", "status")},
            "scenes": scenes,
            "files": files,
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return _summary(folder, manifest)


def _summary(folder: Path, manifest: dict) -> dict:
    scenes = manifest.get("scenes") or []
    return {
        "id": manifest["id"],
        "label": manifest.get("label") or "",
        "created_at": manifest.get("created_at"),
        "title": (manifest.get("project") or {}).get("title") or "",
        "scenes": len(scenes),
        "clips": sum(1 for s in scenes if s.get("clip_status") == "done" and s.get("clip_file")),
        "has_final": "final.mp4" in (manifest.get("files") or []),
        "bytes": _size(folder),
    }


def list_backups(project_dir: Path) -> list[dict]:
    """Newest first; unreadable folders are skipped."""
    root = _root(project_dir)
    if not root.is_dir():
        return []
    out = []
    for folder in root.iterdir():
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            out.append(_summary(folder, manifest))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda b: (b["created_at"] or 0, b["id"]), reverse=True)


def clear_results(project_dir: Path) -> None:
    """Delete the generated result (the song, lyrics and settings stay)."""
    project_dir = Path(project_dir)
    for name in (*RESULT_DIRS, *WORK_DIRS):
        shutil.rmtree(project_dir / name, ignore_errors=True)
    for name in RESULT_FILES:
        (project_dir / name).unlink(missing_ok=True)


def load(project_dir: Path, backup_id: str) -> dict:
    return json.loads((_folder(project_dir, backup_id) / "manifest.json").read_text(encoding="utf-8"))


def restore_files(project_dir: Path, backup_id: str) -> dict:
    """Replace the current result files with the backup's; returns its manifest."""
    project_dir = Path(project_dir)
    folder = _folder(project_dir, backup_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    clear_results(project_dir)
    for name in manifest.get("files") or []:
        src = folder / name
        if src.is_dir():
            shutil.copytree(src, project_dir / name)
        elif src.is_file():
            shutil.copy2(src, project_dir / name)
    return manifest


def delete(project_dir: Path, backup_id: str) -> None:
    shutil.rmtree(_folder(project_dir, backup_id))
