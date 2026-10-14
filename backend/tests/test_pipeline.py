"""End-to-end pipeline with real ffmpeg and a fake provider (tiny media)."""

from __future__ import annotations

import dataclasses

from app.pipeline import media
from tests.conftest import login, needs_ffmpeg


def _setup(client, **options):
    login(client)
    profile = client.post("/api/profiles", json={
        "name": "router", "base_url": "https://ai.example.com", "api_key": "sk-test",
        "chat_model": "kimi", "video_model": "seedance-2.5", "tts_model": "edge-tts", "tts_voice": "id-ID-ArdiNeural",
        "clip_seconds": 5}).json()
    project = client.post("/api/projects", json={"prompt": "Kucing astronot ke bulan", "preset": "tiktok",
                                                 "target_seconds": 10, "profile_id": profile["id"],
                                                 "options": options}).json()
    return project


def _run_jobs(app):
    svc = app.state.services
    while True:
        job = svc.repo.next_queued_job()
        if job is None:
            return
        svc.worker.run_one(job)


@needs_ffmpeg
def test_plan_render_edit_regenerate(app, client, fake_client, settings):
    project = _setup(client, continuity=True)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["title"] == "Kucing Astronot" and len(detail["scenes"]) == 2
    assert detail["jobs"][0]["status"] == "succeeded"

    estimate = client.post(f"/api/projects/{pid}/render", json={}).json()["estimate"]
    assert estimate["clips_to_generate"] == 2
    fake_client.fail_video_times = 1  # first attempt fails, retry succeeds
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    job = detail["jobs"][0]
    assert job["status"] == "succeeded", job["message"]
    assert detail["status"] == "done" and detail["files"] == ["final.mp4", "final.srt"]

    root = settings.projects_dir / str(pid)
    final = root / "final.mp4"
    assert media.has_audio(final)
    narration_total = sum((s["narration_info"] or {}).get("duration", 0) for s in detail["scenes"])
    assert media.duration(final) >= max(5.0, narration_total)
    srt = (root / "final.srt").read_text()
    assert "Halo semua." in srt and "Dia mendarat di bulan!" in srt
    video_calls = [c for c in fake_client.calls if c[0] == "video"]
    assert video_calls[0][3] == "9:16" and video_calls[-1][4] is True  # continuity frame for scene 2
    assert client.get(f"/api/projects/{pid}/files/final.mp4").status_code == 200
    stats = detail["stats"]
    assert stats["jobs"]["plan"]["count"] == 1 and stats["jobs"]["render"]["count"] == 1
    assert stats["clips"]["count"] == 2 and stats["clips"]["retried"] == 1  # first video call failed once
    assert stats["final"]["files"][0] == "final.mp4" and stats["final_at"] >= stats["first_at"]

    # Edit by prompt: only scene 2 changes visually → one new clip, narration of scene 1 reused.
    fake_client.edited = {"title": "x", "scenes": [
        dict(fake_client.storyboard["scenes"][0]),
        {"visual_prompt": "The cat astronaut plants a flag on the moon", "narration": "Dia mendarat di bulan!",
         "duration": 2},
    ]}
    fake_client.calls.clear()
    client.post(f"/api/projects/{pid}/edit", json={"instruction": "ganti adegan kedua jadi tancap bendera"})
    _run_jobs(app)
    job = client.get(f"/api/projects/{pid}").json()["jobs"][0]
    assert job["status"] == "succeeded", job["message"]
    assert job["result"]["changed_visual"] == [1]
    assert [c[0] for c in fake_client.calls].count("video") == 1
    assert [c[0] for c in fake_client.calls].count("tts") == 0

    # Regenerate one scene → exactly one video call.
    fake_client.calls.clear()
    client.post(f"/api/projects/{pid}/scenes/0/regenerate")
    _run_jobs(app)
    assert [c[0] for c in fake_client.calls] == ["video"]


