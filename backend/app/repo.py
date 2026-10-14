"""Data access helpers. Every read/write of user data takes ``user_id`` so one
user can never touch another user's rows."""

from __future__ import annotations

from app.db import Database, dumps, loads, now
from app.security import hash_password, hash_token, new_api_token

PROFILE_FIELDS = ("name", "base_url", "chat_model", "video_model", "tts_model", "tts_voice", "clip_seconds")
PROJECT_FIELDS = ("title", "prompt", "preset", "target_seconds", "language", "profile_id")
DEFAULT_OPTIONS = {
    "continuity": True,          # last frame of clip N seeds clip N+1
    "burn_subtitles": True,
    "keep_clip_audio": False,    # model-generated clip audio under the narration
    "music_volume": 0.25,
    "voice": "",                 # overrides the profile voice when set
    "music_mode": "external",    # none | external (made outside, uploaded) | generate (provider, later)
    "music_prompt": "",          # brief for an AI music generator (written by the planner)
    "music_file": "",
    "music_style": "instrumental",  # instrumental (backsound under narration) | song (lyrics replace narration)
    "lyrics": "",                # song mode: "[m:ss] line" per sung line (+ [Section] headers) → subtitles
    # Story bible, written by the planner and prepended to every clip prompt so
    # separately generated clips share one character, one world and one look.
    "bible_character": "",
    "bible_world": "",
    "bible_style": "",
    "transition": 0.5,           # crossfade seconds between scenes that change place (0 = hard cut)
}


