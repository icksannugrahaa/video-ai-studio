"""Pure units: security, planner parsing, text/subtitles, presets, provider client."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from app.pipeline import planner, presets, subtitles
from app.pipeline.text import chunk_cue, split_sentences, wrap_lines
from app.providers.client import ProviderClient, ProviderError, guess_kind
from app.security import SecretBox, hash_password, mask_secret, new_api_token, verify_password


def test_password_and_tokens():
    stored = hash_password("rahasia-123")
    assert verify_password("rahasia-123", stored)
    assert not verify_password("salah", stored)
    assert not verify_password("x", "garbage")
    token, digest, prefix = new_api_token()
    assert token.startswith("sav_") and len(digest) == 64 and token.startswith(prefix)


def test_secret_box_roundtrip_and_wrong_key():
    box = SecretBox("a" * 40)
    enc = box.encrypt("sk-secret")
    assert "sk-secret" not in enc and box.decrypt(enc) == "sk-secret"
    with pytest.raises(ValueError):
        SecretBox("b" * 40).decrypt(enc)
    assert mask_secret("sk-sandroid-123456") == "sk-s…3456"


def test_extract_json_and_normalize():
    reply = 'Sure!\n```json\n{"title":"T","scenes":[{"visual_prompt":"a","narration":"n","duration":12},' \
            '{"visual_prompt":"","duration":3},{"visual_prompt":"b","duration":"x"}]}\n```'
    board = planner.normalize(planner.extract_json(reply), clip_seconds=5, limit_seconds=60)
    assert board == {"title": "T", "music_prompt": "", "bible": {"character": "", "world": "", "style": ""},
                     "scenes": [
        {"visual_prompt": "a", "narration": "n", "duration": 5.0, "continues": False},
        {"visual_prompt": "b", "narration": "", "duration": 5.0, "continues": False},
    ]}
    capped = planner.normalize({"scenes": [{"visual_prompt": "x", "duration": 5}] * 5}, clip_seconds=5,
                               limit_seconds=12)
    assert len(capped["scenes"]) == 2
    with pytest.raises(planner.PlanError):
        planner.extract_json("no json here")
    with pytest.raises(planner.PlanError):
        planner.normalize({"scenes": []}, clip_seconds=5, limit_seconds=60)


def test_split_sentences_and_cues():
    assert split_sentences("Halo semua. Apa kabar?\nBaik!") == ["Halo semua.", "Apa kabar?", "Baik!"]
    long = split_sentences("kata " * 80, max_chars=50)
    assert all(len(s) <= 50 for s in long)
    cues = chunk_cue("satu dua tiga empat lima enam", 1.0, 4.0, 4)
    assert [c[2] for c in cues] == ["satu dua tiga empat", "lima enam"]
    assert cues[0][0] == 1.0 and cues[-1][1] == 4.0
    assert wrap_lines("a " * 30, 10).count("\n") == 1


def test_subtitles_srt_ass():
    cues = subtitles.build_cues([
        {"offset": 0.0, "sentences": [{"text": "Halo semua", "start": 0.0, "end": 1.2}]},
        {"offset": 3.0, "sentences": [{"text": "Dia {mendarat}", "start": 0.1, "end": 1.0}]},
    ], "bottom")
    assert cues[1] == (3.1, 4.0, "Dia {mendarat}")
    srt = subtitles.to_srt(cues)
    assert "00:00:03,100 --> 00:00:04,000" in srt
    ass = subtitles.to_ass(cues, "bold_center", 720, 1280)
    assert "PlayResY: 1280" in ass and "Dia (mendarat)" in ass and "0:00:03.10" in ass


def test_presets_resolve():
    tiktok = presets.resolve("tiktok", 720)
    assert (tiktok["width"], tiktok["height"], tiktok["model_aspect"]) == (720, 1280, "9:16")
    assert presets.resolve("youtube", 720)[("width")] == 1280
    assert presets.resolve("instagram", 720)["model_aspect"] == "1:1"
    with pytest.raises(ValueError):
        presets.resolve("myspace")


def _resp(status=200, body=None, content=b"", ctype="application/json"):
    r = mock.MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.text = json.dumps(body) if body is not None else ""
    r.content = content
    r.headers = {"Content-Type": ctype}
    return r


def test_client_video_async_job_flow():
    session = mock.MagicMock()
    session.request.side_effect = [
        _resp(202, {"id": "j1", "status": "queued"}),
        _resp(200, {"status": "running"}),
        _resp(200, {"status": "succeeded", "content_url": "/v1/media/jobs/j1/content"}),
        _resp(200, content=b"MP4DATA"),
    ]
    client = ProviderClient("https://ai.example.com/v1", "sk", session=session)
    with mock.patch("app.providers.client.time.sleep"):
        result = client.generate_video("seedance-2.5", "cat", seconds=5, aspect_ratio="9:16", image_png=b"PNG")
    assert result.data == b"MP4DATA"
    body = session.request.call_args_list[0].kwargs["json"]
    assert body["async"] is True and body["duration"] == 5 and body["image"].startswith("data:image/png;base64,")
    assert session.request.call_args_list[-1].args[1] == "https://ai.example.com/v1/media/jobs/j1/content"


def test_client_video_job_failure_and_sync_fallback():
    session = mock.MagicMock()
    session.request.side_effect = [_resp(202, {"id": "j2"}),
                                   _resp(200, {"status": "failed", "error": {"status": 400, "message": "bad prompt"}})]
    client = ProviderClient("https://ai.example.com", "sk", session=session)
    with mock.patch("app.providers.client.time.sleep"), pytest.raises(ProviderError) as err:
        client.generate_video("m", "p")
    assert not err.value.retryable and "bad prompt" in err.value.message

    session = mock.MagicMock()
    session.request.side_effect = [_resp(400, {"error": "unknown field async"}),
                                   _resp(200, {"data": [{"b64_json": "TVA0"}]})]
    client = ProviderClient("https://other.example.com", "sk", session=session)
    assert client.generate_video("m", "p").data == b"MP4"
    assert "async" not in session.request.call_args.kwargs["json"]


def test_guess_kind():
    assert guess_kind("seedance-2.5") == "video"
    assert guess_kind("qwen3-tts-flash") == "tts"
    assert guess_kind("kimi-k3") == "chat"


def test_planner_rules_in_user_message_and_json_repair():
    replies = ["# Konsep video\nScene 1: kucing...", '{"title":"T","scenes":[{"visual_prompt":"cat","narration":"hai","duration":4}]}']
    calls = []

    class Chat:
        def chat(self, model, messages, temperature=0.7, max_tokens=4096):
            calls.append([m["role"] for m in messages])
            return replies.pop(0)

    board = planner.plan_storyboard(Chat(), "m", prompt="kucing", language="id-ID", clip_seconds=5,
                                    target_seconds=10, limit_seconds=60, aspect="9:16")
    assert board["scenes"][0]["visual_prompt"] == "cat"
    assert calls == [["user"], ["user", "assistant", "user"]]  # no system message; one repair turn


def test_client_poll_survives_network_errors_and_maps_failures():
    import requests as _requests
    session = mock.MagicMock()
    session.request.side_effect = [
        _resp(202, {"id": "j3"}),
        _requests.ReadTimeout("slow"),
        _resp(502, {}),
        _resp(200, {"status": "succeeded", "content_url": "/v1/media/jobs/j3/content"}),
        _resp(200, content=b"MP4"),
    ]
    client = ProviderClient("https://ai.example.com", "sk", session=session)
    with mock.patch("app.providers.client.time.sleep"):
        assert client.generate_video("m", "p").data == b"MP4"

    session = mock.MagicMock()
    session.request.side_effect = _requests.ConnectionError("down")
    client = ProviderClient("https://ai.example.com", "sk-secret", session=session)
    with pytest.raises(ProviderError) as err:
        client.chat("m", [{"role": "user", "content": "x"}])
    assert err.value.retryable and "sk-secret" not in err.value.message



def test_policy_refusal_is_not_retried():
    session = mock.MagicMock()
    session.request.side_effect = [_resp(202, {"id": "j9"}), _resp(200, {"status": "failed", "error": {
        "status": 502, "message": "cbi → Task video gagal: {'message': 'The request failed because the output video "
                                  "may be related to copyright restrictions'}"}})]
    client = ProviderClient("https://ai.example.com", "sk", session=session)
    with mock.patch("app.providers.client.time.sleep"), pytest.raises(ProviderError) as err:
        client.generate_video("m", "p")
    assert not err.value.retryable and "ubah prompt" in err.value.message and "copyright" in err.value.message


def test_bible_and_continues_are_normalized():
    board = planner.normalize({"bible": {"character": " An orange cat ", "world": "Jakarta", "extra": "x"},
                               "scenes": [{"visual_prompt": "a", "duration": 3, "continues": True},
                                          {"visual_prompt": "b", "duration": 3, "continues": "yes"},
                                          {"visual_prompt": "c", "duration": 3, "continues": True}]},
                              clip_seconds=5, limit_seconds=60)
    assert board["bible"] == {"character": "An orange cat", "world": "Jakarta", "style": ""}
    # first scene never continues; only a real JSON true counts
    assert [s["continues"] for s in board["scenes"]] == [False, False, True]


def test_clip_prompt_prepends_bible_verbatim():
    legacy = planner.clip_prompt({}, "A cat on a roof")
    assert legacy == "A cat on a roof"
    options = {"bible_style": "Stylized 3D film look.", "bible_character": "A slim orange cat with a blue scarf",
               "bible_world": "Jakarta, Indonesia, 2020s"}
    prompt = planner.clip_prompt(options, "the character naps on a tiled roof at dusk")
    assert prompt.startswith("Stylized 3D film look. Main character, identical in every shot: A slim orange cat")
    assert "Setting: Jakarta, Indonesia, 2020s." in prompt
    assert "Shot: the character naps on a tiled roof at dusk" in prompt
    assert planner.has_bible(options) and not planner.has_bible({"bible_world": "  "})


def test_scene_transitions_cut_continuous_shots_and_cap_fades():
    from app.engine import scene_transitions
    scenes = [{"continues": False}, {"continues": False}, {"continues": True}, {"continues": False}]
    assert scene_transitions(scenes, [6, 6, 6, 1.2], {"transition": 0.5}) == [0.5, 0.0, 0.4, 0.0]
    assert scene_transitions(scenes, [6, 6, 6, 6], {"transition": 0}) == [0.0, 0.0, 0.0, 0.0]
    assert scene_transitions(scenes, [6, 6, 6, 6], {}) == [0.5, 0.0, 0.5, 0.0]  # default 0.5 s
    assert scene_transitions(scenes[:1], [6], {"transition": 1}) == [0.0]


def test_old_database_gets_continues_column(tmp_path):
    import sqlite3
    from app.db import Database
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE scenes (id INTEGER PRIMARY KEY, project_id INTEGER, idx INTEGER, "
                 "visual_prompt TEXT, narration TEXT, duration REAL)")
    conn.commit()
    conn.close()
    db = Database(path)
    columns = {r["name"] for r in db.all("PRAGMA table_info(scenes)")}
    assert {"continues", "clip_gen_seconds", "clip_attempts"} <= columns


def test_clip_chains_follow_continues_flags():
    from app.engine import clip_chains
    scenes = [{"idx": i, "continues": c} for i, c in enumerate([False, True, False, True, True, False])]
    ids = lambda chains: [[s["idx"] for s in c] for c in chains]  # noqa: E731
    assert ids(clip_chains(scenes, continuity=True, bible=True)) == [[0, 1], [2, 3, 4], [5]]
    assert ids(clip_chains(scenes, continuity=False, bible=True)) == [[0], [1], [2], [3], [4], [5]]
    # legacy projects (no bible) seed every scene from the previous one → one chain
    assert ids(clip_chains(scenes, continuity=True, bible=False)) == [[0, 1, 2, 3, 4, 5]]