@needs_ffmpeg
def test_resume_skips_finished_scenes_and_cancel(app, client, fake_client):
    project = _setup(client, continuity=False)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    svc = app.state.services
    job = client.post(f"/api/projects/{pid}/render", json={"confirm": True}).json()["job"]
    # Simulate a crash after scene 0 finished: mark it done, job left running.
    scenes = svc.repo.scenes(pid)
    fake_client.calls.clear()
    from app.engine import Workspace
    ws = Workspace(svc.settings.projects_dir, pid)
    clip = fake_client("", "").generate_video("m", "p", seconds=3)
    (ws.path("clips", "scene_0_v1.mp4")).write_bytes(clip.data)
    svc.repo.update_scene(scenes[0]["id"], clip_status="done", clip_file="clips/scene_0_v1.mp4", clip_version=1)
    svc.repo.update_job(job["id"], status="running")
    assert svc.repo.requeue_interrupted() == 1
    fake_client.calls.clear()
    _run_jobs(app)
    assert [c[0] for c in fake_client.calls if c[0] == "video"] == ["video"]  # only scene 1
    assert svc.repo.job(job["id"])["status"] == "succeeded"

    job2 = client.post(f"/api/projects/{pid}/scenes/1/regenerate").json()
    canceled = client.post(f"/api/jobs/{job2['id']}/cancel").json()
    assert canceled["status"] == "canceled"
    assert svc.repo.next_queued_job() is None


@needs_ffmpeg
def test_music_is_mixed(app, client, settings):
    import subprocess
    project = _setup(client)
    pid = project["id"]
    music = settings.data_dir / "m.mp3"
    music.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
                    str(music)], check=True)
    client.post(f"/api/projects/{pid}/music", files={"file": ("bg.mp3", music.read_bytes(), "audio/mpeg")})
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]


@needs_ffmpeg
def test_music_brief_prompt_job_and_compose_only(app, client, fake_client, settings):
    import subprocess
    project = _setup(client)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["options"]["music_prompt"] == "Playful orchestral, 110 BPM"   # written with the storyboard
    assert detail["options"]["music_mode"] == "external"

    client.post(f"/api/projects/{pid}/render", json={"confirm": True})   # a long job is queued…
    resp = client.post(f"/api/projects/{pid}/music-prompt", json={"hint": "lebih santai"})
    assert resp.status_code == 200                                          # …music brief still works
    assert resp.json()["options"]["music_prompt"].startswith("Dreamy lo-fi")
    _run_jobs(app)


    music = settings.data_dir / "m.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=20",
                    str(music)], check=True)
    client.post(f"/api/projects/{pid}/music", files={"file": ("song.mp3", music.read_bytes(), "audio/mpeg")})
    fake_client.calls.clear()
    job = client.post(f"/api/projects/{pid}/compose").json()
    _run_jobs(app)
    assert app.state.services.repo.job(job["id"])["status"] == "succeeded"
    assert [c for c in fake_client.calls if c[0] in ("video", "tts")] == []      # remix only
    assert (settings.projects_dir / str(pid) / "final.mp4").exists()

    client.patch(f"/api/projects/{pid}", json={"options": {"music_mode": "none"}})
    assert client.get(f"/api/projects/{pid}").json()["options"]["music_file"] == "music.mp3"   # kept, just unused


@needs_ffmpeg
def test_music_uploaded_during_render_is_used(app, client, fake_client, settings, monkeypatch):
    import subprocess
    from app.pipeline import media
    project = _setup(client)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})

    music = settings.data_dir / "late.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
                    str(music)], check=True)
    real_generate = fake_client.generate_video
    uploaded = {"done": False}

    def generate_and_upload(self, *args, **kwargs):  # user uploads music while clips render
        if not uploaded["done"]:
            uploaded["done"] = True
            client.post(f"/api/projects/{pid}/music", files={"file": ("late.mp3", music.read_bytes(), "audio/mpeg")})
        return real_generate(self, *args, **kwargs)

    monkeypatch.setattr(fake_client, "generate_video", generate_and_upload)
    seen = {}
    real_compose = media.compose_final

    def spy(*args, **kwargs):
        seen["music"] = kwargs.get("music")
        return real_compose(*args, **kwargs)

    monkeypatch.setattr(media, "compose_final", spy)
    _run_jobs(app)
    assert seen["music"] is not None and seen["music"].name == "music.mp3"


