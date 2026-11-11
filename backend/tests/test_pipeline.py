"""End-to-end pipeline with real ffmpeg and a fake provider (tiny media)."""

from __future__ import annotations

import dataclasses

import pytest

from app import engine as app_engine
from app.pipeline import media
from app.providers import ProviderError
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
def test_plan_render_edit_regenerate(app, client, fake_client, settings, monkeypatch):
    monkeypatch.setattr(media, "seam_gap", lambda prev, nxt: 0.0)  # fake clips never connect
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
    monkeypatch.setattr(media, "seam_gap", lambda prev, nxt: 0.0)  # fake clips never connect
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
    assert abs(media.duration(settings.projects_dir / str(pid) / "final.mp4") - 12.0) < 0.3  # 3 scenes, min 4 s each


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
    project = _setup(client, continuity=True, parallel_clips=True)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    seeded = {c[1].split("Shot: ")[1][:6]: c[4] for c in fake_client.calls if c[0] == "video"}
    assert seeded == {"shot 0": False, "shot 1": True, "shot 2": False, "shot 3": False}
    assert all(s["clip_status"] == "done" for s in detail["scenes"])


def _rendered(client, app, pid):
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    return detail


def _planned_chain(app, client, fake_client, monkeypatch, *flags):
    monkeypatch.setattr(fake_client, "storyboard", _bible_board(*flags))
    pid = _setup(client, continuity=True)["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    return pid


def _videos(fake_client):
    return [c for c in fake_client.calls if c[0] == "video"]


@needs_ffmpeg
def test_clip_that_left_its_seed_is_retaken_once_and_the_closer_one_stays(app, client, fake_client, monkeypatch, settings):
    pid = _planned_chain(app, client, fake_client, monkeypatch, False, True)
    states = []

    def gap(prev, nxt):
        states.append(app.state.services.repo.scenes(pid)[1]["clip_status"])
        return 5.0 if "_retake" in str(nxt) else 30.0

    monkeypatch.setattr(media, "seam_gap", gap)
    fake_client.calls = []
    scenes = _rendered(client, app, pid)["scenes"]
    assert len(_videos(fake_client)) == 3
    assert states[:2] == ["done", "running"] and scenes[1]["clip_status"] == "done"
    assert client.get(f"/api/projects/{pid}/files/{scenes[1]['clip_file']}").status_code == 200  # the player can load it
    assert scenes[1]["clip_file"].endswith("_retake.mp4")
    clips = settings.projects_dir / str(pid) / "clips"
    assert not (clips / "scene_1_v1.mp4").exists()


@needs_ffmpeg
def test_worse_retake_is_dropped_and_clip_is_not_retried_again(app, client, fake_client, monkeypatch, settings):
    pid = _planned_chain(app, client, fake_client, monkeypatch, False, True)
    monkeypatch.setattr(media, "seam_gap", lambda prev, nxt: 40.0 if "_retake" in str(nxt) else 30.0)
    fake_client.calls = []
    scenes = _rendered(client, app, pid)["scenes"]
    assert len(_videos(fake_client)) == 3
    assert scenes[1]["clip_file"] == "clips/scene_1_v1.mp4"
    assert not (settings.projects_dir / str(pid) / "clips" / "scene_1_v1_retake.mp4").exists()


def _basket_board(fake_client, monkeypatch):
    shot = ("Table. START: one apple. ACTION: lifts an apple from a basket on the table, sets it down. "
            "END: exactly two large red apples in a row and a basket on the table.")
    board = _bible_board(False)
    board["scenes"][0]["visual_prompt"] = shot
    monkeypatch.setattr(fake_client, "storyboard", board)


def _answers(fake_client, monkeypatch, *replies):
    """The chat model's reading of each last frame, in order."""
    plain, queue = fake_client.chat, list(replies)

    def chat(self, model, messages, temperature=0.7, max_tokens=4096):
        if isinstance(messages[-1]["content"], list):
            fake_client.calls.append(("look", messages[-1]["content"][1]["image_url"]["url"][:22]))
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return plain(self, model, messages, temperature, max_tokens)

    monkeypatch.setattr(fake_client, "chat", chat)


@needs_ffmpeg
def test_clip_ending_without_what_its_shot_promises_is_retaken_even_unseeded(app, client, fake_client, monkeypatch):
    _basket_board(fake_client, monkeypatch)
    _answers(fake_client, monkeypatch, '{"count":2,"visible":{"basket":false}}', '{"count":2,"visible":{"basket":true}}')
    pid = _setup(client, continuity=True)["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    fake_client.calls = []
    scene = _rendered(client, app, pid)["scenes"][0]
    assert len(_videos(fake_client)) == 2
    assert [c for c in fake_client.calls if c[0] == "look"][0][1] == "data:image/jpeg;base64,"[:22]
    assert scene["clip_file"].endswith("_retake.mp4") and not scene["clip_error"]


@needs_ffmpeg
def test_end_state_still_wrong_after_the_retake_is_shown_on_the_scene(app, client, fake_client, monkeypatch):
    _basket_board(fake_client, monkeypatch)
    wrong = '{"count":2,"visible":{"basket":false}}'
    _answers(fake_client, monkeypatch, wrong, wrong)
    pid = _setup(client, continuity=True)["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    fake_client.calls = []
    scene = _rendered(client, app, pid)["scenes"][0]
    assert len(_videos(fake_client)) == 2  # never a third bill
    assert scene["clip_status"] == "done" and scene["clip_file"] == "clips/scene_0_v1.mp4"
    assert "basket tidak terlihat" in scene["clip_error"]


@needs_ffmpeg
def test_unreadable_answer_bills_no_retake_but_flags_the_scene(app, client, fake_client, monkeypatch):
    _basket_board(fake_client, monkeypatch)
    _answers(fake_client, monkeypatch, *["maaf, saya tidak bisa melihat gambar"] * 3)
    pid = _setup(client, continuity=True)["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    fake_client.calls = []
    scene = _rendered(client, app, pid)["scenes"][0]
    assert len(_videos(fake_client)) == 1
    assert len([c for c in fake_client.calls if c[0] == "look"]) == 3  # asked again before giving up
    assert scene["clip_status"] == "done" and scene["clip_error"] == app_engine.UNCHECKED_NOTE


@needs_ffmpeg
def test_end_check_asks_again_after_a_provider_error(app, client, fake_client, monkeypatch):
    # Seen live: the chat model's accounts were all cooling down, the check was
    # skipped and a first clip with three extra apples seeded the whole chain.
    _basket_board(fake_client, monkeypatch)
    _answers(fake_client, monkeypatch, ProviderError("busy", status=404),
             '{"count":2,"visible":{"basket":false}}', '{"count":2,"visible":{"basket":true}}')
    pid = _setup(client, continuity=True)["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    fake_client.calls = []
    scene = _rendered(client, app, pid)["scenes"][0]
    assert len(_videos(fake_client)) == 2
    assert scene["clip_file"].endswith("_retake.mp4") and not scene["clip_error"]


@needs_ffmpeg
def test_failed_retake_keeps_the_first_clip(app, client, fake_client, monkeypatch):
    pid = _planned_chain(app, client, fake_client, monkeypatch, False, True)

    def gap(prev, nxt):
        fake_client.fail_prompts = ("shot 1",)
        return 30.0

    monkeypatch.setattr(media, "seam_gap", gap)
    scenes = _rendered(client, app, pid)["scenes"]
    assert scenes[1]["clip_status"] == "done" and scenes[1]["clip_file"] == "clips/scene_1_v1.mp4"


@needs_ffmpeg
def test_remaking_a_clip_also_remakes_the_next_one_only_if_it_no_longer_connects(app, client, fake_client, monkeypatch):
    pid = _planned_chain(app, client, fake_client, monkeypatch, False, True, True, True, False)
    monkeypatch.setattr(media, "seam_gap", lambda prev, nxt: 1.0)
    scenes = _rendered(client, app, pid)["scenes"]
    # the user regenerates clip idx 1: idx 2 was seeded by the old one and breaks, idx 3 still connects
    app.state.services.repo.update_scene(scenes[1]["id"], version=2)
    monkeypatch.setattr(media, "seam_gap", lambda prev, nxt: 30.0 if "scene_2_v1" in str(nxt) else 1.0)
    fake_client.calls = []
    scenes = _rendered(client, app, pid)["scenes"]
    assert [c[1].split("Shot: ")[1][:6] for c in _videos(fake_client)] == ["shot 1", "shot 2"]
    assert [s["version"] for s in scenes] == [1, 2, 2, 1, 1]
    assert scenes[2]["clip_file"] == "clips/scene_2_v2.mp4"


@needs_ffmpeg
def test_parallel_failure_stops_new_clips_and_keeps_finished_ones(settings, fake_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = dataclasses.replace(settings, clip_concurrency=2)
    app = create_app(settings, client_factory=fake_client, start_worker=False)
    client = TestClient(app)
    monkeypatch.setattr(fake_client, "storyboard", _bible_board(False, False, False, False))
    monkeypatch.setattr(fake_client, "fail_prompts", ("shot 0",))
    project = _setup(client, continuity=True, parallel_clips=True)
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


@needs_ffmpeg
def test_clips_run_one_at_a_time_unless_parallel_is_enabled(settings, fake_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = dataclasses.replace(settings, clip_concurrency=2)
    app = create_app(settings, client_factory=fake_client, start_worker=False)
    client = TestClient(app)
    monkeypatch.setattr(fake_client, "storyboard", _bible_board(False, False, False))
    active, peak = [0], [0]
    real = fake_client.generate_video

    def tracking(self, *args, **kwargs):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        try:
            return real(self, *args, **kwargs)
        finally:
            active[0] -= 1

    monkeypatch.setattr(fake_client, "generate_video", tracking)
    project = _setup(client, continuity=True)
    assert project["options"]["parallel_clips"] is False
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    assert peak[0] == 1


@needs_ffmpeg
def test_short_scene_requests_the_minimum_clip_length(settings, fake_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app(settings, client_factory=fake_client, start_worker=False)
    client = TestClient(app)
    monkeypatch.setattr(fake_client, "storyboard", _bible_board(False))
    project = _setup(client, continuity=True)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    # an older plan (or a manual edit) may still hold a 3 s scene
    svc = app.state.services
    scene = svc.repo.scenes(pid)[0]
    svc.db.execute("UPDATE scenes SET duration = 3 WHERE id = ?", (scene["id"],))
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    assert [c[2] for c in fake_client.calls if c[0] == "video"] == [4]


def _colour_clip(path, colours, rate=24):
    """Clip made of solid-colour segments ``[(colour, seconds), ...]``."""
    import subprocess
    inputs = "".join(f"color=c={c}:s=64x64:r={rate}:d={d}[s{i}];" for i, (c, d) in enumerate(colours))
    joins = "".join(f"[s{i}]" for i in range(len(colours)))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-filter_complex",
                    f"{inputs}{joins}concat=n={len(colours)}:v=1:a=0,format=yuv420p", "-c:v", "libx264",
                    "-preset", "ultrafast", str(path)], check=True)
    return path


def _pixel(path, at=None):
    import subprocess
    seek = ["-ss", f"{at}"] if at is not None else []
    out = subprocess.run(["ffmpeg", "-loglevel", "error", *seek, "-i", str(path), "-frames:v", "1", "-vf", "scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(out[:3])


@needs_ffmpeg
def test_last_frame_is_the_real_last_frame(tmp_path):
    clip = _colour_clip(tmp_path / "c.mp4", [("red", 1.0), ("blue", 0.084)])
    r, g, b = _pixel(media.last_frame_png(clip, tmp_path / "last.png"))
    assert b > 200 and r < 60


@needs_ffmpeg
def test_short_clip_is_padded_under_the_fade_not_at_the_cut(tmp_path):
    clip = _colour_clip(tmp_path / "c.mp4", [("blue", 0.125), ("red", 0.75), ("green", 0.125)])
    norm = media.normalize_clip(clip, tmp_path / "n.mp4", width=64, height=64, fps=24, seconds=1.25,
                                keep_audio=False, preset="ultrafast", lead=0.25)
    assert abs(media.duration(norm) - 1.25) < 0.1
    assert _pixel(norm, 0.2)[2] > 200          # first frame held while the crossfade covers it
    assert _pixel(norm, 0.95)[0] > 200         # still mid-clip (a tail freeze would show green here)
    r, g, b = _pixel(norm, 1.2)                 # the clip's own ending plays up to the cut
    assert g > 100 and r < 60


@needs_ffmpeg
def test_render_keeps_shared_clip_frame_rate(tmp_path):
    from app.engine import render_fps
    a = _colour_clip(tmp_path / "a.mp4", [("red", 0.5)], rate=24)
    b = _colour_clip(tmp_path / "b.mp4", [("red", 0.5)], rate=24)
    c = _colour_clip(tmp_path / "c.mp4", [("red", 0.5)], rate=25)
    assert render_fps([a, b], 30) == 24
    assert render_fps([a, c], 30) == 30        # mixed rates: one common output rate
    assert render_fps([_colour_clip(tmp_path / "d.mp4", [("red", 0.5)], rate=60)], 30) == 30


@needs_ffmpeg
def test_continues_cut_lands_on_the_pose_the_next_clip_starts_from(tmp_path):
    # the next clip was seeded 3 frames before the previous clip's end (blue, not the green tail)
    prev = _colour_clip(tmp_path / "prev.mp4", [("red", 2.0), ("blue", 0.25), ("green", 0.125)])
    nxt = _colour_clip(tmp_path / "next.mp4", [("blue", 0.5)])
    keep = media.seam_frames(prev, nxt, fps=24)
    assert keep == 54
    norm = media.normalize_clip(prev, tmp_path / "n.mp4", width=64, height=64, fps=24, seconds=2.375,
                                keep_audio=False, preset="ultrafast", keep_frames=keep)
    assert abs(media.duration(norm) - 2.375) < 0.1      # slowed down a little, not shortened
    r, g, b = _pixel(media.last_frame_png(norm, tmp_path / "last.png"))
    assert b > 200 and g < 60                           # ends on blue: no jump back at the cut
    assert media.seam_frames(nxt, _colour_clip(tmp_path / "n2.mp4", [("blue", 0.5)]), fps=24) is None


def test_retime_fills_the_section_and_seam_break_is_detected(tmp_path):
    prev = _colour_clip(tmp_path / "a.mp4", [("red", 1.0)])
    nxt = _colour_clip(tmp_path / "b.mp4", [("blue", 1.0)])
    assert media.seam_broken(prev, nxt) is True
    assert media.seam_broken(prev, prev) is False
    norm = media.normalize_clip(prev, tmp_path / "n.mp4", width=64, height=64, fps=24, seconds=1.25,
                                keep_audio=False, retime=1.25)
    assert abs(media.duration(norm) - 1.25) < 0.1


def test_long_section_bounces_the_clip_and_trailing_silence_is_ignored(tmp_path):
    clip = _colour_clip(tmp_path / "a.mp4", [("red", 1.0)])
    norm = media.normalize_clip(clip, tmp_path / "n.mp4", width=64, height=64, fps=24, seconds=3.0,
                                keep_audio=False, retime=3.0)
    assert abs(media.duration(norm) - 3.0) < 0.1
    import subprocess
    song = tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=mono:d=2", "-filter_complex", "[0][1]concat=n=2:v=0:a=1", str(song)],
                   check=True)
    assert 1.9 < media.audible_end(song) < 2.2



def test_song_plan_writes_lyrics_with_the_storyboard(app, client, fake_client):
    pid = _setup(client, music_style="song", music_mode="external")["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    options = client.get(f"/api/projects/{pid}").json()["options"]
    assert "Kucing kecil terbang tinggi" in options["lyrics"]
    assert "Kucing kecil terbang tinggi" in options["music_prompt"]

    mine = "[0:00] Lirik buatan saya"  # a new plan never overwrites lyrics the user has
    client.patch(f"/api/projects/{pid}", json={"options": {"lyrics": mine}})
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    assert client.get(f"/api/projects/{pid}").json()["options"]["lyrics"] == mine


def test_song_plan_keeps_the_storyboard_when_lyrics_fail(app, client, fake_client, monkeypatch):
    from app.pipeline import planner
    def refuse(*args, **kwargs):
        raise planner.PlanError("model tidak mengembalikan lirik bertimestamp")
    monkeypatch.setattr(planner, "song_from_idea", refuse)
    pid = _setup(client, music_style="song", music_mode="external")["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded" and detail["scenes"]
    assert not detail["options"].get("lyrics")


def test_lyrics_can_be_written_before_any_scene(app, client, fake_client):
    pid = _setup(client, music_style="song", music_mode="external")["id"]
    detail = client.post(f"/api/projects/{pid}/song", json={"hint": ""}).json()
    assert "Kucing kecil terbang tinggi" in detail["options"]["lyrics"] and not detail["scenes"]
    assert "Kucing kecil terbang tinggi" in detail["options"]["music_prompt"]

    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    detail2 = client.get(f"/api/projects/{pid}").json()
    assert detail2["scenes"] and detail2["options"]["lyrics"] == detail["options"]["lyrics"]
    assert detail2["options"]["music_prompt"] == detail["options"]["music_prompt"]  # the storyboard must not replace it


def test_instrumental_plan_writes_no_lyrics(app, client, fake_client):
    pid = _setup(client, music_style="instrumental", music_mode="external")["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    assert not client.get(f"/api/projects/{pid}").json()["options"].get("lyrics")


@needs_ffmpeg
def test_song_render_writes_missing_lyrics_and_prompt_first(app, client, fake_client):
    project = _setup(client, music_style="song", music_mode="external")
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    client.patch(f"/api/projects/{pid}", json={"options": {"lyrics": "", "music_prompt": ""}})
    fake_client.calls.clear()
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    assert "Kucing kecil terbang tinggi" in detail["options"]["lyrics"]
    assert "Lyrics:" in detail["options"]["music_prompt"]
    kinds = [c[0] for c in fake_client.calls]
    assert kinds.index("chat") < kinds.index("video")  # written before any billed clip
    video = next(c for c in fake_client.calls if c[0] == "video")
    assert "Kucing kecil terbang tinggi" in video[1]


@needs_ffmpeg
def test_song_render_keeps_user_lyrics_and_only_fills_the_prompt(app, client, fake_client):
    project = _setup(client, music_style="song", music_mode="external")
    pid = project["id"]
    client.post(f"/api/projects/{pid}/plan")
    _run_jobs(app)
    mine = "[0:00] Lirik buatan saya"
    client.patch(f"/api/projects/{pid}", json={"options": {"lyrics": mine, "music_prompt": ""}})
    fake_client.calls.clear()
    client.post(f"/api/projects/{pid}/render", json={"confirm": True})
    _run_jobs(app)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["jobs"][0]["status"] == "succeeded", detail["jobs"][0]["message"]
    assert detail["options"]["lyrics"] == mine
    assert mine in detail["options"]["music_prompt"]
    assert "chat" not in [c[0] for c in fake_client.calls]


@needs_ffmpeg
def test_render_fps_sees_through_repeated_frames(tmp_path):
    """Models deliver 24 fps motion in a 60 fps file; rendering that at 30 repeats every 5th frame."""
    import subprocess
    from app.engine import render_fps
    clip = tmp_path / "pulldown.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=128x72:r=24:d=2",
                    "-vf", "fps=60,format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", str(clip)], check=True)
    assert media.video_fps(clip) == 60
    assert render_fps([clip], 30) == 24


@needs_ffmpeg
def test_seam_colour_gain_and_normalize(tmp_path):
    prev = _colour_clip(tmp_path / "p.mp4", [("0x808080", 0.3)])
    nxt = _colour_clip(tmp_path / "n.mp4", [("0x747474", 0.3)])
    gain = media.seam_colour_gain(prev, nxt)
    assert all(1.05 < g < 1.2 for g in gain)
    out = media.normalize_clip(nxt, tmp_path / "o.mp4", width=64, height=64, fps=24, seconds=0.3,
                               keep_audio=False, preset="ultrafast", gain=gain)
    assert all(abs(a - b) <= 3 for a, b in zip(media.seam_colour_mean(out), media.seam_colour_mean(prev, last=True)))


def test_chain_gains_carry_along_a_chain_and_reset_on_a_new_shot():
    from app.engine import chain_gains
    gains = chain_gains([(1.1, 1.0, 1.0), (1.1, 1.0, 1.0), None, (0.5, 1.0, 1.0)])
    assert gains[0] == (1.0, 1.0, 1.0)
    assert gains[1] == (1.1, 1.0, 1.0)
    assert gains[2][0] == pytest.approx(1.15)  # capped: a real reshoot must not be painted over
    assert gains[3] == (1.0, 1.0, 1.0)
    assert gains[4][0] == pytest.approx(0.85)


def test_trimmed_end_cuts_a_still_tail_within_the_slowdown_limit():
    from app.engine import trimmed_end
    assert trimmed_end(10.08, 8.9, 10.0) == 8.9
    assert trimmed_end(10.08, 6.0, 10.0) == pytest.approx(8.696, abs=0.001)  # capped: no slower than 15 %
    assert trimmed_end(10.08, 9.8, 10.0) is None                             # a short hold stays
    assert trimmed_end(9.09, 7.0, 3.46) is None                              # scene shorter than the action


@needs_ffmpeg
def test_active_seconds_ignores_a_held_pose_and_normalize_drops_it(tmp_path):
    import subprocess
    clip = tmp_path / "held.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=128x72:r=24:d=3,geq=lum='128+100*sin((X+min(N,48)*6)/9)':cb=128:cr=128",
                    "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p", str(clip)], check=True)
    assert abs(media.active_seconds(clip) - 2.0) < 0.3
    out = media.normalize_clip(clip, tmp_path / "o.mp4", width=64, height=64, fps=24, seconds=2.2, keep_audio=False,
                               preset="ultrafast", retime=2.2, active=2.0)
    assert abs(media.duration(out) - 2.2) < 0.15
    assert media.active_seconds(out) > 1.9      # the action now runs to the end instead of stalling