class Repo:
    def __init__(self, db: Database):
        self.db = db

    # ── users ──────────────────────────────────────────────────────────
    def create_user(self, username: str, password: str, role: str = "user") -> int:
        return self.db.execute(
            "INSERT INTO users(username, password_hash, role, active, created_at) VALUES(?,?,?,1,?)",
            (username.strip(), hash_password(password), role, now()),
        )

    def user_by_name(self, username: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE username = ?", (username.strip(),))

    def user(self, user_id: int) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))

    def users(self) -> list[dict]:
        return self.db.all("SELECT id, username, role, active, created_at FROM users ORDER BY id")

    def update_user(self, user_id: int, *, role: str | None = None, active: bool | None = None,
                    password: str | None = None) -> None:
        if role is not None:
            self.db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        if active is not None:
            self.db.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
        if password:
            self.db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))

    def ensure_admin(self, username: str, password: str) -> None:
        """Create the bootstrap admin once (``.env``); never overwrites a password."""
        if not password or self.user_by_name(username):
            return
        self.create_user(username, password, role="admin")

    # ── API tokens ─────────────────────────────────────────────────────
    def create_token(self, user_id: int, name: str) -> tuple[str, dict]:
        token, token_hash, prefix = new_api_token()
        token_id = self.db.execute(
            "INSERT INTO api_tokens(user_id, name, token_hash, prefix, created_at) VALUES(?,?,?,?,?)",
            (user_id, name.strip() or "token", token_hash, prefix, now()),
        )
        return token, self.db.one("SELECT id, name, prefix, created_at, last_used_at FROM api_tokens WHERE id = ?",
                                  (token_id,))

    def tokens(self, user_id: int) -> list[dict]:
        return self.db.all("SELECT id, name, prefix, created_at, last_used_at FROM api_tokens "
                           "WHERE user_id = ? ORDER BY id DESC", (user_id,))

    def delete_token(self, user_id: int, token_id: int) -> bool:
        return self.db.execute("DELETE FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user_id)) > 0

    def user_by_token(self, token: str) -> dict | None:
        row = self.db.one("SELECT u.*, t.id AS token_id FROM api_tokens t JOIN users u ON u.id = t.user_id "
                          "WHERE t.token_hash = ?", (hash_token(token),))
        if row:
            self.db.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now(), row["token_id"]))
        return row

    # ── provider profiles ──────────────────────────────────────────────
    def create_profile(self, user_id: int, data: dict, api_key_enc: str) -> int:
        return self.db.execute(
            "INSERT INTO profiles(user_id, name, base_url, api_key_enc, chat_model, video_model, tts_model, "
            "tts_voice, clip_seconds, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id, data["name"], data["base_url"], api_key_enc, data.get("chat_model", ""),
             data.get("video_model", ""), data.get("tts_model", ""), data.get("tts_voice", ""),
             int(data.get("clip_seconds") or 5), now()),
        )

    def profiles(self, user_id: int) -> list[dict]:
        return self.db.all("SELECT * FROM profiles WHERE user_id = ? ORDER BY id", (user_id,))

    def profile(self, user_id: int, profile_id: int) -> dict | None:
        return self.db.one("SELECT * FROM profiles WHERE id = ? AND user_id = ?", (profile_id, user_id))

    def update_profile(self, user_id: int, profile_id: int, data: dict, api_key_enc: str | None = None) -> None:
        fields = {k: data[k] for k in PROFILE_FIELDS if k in data and data[k] is not None}
        if api_key_enc:
            fields["api_key_enc"] = api_key_enc
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE profiles SET {sets} WHERE id = ? AND user_id = ?",
                        (*fields.values(), profile_id, user_id))

    def delete_profile(self, user_id: int, profile_id: int) -> bool:
        return self.db.execute("DELETE FROM profiles WHERE id = ? AND user_id = ?", (profile_id, user_id)) > 0

    # ── projects ───────────────────────────────────────────────────────
    def create_project(self, user_id: int, data: dict) -> int:
        options = {**DEFAULT_OPTIONS, **(data.get("options") or {})}
        ts = now()
        return self.db.execute(
            "INSERT INTO projects(user_id, profile_id, title, prompt, preset, target_seconds, language, "
            "options_json, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?, 'draft', ?, ?)",
            (user_id, data.get("profile_id"), data.get("title", ""), data.get("prompt", ""),
             data.get("preset", "tiktok"), int(data.get("target_seconds") or 30), data.get("language", "id-ID"),
             dumps(options), ts, ts),
        )

    def projects(self, user_id: int) -> list[dict]:
        rows = self.db.all("SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
        return [self._project_out(r) for r in rows]

    def project(self, user_id: int, project_id: int) -> dict | None:
        row = self.db.one("SELECT * FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        return self._project_out(row) if row else None

    @staticmethod
    def _project_out(row: dict) -> dict:
        out = dict(row)
        out["options"] = {**DEFAULT_OPTIONS, **loads(out.pop("options_json"), {})}
        return out

    def update_project(self, user_id: int, project_id: int, data: dict) -> None:
        fields = {k: data[k] for k in PROJECT_FIELDS if k in data and data[k] is not None}
        if "options" in data and data["options"] is not None:
            current = self.project(user_id, project_id) or {}
            fields["options_json"] = dumps({**(current.get("options") or {}), **data["options"]})
        if "status" in data:
            fields["status"] = data["status"]
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE projects SET {sets} WHERE id = ? AND user_id = ?",
                        (*fields.values(), project_id, user_id))

    def delete_project(self, user_id: int, project_id: int) -> bool:
        return self.db.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)) > 0

    # ── scenes ─────────────────────────────────────────────────────────
    def scenes(self, project_id: int) -> list[dict]:
        rows = self.db.all("SELECT * FROM scenes WHERE project_id = ? ORDER BY idx", (project_id,))
        for row in rows:
            row["narration_info"] = loads(row.pop("narration_json"), None)
            row["continues"] = bool(row.get("continues"))
        return rows

    def replace_scenes(self, project_id: int, new_scenes: list[dict]) -> dict:
        """Store a new storyboard, keeping generated clips of unchanged scenes.

        A scene keeps its clip when its visual prompt, duration and
        ``continues`` flag match the old scene at the same index; otherwise its ``version`` is bumped and
        the clip is regenerated. Narration audio is kept only for identical
        narration text. Returns ``{"changed_visual": [...], "changed_narration": [...]}``.
        """
        old = {s["idx"]: s for s in self.scenes(project_id)}
        changed_visual, changed_narration = [], []
        with self.db.connect() as conn:
            conn.execute("DELETE FROM scenes WHERE project_id = ? AND idx >= ?", (project_id, len(new_scenes)))
            for idx, scene in enumerate(new_scenes):
                prev = old.get(idx)
                continues = bool(scene.get("continues")) and idx > 0
                same_visual = bool(prev) and prev["visual_prompt"] == scene["visual_prompt"] \
                    and abs(float(prev["duration"]) - float(scene["duration"])) < 0.01 \
                    and bool(prev.get("continues")) == continues
                same_narration = bool(prev) and prev["narration"] == scene["narration"]
                if not same_visual:
                    changed_visual.append(idx)
                if not same_narration:
                    changed_narration.append(idx)
                if prev is None:
                    conn.execute(
                        "INSERT INTO scenes(project_id, idx, visual_prompt, narration, duration, continues) "
                        "VALUES(?,?,?,?,?,?)",
                        (project_id, idx, scene["visual_prompt"], scene["narration"], scene["duration"], int(continues)),
                    )
                    continue
                conn.execute(
                    "UPDATE scenes SET visual_prompt = ?, narration = ?, duration = ?, continues = ?, "
                    "version = CASE WHEN ? THEN version ELSE version + 1 END, "
                    "clip_status = CASE WHEN ? THEN clip_status ELSE 'pending' END, "
                    "clip_error = CASE WHEN ? THEN clip_error ELSE NULL END, "
                    "narration_file = CASE WHEN ? THEN narration_file ELSE NULL END, "
                    "narration_json = CASE WHEN ? THEN narration_json ELSE NULL END "
                    "WHERE id = ?",
                    (scene["visual_prompt"], scene["narration"], scene["duration"], int(continues), same_visual, same_visual,
                     same_visual, same_narration, same_narration, prev["id"]),
                )
        return {"changed_visual": changed_visual, "changed_narration": changed_narration}

    def bump_scene(self, project_id: int, idx: int) -> bool:
        """Force regeneration of one scene's clip."""
        return self.db.execute(
            "UPDATE scenes SET version = version + 1, clip_status = 'pending', clip_error = NULL "
            "WHERE project_id = ? AND idx = ?", (project_id, idx)) > 0

    def update_scene(self, scene_id: int, **fields) -> None:
        if "narration_info" in fields:
            fields["narration_json"] = dumps(fields.pop("narration_info")) if fields["narration_info"] is not None else None
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE scenes SET {sets} WHERE id = ?", (*fields.values(), scene_id))

    # ── jobs ───────────────────────────────────────────────────────────
    def create_job(self, user_id: int, project_id: int | None, kind: str, payload: dict | None = None) -> int:
        ts = now()
        return self.db.execute(
            "INSERT INTO jobs(user_id, project_id, kind, status, payload_json, created_at, updated_at) "
            "VALUES(?,?,?, 'queued', ?, ?, ?)", (user_id, project_id, kind, dumps(payload or {}), ts, ts),
        )

    def job(self, job_id: int, user_id: int | None = None) -> dict | None:
        if user_id is None:
            row = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        else:
            row = self.db.one("SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
        return self._job_out(row) if row else None

    def jobs_for_project(self, user_id: int, project_id: int, limit: int = 20) -> list[dict]:
        rows = self.db.all("SELECT * FROM jobs WHERE user_id = ? AND project_id = ? ORDER BY id DESC LIMIT ?",
                           (user_id, project_id, limit))
        return [self._job_out(r) for r in rows]

    def jobs_ahead(self, job_id: int) -> int:
        """Queued/running jobs (any user) that will run before ``job_id``."""
        row = self.db.one("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running') AND id < ? "
                          "AND kind != 'preview'", (job_id,))
        return int(row["n"]) if row else 0

    def active_job(self, project_id: int) -> dict | None:
        """The project's main-lane job (plan/render/edit/compose…). Preview jobs
        run in their own lane and never block or hide it."""
        row = self.db.one("SELECT * FROM jobs WHERE project_id = ? AND status IN ('queued','running') "
                          "AND kind != 'preview' ORDER BY id LIMIT 1", (project_id,))
        return self._job_out(row) if row else None

    def latest_preview_job(self, project_id: int) -> dict | None:
        row = self.db.one("SELECT * FROM jobs WHERE project_id = ? AND kind = 'preview' ORDER BY id DESC LIMIT 1",
                          (project_id,))
        return self._job_out(row) if row else None

    @staticmethod
    def _job_out(row: dict) -> dict:
        out = dict(row)
        out["payload"] = loads(out.pop("payload_json"), {})
        out["result"] = loads(out.pop("result_json"), {})
        return out

    def update_job(self, job_id: int, **fields) -> None:
        if "result" in fields:
            fields["result_json"] = dumps(fields.pop("result"))
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))

    def next_queued_job(self, preview: bool = False) -> dict | None:
        """Oldest queued job of one lane: main (everything else) or preview."""
        lane = "kind = 'preview'" if preview else "kind != 'preview'"
        row = self.db.one(f"SELECT * FROM jobs WHERE status = 'queued' AND {lane} ORDER BY id LIMIT 1")
        return self._job_out(row) if row else None

    def requeue_interrupted(self) -> int:
        """Jobs left ``running`` by a crash/restart are queued again (resume)."""
        return self.db.execute("UPDATE jobs SET status = 'queued', message = 'dilanjutkan setelah restart' "
                               "WHERE status = 'running'")

    def job_status(self, job_id: int) -> str:
        row = self.db.one("SELECT status FROM jobs WHERE id = ?", (job_id,))
        return row["status"] if row else "missing"