@needs_ffmpeg
def test_song_mode_lyrics_drive_subtitles_without_tts(app, client, fake_client, settings, monkeypatch):
    import subprocess
    from app.pipeline import media
    project = _setup(client)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    detail = client.post(f"/api/projects/{pid}/song", json={"hint": "lagu anak"}).json()
    opts = detail["options"]
    assert opts["music_style"] == "song"
    assert opts["lyrics"] == ("[Intro]\n\n[Verse 1]\n[0:00] Kucing kecil terbang tinggi\n[0:03] Menuju bulan yang sepi"
                              "\n\n[Chorus]\n[0:04] Halo bulan!")  # out-of-order line dropped
    assert "bright female vocal" in opts["music_prompt"] and "Lyrics:" in opts["music_prompt"]

    song = settings.data_dir / "song.mp3"
    song.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    str(song)], check=True)
    client.post(f"/api/projects/{pid}/music", files={"file": ("song.mp3", song.read_bytes(), "audio/mpeg")})
    seen = {}
    real = media.compose_final
    monkeypatch.setattr(media, "compose_final", lambda *a, **k: seen.update(k) or real(*a, **k))
    fake_client.calls.clear()
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    job = client.get(f"/api/projects/{pid}").json()["jobs"][0]
    assert job["status"] == "succeeded", job["message"]
    assert [c for c in fake_client.calls if c[0] == "tts"] == []          # lyrics replace narration
    assert seen["music_volume"] == 1.0
    srt = (settings.projects_dir / str(pid) / "final.srt").read_text()
    assert "Kucing kecil terbang tinggi" in srt and "Halo bulan!" in srt and "Halo semua" not in srt
    assert media.duration(settings.projects_dir / str(pid) / "final.mp4") >= 4.9


@needs_ffmpeg
def test_partial_preview_from_ready_clips(app, client, fake_client, settings):
    project = _setup(client, continuity=False)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    assert client.post(f"/api/projects/{pid}/compose", json={"partial": True}).status_code == 400  # no clip yet
    svc = app.state.services
    scenes = svc.repo.scenes(pid)
    from app.engine import Workspace
    ws = Workspace(svc.settings.projects_dir, pid)
    clip = fake_client("", "")
    ws.path("clips", "scene_0_v1.mp4").write_bytes(clip.generate_video("m", "p", seconds=3).data)
    svc.repo.update_scene(scenes[0]["id"], clip_status="done", clip_file="clips/scene_0_v1.mp4", clip_version=1)
    assert client.post(f"/api/projects/{pid}/compose", json={}).status_code == 400   # full needs all clips
    job = client.post(f"/api/projects/{pid}/compose", json={"partial": True}).json()
    _run_jobs(app)
    done = svc.repo.job(job["id"])
    assert done["status"] == "succeeded", done["message"]
    assert done["result"]["scenes_used"] == [1]
    detail = client.get(f"/api/projects/{pid}").json()
    assert "preview.mp4" in detail["files"] and "final.mp4" not in detail["files"]
    srt = (settings.projects_dir / str(pid) / "preview.srt").read_text()
    assert "Halo semua." in srt and "mendarat" not in srt
    assert client.get(f"/api/projects/{pid}/files/preview.mp4").status_code == 200


@needs_ffmpeg
def test_crossfade_keeps_scene_timeline(tmp_path):
    import subprocess
    clips, lengths, fades = [], [2.0, 1.5, 2.0], [0.4, 0.0, 0.0]
    assert [media.crossfade_clip_seconds(lengths, fades, i) for i in range(3)] == [2.2, 1.7, 2.0]
    for i in range(3):
        length = media.crossfade_clip_seconds(lengths, fades, i)
        src = tmp_path / f"src{i}.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc=size=160x284:rate=12:duration={length}", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)], check=True)
        norm = tmp_path / f"norm{i}.mp4"
        media.normalize_clip(src, norm, width=160, height=284, fps=12, seconds=length,
                             keep_audio=False, preset="ultrafast")
        clips.append(norm)
    if not media.has_filter("xfade"):
        return  # old ffmpeg: the engine falls back to plain concat
    out = media.crossfade_videos(clips, lengths, fades, tmp_path / "out.mp4", preset="ultrafast")
    assert abs(media.duration(out) - sum(lengths)) < 0.15
    assert media.has_audio(out)


