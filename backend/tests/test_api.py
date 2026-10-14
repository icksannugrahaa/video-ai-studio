"""HTTP API: auth, CSRF header, tokens, admin, isolation between users."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login


def _profile(client, **extra):
    body = {"name": "router", "base_url": "https://ai.example.com/v1/", "api_key": "sk-secret-key-123",
            "chat_model": "kimi", "video_model": "seedance-2.5", "tts_model": "edge-tts", "clip_seconds": 5, **extra}
    resp = client.post("/api/profiles", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_login_me_and_bad_password(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    user = login(client)
    assert user["role"] == "admin"
    assert client.get("/api/auth/me").json()["username"] == "admin"


def test_cookie_writes_require_csrf_header(client):
    login(client)
    del client.headers["X-Requested-With"]
    assert client.post("/api/projects", json={"prompt": "x"}).status_code == 403
    client.headers["X-Requested-With"] = "sav"
    assert client.post("/api/projects", json={"prompt": "x"}).status_code == 200


def test_api_token_auth_and_revoke(app, client):
    login(client)
    created = client.post("/api/auth/tokens", json={"name": "bot"}).json()
    token = created["token"]
    api = TestClient(app)
    api.headers["Authorization"] = f"Bearer {token}"
    assert api.post("/api/projects", json={"prompt": "via token"}).status_code == 200  # no CSRF header needed
    assert all("token" not in t for t in client.get("/api/auth/tokens").json())
    client.delete(f"/api/auth/tokens/{created['id']}")
    assert api.get("/api/projects").status_code == 401


def test_profile_key_encrypted_and_masked(app, client):
    login(client)
    profile = _profile(client)
    assert profile["base_url"] == "https://ai.example.com/v1"
    assert profile["api_key_masked"] == "sk-s…-123" and "api_key_enc" not in profile
    row = app.state.services.db.one("SELECT api_key_enc FROM profiles WHERE id = ?", (profile["id"],))
    assert "sk-secret" not in row["api_key_enc"]
    models = client.get(f"/api/profiles/{profile['id']}/models").json()
    assert models["by_kind"]["video"] == ["seedance-2.5"]
    assert client.post("/api/profiles", json={"name": "x", "base_url": "ftp://x.example", "api_key": "k"}).status_code == 422


def test_registration_admin_users_and_isolation(app, client):
    login(client)
    assert client.post("/api/auth/register", json={"username": "budi", "password": "password-1"}).status_code == 403
    assert client.put("/api/settings", json={"registration_open": True}).json()["registration_open"] is True
    other = TestClient(app)
    assert other.post("/api/auth/register", json={"username": "budi", "password": "password-1"}).status_code == 200
    other.headers["X-Requested-With"] = "sav"
    assert other.get("/api/users").status_code == 403

    project = client.post("/api/projects", json={"prompt": "milik admin"}).json()
    profile = _profile(client)
    assert other.get(f"/api/projects/{project['id']}").status_code == 404
    assert other.patch(f"/api/projects/{project['id']}", json={"title": "x"}).status_code == 404
    assert other.post("/api/projects", json={"prompt": "x", "profile_id": profile["id"]}).status_code == 400
    assert other.get("/api/projects").json() == []

    budi = next(u for u in client.get("/api/users").json() if u["username"] == "budi")
    client.patch(f"/api/users/{budi['id']}", json={"active": False})
    assert other.get("/api/projects").status_code == 401
    me = client.get("/api/auth/me").json()
    assert client.patch(f"/api/users/{me['id']}", json={"active": False}).status_code == 400


def test_project_flow_validation(client):
    login(client)
    assert client.post("/api/projects", json={"preset": "myspace"}).status_code == 400
    project = client.post("/api/projects", json={"prompt": ""}).json()
    assert client.post(f"/api/projects/{project['id']}/plan").status_code == 400  # empty prompt
    client.patch(f"/api/projects/{project['id']}", json={"prompt": "Kucing astronot"})
    assert client.post(f"/api/projects/{project['id']}/plan").status_code == 400  # no profile
    profile = _profile(client)
    client.patch(f"/api/projects/{project['id']}", json={"profile_id": profile["id"]})
    job = client.post(f"/api/projects/{project['id']}/plan").json()
    assert job["kind"] == "plan" and job["status"] == "queued"
    assert client.post(f"/api/projects/{project['id']}/plan").status_code == 409  # one job at a time
    assert client.get("/api/projects/9999/files/final.mp4").status_code == 404
    assert client.get(f"/api/projects/{project['id']}/files/../app.db").status_code == 404


def test_presets_and_music_upload(client):
    login(client)
    assert {p["id"] for p in client.get("/api/presets").json()} >= {"tiktok", "youtube"}
    project = client.post("/api/projects", json={"prompt": "x"}).json()
    bad = client.post(f"/api/projects/{project['id']}/music", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
    ok = client.post(f"/api/projects/{project['id']}/music", files={"file": ("song.mp3", b"ID3data", "audio/mpeg")})
    assert ok.json()["options"]["music_file"] == "music.mp3"


def test_models_grouped_by_field_and_draft_probe(client, fake_client):
    login(client)
    profile = _profile(client)
    by_field = client.get(f"/api/profiles/{profile['id']}/models").json()["by_field"]
    assert by_field == {"chat": ["kimi"], "video": ["seedance-2.5"], "tts": ["edge-tts"]}
    draft = client.post("/api/profiles/models", json={"base_url": "https://ai.example.com", "api_key": "sk-new"})
    assert draft.status_code == 200 and draft.json()["by_field"]["video"] == ["seedance-2.5"]
    reuse = client.post("/api/profiles/models", json={"base_url": "https://ai.example.com", "profile_id": profile["id"]})
    assert reuse.status_code == 200
    assert client.post("/api/profiles/models", json={"base_url": "https://ai.example.com"}).status_code == 400


def test_project_list_summary_and_music_file(client):
    login(client)
    project = client.post("/api/projects", json={"prompt": "x"}).json()
    listed = client.get("/api/projects").json()[0]
    assert listed["scene_count"] == 0 and listed["clips_ready"] == 0 and listed["files"] == []
    assert listed["thumb_clip"] is None and listed["active_job"] is None
    client.post(f"/api/projects/{project['id']}/music", files={"file": ("song.mp3", b"ID3data", "audio/mpeg")})
    music = client.get(f"/api/projects/{project['id']}/files/music.mp3")
    assert music.status_code == 200 and music.headers["content-type"] == "audio/mpeg"
    assert client.get(f"/api/projects/{project['id']}/files/music.exe").status_code == 404