@needs_ffmpeg
def test_bible_prompts_and_smart_continuity(app, client, fake_client, settings, monkeypatch):
    monkeypatch.setattr(fake_client, "storyboard", {
        "title": "Oren", "music_prompt": "",
        "bible": {"character": "A slim orange tabby cat with a navy scarf", "world": "Jakarta, Indonesia",
                  "style": "Stylized 3D film look"},
        "scenes": [
            {"visual_prompt": "the character wakes up on a roof", "narration": "", "duration": 2},
            {"visual_prompt": "the character walks in a market", "narration": "", "duration": 2, "continues": False},
            {"visual_prompt": "the character sniffs a fish stall", "narration": "", "duration": 2, "continues": True},
        ]})
    project = _setup(client, continuity=True)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["options"]["bible_character"] == "A slim orange tabby cat with a navy scarf"
    assert [s["continues"] for s in detail["scenes"]] == [False, False, True]
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    video_calls = [c for c in fake_client.calls if c[0] == "video"]
    assert all("A slim orange tabby cat with a navy scarf" in c[1] for c in video_calls)
    assert all("Jakarta, Indonesia" in c[1] for c in video_calls)
    # only the continuous shot starts from the previous clip's last frame
    assert [c[4] for c in video_calls] == [False, False, True]
    assert all(s["clip_gen_seconds"] is not None and s["clip_gen_seconds"] >= 0 and s["clip_attempts"] == 1
               for s in detail["scenes"])
    assert abs(media.duration(settings.projects_dir / str(pid) / "final.mp4") - 9.0) < 0.3  # 3 scenes, min 3 s each


@needs_ffmpeg
def test_preview_lane_runs_beside_main_job(app, client, fake_client, settings):
    project = _setup(client)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    assert client.post(f"/api/projects/{pid}/preview").status_code == 400  # no clip yet
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    # Queue a main-lane job first: a preview must still be accepted and must not hide it.
    client.post(f"/api/projects/{pid}/plan")
    resp = client.post(f"/api/projects/{pid}/preview")
    assert resp.status_code == 200 and resp.json()["kind"] == "preview"
    assert client.post(f"/api/projects/{pid}/preview").status_code == 409  # one preview at a time
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["active_job"]["kind"] == "plan" and detail["preview_job"]["status"] == "queued"
    svc = app.state.services
    job = svc.repo.next_queued_job(preview=True)
    assert job["kind"] == "preview" and svc.repo.next_queued_job()["kind"] == "plan"
    svc.worker.run_one(job)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["preview_job"]["status"] == "succeeded", detail["preview_job"]["message"]
    assert "preview.mp4" in detail["files"] and all(j["kind"] != "preview" for j in detail["jobs"])
    assert not list((settings.projects_dir / str(pid) / "tmp_preview").glob("*"))


def _bible_board(*flags):
    return {"title": "Paralel", "music_prompt": "",
            "bible": {"character": "A small orange cat", "world": "Jakarta", "style": "3D"},
            "scenes": [{"visual_prompt": f"shot {i}", "narration": "", "duration": 2, "continues": c}
                       for i, c in enumerate(flags)]}


@needs_ffmpeg
def test_parallel_chains_seed_only_continuous_shots(settings, fake_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = dataclasses.replace(settings, clip_concurrency=2)
    app = create_app(settings, client_factory=fake_client, start_worker=False)
    client = TestClient(app)
    monkeypatch.setattr(fake_client, "storyboard", _bible_board(False, True, False, False))
    project = _setup(client, continuity=True)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    seeded = {c[1].split("Shot: ")[1].split(" No on-screen")[0]: c[4] for c in fake_client.calls if c[0] == "video"}
    assert seeded == {"shot 0": False, "shot 1": True, "shot 2": False, "shot 3": False}
    assert all(s["clip_status"] == "done" for s in detail["scenes"])


@needs_ffmpeg
def test_parallel_failure_stops_new_clips_and_keeps_finished_ones(settings, fake_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = dataclasses.replace(settings, clip_concurrency=2)
    app = create_app(settings, client_factory=fake_client, start_worker=False)
    client = TestClient(app)
    monkeypatch.setattr(fake_client, "storyboard", _bible_board(False, False, False, False))
    monkeypatch.setattr(fake_client, "fail_prompts", ("shot 0",))
    project = _setup(client, continuity=True)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    job = detail["jobs"][0]
    assert job["status"] == "failed" and "Scene 1" in job["message"]
    states = [s["clip_status"] for s in detail["scenes"]]
    assert states[0] == "failed" and "running" not in states
    # the failure stops the queue: at most the clip already in flight on the other lane finishes
    assert states.count("done") <= 1 and states.count("pending") >= 2
