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
    assert board == {"title": "T", "music_prompt": "", "bible": {"character": "", "world": "", "style": ""}, "concept": {},
                     "scenes": [
        {"visual_prompt": "a", "narration": "n", "duration": 5.0, "continues": False},
        {"visual_prompt": "b", "narration": "", "duration": 5.0, "continues": False},
    ]}
    capped = planner.normalize({"scenes": [{"visual_prompt": "x", "duration": 5}] * 5}, clip_seconds=5,
                               limit_seconds=12)
    assert len(capped["scenes"]) == 2
    assert planner.extract_json('{"a": [1, 2,], "b": {"c": "x"},}') == {"a": [1, 2], "b": {"c": "x"}}
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



def _sse(*lines):
    r = _resp(ctype="text/event-stream; charset=utf-8")
    r.iter_lines.return_value = [line.encode("utf-8") for line in lines]
    return r


def _chat_client(resp):
    session = mock.MagicMock()
    session.request.return_value = resp
    return ProviderClient("https://ai.example.com", "sk-secret", session=session), session


def test_chat_streams_so_the_router_heartbeat_outlives_the_proxy_timeout():
    client, session = _chat_client(_sse(
        ": keep-alive", "",
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"content":"Apel "}}]}',
        'data: {"choices":[{"delta":{"content":"merah é"}}]}',
        "data: [DONE]"))
    assert client.chat("m", [{"role": "user", "content": "x"}]) == "Apel merah é"
    kwargs = session.request.call_args.kwargs
    assert kwargs["json"]["stream"] is True and kwargs["stream"] is True


def test_chat_accepts_a_plain_json_reply_and_a_whole_message_in_the_stream():
    client, _ = _chat_client(_resp(200, {"choices": [{"message": {"content": "halo"}}]}))
    assert client.chat("m", []) == "halo"
    client, _ = _chat_client(_sse('data: {"choices":[{"message":{"content":"utuh"}}]}', "data: [DONE]"))
    assert client.chat("m", []) == "utuh"


def test_chat_reports_errors_inside_the_stream_and_a_broken_stream():
    import requests as _requests
    client, _ = _chat_client(_sse(": keep-alive", 'data: {"error":{"message":"semua provider gagal","status":503}}'))
    with pytest.raises(ProviderError) as err:
        client.chat("m", [])
    assert err.value.status == 503 and err.value.retryable and "semua provider gagal" in err.value.message

    broken = _sse()
    broken.iter_lines.side_effect = _requests.exceptions.ChunkedEncodingError("cut")
    client, _ = _chat_client(broken)
    with pytest.raises(ProviderError) as err:
        client.chat("m", [])
    assert err.value.retryable and "sk-secret" not in err.value.message

    client, _ = _chat_client(_sse(": keep-alive", "data: [DONE]"))
    with pytest.raises(ProviderError, match="tidak mengembalikan teks"):
        client.chat("m", [])


def test_chat_gives_up_when_only_keep_alives_arrive():
    client, _ = _chat_client(_sse(": keep-alive", ": keep-alive"))
    with mock.patch("app.providers.client.time.monotonic", side_effect=[0, 10 ** 6]), \
            pytest.raises(ProviderError, match="timeout") as err:
        client.chat("m", [])
    assert err.value.status == 504


def test_error_page_html_never_reaches_the_user():
    page = mock.MagicMock(status_code=524, text="<!DOCTYPE html><html>Cloudflare</html>")
    page.json.side_effect = ValueError
    client, _ = _chat_client(page)
    with pytest.raises(ProviderError) as err:
        client.chat("m", [])
    assert "<" not in err.value.message and "HTTP 524" in err.value.message


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
    assert scene_transitions(scenes, [6, 6, 6, 1.2], {"transition": 0.5}) == [0.5, 0.2, 0.4, 0.0]
    assert scene_transitions(scenes, [6, 6, 6, 6], {"transition": 0}) == [0.0, 0.0, 0.0, 0.0]
    assert scene_transitions(scenes, [6, 6, 6, 6], {}) == [0.5, 0.2, 0.5, 0.0]  # default 0.5 s
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


def test_normalize_keeps_scenes_at_least_four_seconds():
    board = planner.normalize({"scenes": [{"visual_prompt": "x", "duration": 3}, {"visual_prompt": "y", "duration": 2}]},
                              clip_seconds=8, limit_seconds=60)
    assert [s["duration"] for s in board["scenes"]] == [4.0, 4.0]
    assert planner.min_clip_seconds(3) == 3  # a profile capped below 4 s still gets its own length


def test_requeue_interrupted_resets_in_flight_clips(tmp_path):
    from app.db import Database
    from app.repo import Repo
    repo = Repo(Database(tmp_path / "app.db"))
    uid = repo.create_user("u", "password123")
    pid = repo.create_project(uid, {"prompt": "x"})
    repo.replace_scenes(pid, [{"visual_prompt": "a", "narration": "", "duration": 4},
                              {"visual_prompt": "b", "narration": "", "duration": 4}])
    first, second = repo.scenes(pid)
    repo.update_scene(first["id"], clip_status="running")
    repo.update_scene(second["id"], clip_status="done")
    repo.requeue_interrupted()
    assert [s["clip_status"] for s in repo.scenes(pid)] == ["pending", "done"]


def test_song_mode_clip_prompt_carries_the_lines_sung_in_that_shot():
    options = {"bible_style": "3D", "music_prompt": "Kids pop, 120 BPM, ukulele",
               "lyrics": "[Intro]\n[0:00] Hai teman\n[0:04] Satu, dua, tunjuk jari\n[0:06] Ikuti lagu ini\n[0:09] Ketuk"}
    sung = planner.sung_direction(options, 4.0, 8.0)
    assert '0s "Satu, dua, tunjuk jari"' in sung and '2s "Ikuti lagu ini"' in sung
    assert "Hai teman" not in sung and "Ketuk" not in sung and "120 BPM" in sung
    assert "Ikuti" not in planner.sung_direction(options, 8.0, 12.0)    # sung back in the previous shot
    assert '0s "Hai teman"' in planner.sung_direction(options, 1.0, 3.5)  # nothing new: the carried line
    prompt = planner.clip_prompt(options, "the character counts", sung=sung)
    assert prompt.index("Shot:") < prompt.index("tunjuk jari") < prompt.index("No on-screen text")
    assert planner.sung_direction({"music_prompt": "90 BPM"}, 0, 4).endswith("on the beat at 90 BPM.")
    assert planner.sung_direction({}, 0, 4) == ""


def test_planner_asks_for_a_visible_concept_and_keeps_it():
    sent = []

    class Chat:
        def chat(self, model, messages, temperature=0.7, max_tokens=4096):
            sent.append(messages[-1]["content"])
            return ('{"title": "Ayo Berhitung 1 sampai 3", "concept": {"promise": "counting 1 to 3 with apples",'
                    ' "beats": ["one apple", "two apples", " ", "three apples"]},'
                    ' "scenes": [{"visual_prompt": "the character picks up exactly one red apple", "duration": 4}]}')

    board = planner.plan_storyboard(Chat(), "m", prompt="video berhitung", language="id-ID", clip_seconds=5,
                                    target_seconds=10, limit_seconds=60, aspect="9:16", song=True)
    assert board["concept"] == {"promise": "counting 1 to 3 with apples",
                                "beats": ["one apple", "two apples", "three apples"]}
    assert "VISIBLE in every scene" in sent[0] and "music video with a sung song" in sent[0]
    planner.plan_storyboard(Chat(), "m", prompt="x", language="id-ID", clip_seconds=5,
                            target_seconds=10, limit_seconds=60, aspect="9:16")
    assert "music video with a sung song" not in sent[1]


def _song_scenes():
    return [{"idx": 0, "narration": "Satu", "duration": 5}, {"idx": 1, "narration": "Dua", "duration": 5}]


def test_song_lengths_put_cuts_on_sung_lines_and_keep_the_last_word():
    from app.pipeline import planner
    lyrics = "[Verse]\n[0:00.4] Satu apel!\n[0:02.9] Ayo hitung satu!\n[0:05.2] Dua apel!\n[0:08.0]"
    assert planner.song_lengths(_song_scenes(), lyrics, 40.0) == [5.2, 4.8]  # 8.0 + 2 s fade
    assert planner.song_lengths(_song_scenes(), lyrics, 9.0) == [5.2, 3.8]   # never past the song
    assert [c[1] for c in planner.parse_lyrics(lyrics, 10.0)] == [2.9, 5.2, 8.0]


def test_song_lengths_follow_timestamps_even_when_lyric_words_differ_from_narration():
    from app.pipeline import planner
    lyrics = "[0:00] Kata lain sama sekali\n[0:05] Baris kedua"
    assert planner.song_lengths(_song_scenes(), lyrics, 33.5) == [5.0, 28.5]
    assert planner.song_lengths(_song_scenes(), "[0:00] Satu\n[0:30] Jauh sekali", 12.0) == [5.0, 7.0]  # no line near
    assert planner.song_lengths(_song_scenes(), "") is None
    assert planner.song_lengths(_song_scenes(), "[0:00] Satu", 5.5) is None  # song too short for the scenes


def test_broken_seam_gets_a_full_crossfade_and_good_seam_a_short_dissolve():
    from app.engine import scene_transitions
    scenes = [{"continues": False}, {"continues": True}]
    assert scene_transitions(scenes, [6, 6], {"transition": 0.5}) == [0.2, 0.0]
    assert scene_transitions(scenes, [6, 6], {"transition": 0.5}, {0}) == [0.5, 0.0]
    assert scene_transitions(scenes, [6, 6], {"transition": 0}, {0}) == [0.0, 0.0]


def test_prompts_never_ask_for_finger_counts():
    from app.pipeline import planner
    sung = planner.sung_direction({"lyrics": "[0:00] Tiga apel"}, 0.0, 4.0)
    assert "without hand signs" in sung and "holding up" not in sung
    assert "holds up" not in planner._SYSTEM


def test_clip_prompt_adds_production_direction_and_seed_order():
    from app.pipeline import planner
    options = {"bible_style": "35mm look"}
    plain = planner.clip_prompt(options, "A cat jumps")
    assert planner.SHOT_CRAFT in plain and planner.SEEDED_SHOT not in plain
    assert planner.SEEDED_SHOT in planner.clip_prompt(options, "A cat jumps", seeded=True)
    assert planner.clip_prompt({}, "A cat jumps") == "A cat jumps"  # projects without a bible keep their prompt


def test_lyric_parts_cut_on_sung_lines_and_cover_the_song():
    lyrics = "[Intro]\n[0:03] Satu apel\n[0:07] Dua apel\n[0:12] Tiga apel\n[0:27] Selesai"
    parts = planner.lyric_parts(lyrics, 30.0, 5)
    assert parts[0] == (0.0, 3.0, "") and parts[1] == (3.0, 7.0, "Satu apel") and parts[2] == (7.0, 12.0, "Dua apel")
    assert parts[-1][1] == 30.0 and all(a[1] == b[0] for a, b in zip(parts, parts[1:]))
    assert all(end - start <= 5 for start, end, _ in parts[:-1])
    assert " ".join(words for _, _, words in parts).split() == "Satu apel Dua apel Tiga apel Selesai".split()
    assert planner.lyric_parts("tanpa waktu", 30.0, 5) == []
    tail = planner.lyric_parts("[0:04] a", 9.5, 5)  # 0.5 s left over is too short to film
    assert tail[-1][1] == 9.5 and tail[-1][1] - tail[-1][0] >= 2


def _board(count):
    return json.dumps({"scenes": [{"visual_prompt": f"shot {i}", "narration": "x", "duration": 5} for i in range(count)]})


def test_storyboard_takes_its_timing_and_words_from_the_song():
    class Chat:
        request = ""
        reply = _board(2)
        def chat(self, model, messages, temperature=0.7, max_tokens=4096):
            Chat.request = messages[-1]["content"]
            return Chat.reply
    args = dict(prompt="ide", language="id-ID", clip_seconds=5, target_seconds=30, limit_seconds=180, aspect="9:16")
    board = planner.plan_storyboard(Chat(), "m", **args, song=True, lyrics="[0:00] Satu apel\n[0:04] Dua apel", song_seconds=8.0)
    assert "exactly 2 scenes" in Chat.request and "0:04-0:08: Dua apel" in Chat.request
    assert [(s["duration"], s["narration"]) for s in board["scenes"]] == [(4.0, "Satu apel"), (4.0, "Dua apel")]

    Chat.reply = _board(3)  # a wrong count keeps the model's scenes; the render still cuts them to the song
    board = planner.plan_storyboard(Chat(), "m", **args, song=True, lyrics="[0:00] Satu apel\n[0:04] Dua apel", song_seconds=8.0)
    assert [s["duration"] for s in board["scenes"]] == [5.0, 5.0, 5.0]

    planner.plan_storyboard(Chat(), "m", **args)
    assert "The song already exists" not in Chat.request


def test_counted_objects_are_placed_once_and_have_room():
    from app.pipeline import planner
    assert "never repeated" in planner.SHOT_CRAFT and "none is stacked" in planner.SHOT_CRAFT
    assert "by the third second" in planner._SYSTEM and "empty space" in planner._SYSTEM
    assert "including the closing shot" in planner._SYSTEM


def test_continuing_shot_starts_in_the_state_the_previous_shot_ends_in():
    from app.pipeline import planner
    first = "Medium shot. START: two apples. ACTION: adds one. END: exactly three apples, no others."
    scenes = [{"visual_prompt": first, "continues": False},
              {"visual_prompt": "Medium shot. START: two apples. ACTION: adds one. END: four apples.", "continues": True},
              {"visual_prompt": "Wide. START: a bowl. ACTION: waves. END: a bowl.", "continues": False}]
    planner.link_shots(scenes)
    assert scenes[0]["visual_prompt"] == first
    assert scenes[1]["visual_prompt"] == ("Medium shot. START: exactly three apples, no others. ACTION: adds one. "
                                          "END: four apples.")
    assert "START: a bowl." in scenes[2]["visual_prompt"]  # a new location does not inherit anything


def test_place_objects_are_taken_from_stays_in_every_later_shot():
    from app.pipeline import planner
    # Project 11: the basket was only named in ACTION, vanished mid clip and was missing from the next seed frame.
    scenes = [{"visual_prompt": "Table. START: one apple, no other apples. ACTION: lifts a second apple from a basket "
                                "at the right edge, sets it down. END: two apples, no other apples.", "continues": False},
              {"visual_prompt": "Table. START: x. ACTION: lifts a third apple from the basket at the right edge, "
                                "sets it down. END: three apples, no other apples.", "continues": True},
              {"visual_prompt": "Table. START: x. ACTION: sweeps a palm above the apples. END: three apples.", "continues": True},
              {"visual_prompt": "Yard. START: a ball. ACTION: kicks it. END: a ball.", "continues": False}]
    planner.keep_sources(scenes)
    planner.link_shots(scenes)
    for scene in scenes[:3]:
        start, end = scene["visual_prompt"].split("ACTION:")[0], scene["visual_prompt"].split("END:")[1]
        assert "basket at the right edge stays in clear view" in start
        assert "basket at the right edge stays in clear view" in end
    assert scenes[0]["visual_prompt"].count("stays in clear view") == 2  # once in START, once in END
    assert "basket" not in scenes[3]["visual_prompt"]  # a new location does not inherit it


def test_container_named_without_a_place_gets_one():
    from app.pipeline import planner
    scenes = [{"visual_prompt": "Table. START: one apple and exactly four in the right-end basket, no other apples. ACTION: "
                                "takes one apple from basket, places it. END: exactly two apples and exactly three in "
                                "right-end basket, no other apples.", "continues": False},
              {"visual_prompt": "Table. START: x. ACTION: claps. END: exactly two apples and the right-end basket empty.",
               "continues": True}]
    planner.keep_sources(scenes)
    planner.link_shots(scenes)
    for scene in scenes:
        start, end = scene["visual_prompt"].split("ACTION:")[0], scene["visual_prompt"].split("END:")[1]
        assert "closest to the camera" in start and "closest to the camera" in end
    once = [s["visual_prompt"] for s in scenes]
    planner.keep_sources(scenes)
    assert [s["visual_prompt"] for s in scenes] == once  # a replan of an unchanged shot does not regenerate it
    assert planner.end_checks(scenes[1]["visual_prompt"])["visible"] == ["basket"]


def test_source_already_stated_or_no_source_leaves_the_prompt_alone():
    from app.pipeline import planner
    stated = ("Table. START: one apple and a basket on the table. ACTION: takes an apple from the basket. "
              "END: two apples and a basket on the table.")
    plain = "She walks from the door to the table, smiling."
    scenes = [{"visual_prompt": stated, "continues": False}, {"visual_prompt": plain, "continues": False}]
    planner.keep_sources(scenes)
    assert [s["visual_prompt"] for s in scenes] == [stated, plain]


def test_end_checks_read_project_11_shots_and_compare_the_reading():
    from app.pipeline import planner
    scenes = [{"visual_prompt": "T. START: one apple. ACTION: Bu Mila lifts a second large red apple from a basket at the "
                                "right edge, sets it down. END: Bu Mila hands at her sides; exactly three large red apples "
                                "in a row, no other apples.", "continues": False},
              {"visual_prompt": "T. START: x. ACTION: sweeps a palm. END: exactly 5 apples, no other apples.", "continues": True}]
    planner.keep_sources(scenes)
    first, closing = (planner.end_checks(s["visual_prompt"]) for s in scenes)
    assert first == {"count": 3, "noun": "apples", "visible": ["basket"]}
    assert closing == {"count": 5, "noun": "apples", "visible": ["basket"]}
    assert '"basket":false' in planner.end_question(first) and "Count the apples" in planner.end_question(first)
    assert planner.end_problems(first, {"count": 3, "visible": {"basket": True}}) == []
    assert planner.end_problems(first, {"count": 2, "visible": {"basket": False}}) == ["apples 2, seharusnya 3", "basket tidak terlihat"]
    assert planner.end_problems(first, {"count": "tiga"}) == []  # no clear mismatch, no bill
    assert planner.end_checks("A cat jumps over a wall") is None
    assert planner.end_checks("START: a. ACTION: b. END: the cat sleeps.") is None
    assert planner.end_checks("END: exactly two apples and exactly one more in the basket.")["visible"] == ["basket"]


def test_end_checks_find_the_container_however_the_planner_words_it():
    from app.pipeline import planner
    bare = ("START: one. ACTION: Bu Guru takes one apple from basket, places it right of the first. "
            "END: exactly three apples in row and exactly two in right-end basket, no other apples.")
    empty = "START: five. ACTION: she claps. END: exactly five apples in row and the right-end basket empty, no other apples."
    assert planner.end_checks(bare) == {"count": 3, "noun": "apples", "visible": ["basket"]}
    assert planner.end_checks(empty) == {"count": 5, "noun": "apples", "visible": ["basket"]}
    assert planner.end_checks("START: a. ACTION: b. END: exactly three apples in row, no other apples.")["visible"] == []


def test_later_shots_of_a_sequence_also_check_the_container_of_earlier_shots():
    from app.pipeline import planner
    scenes = [{"idx": 0, "continues": 0, "visual_prompt": "START: a. ACTION: takes 1 apple from basket. END: row: exactly 3 apples."},
              {"idx": 1, "continues": 1, "visual_prompt": "START: a. ACTION: sways. END: row: exactly 3 apples."},
              {"idx": 2, "continues": 1, "visual_prompt": "START: a. ACTION: sways. END: she smiles."},
              {"idx": 3, "continues": 0, "visual_prompt": "START: a. ACTION: runs. END: exactly 2 dogs."}]
    assert planner.sequence_checks(scenes, scenes[1])["visible"] == ["basket"]
    assert planner.sequence_checks(scenes, scenes[2]) == {"count": None, "noun": "", "visible": ["basket"]}
    assert planner.sequence_checks(scenes, scenes[3])["visible"] == []  # a new location does not inherit it


def test_generated_project_11_wording_gets_no_false_check_and_no_bloat():
    from app.pipeline import planner
    shot = ("Table. START: exactly 1 red apple row far left, exactly 4 in basket front right corner, no other apples. "
            "ACTION: Melati takes 1 from basket, places right of first. "
            "END: exactly 2 red apples row far left, exactly 3 in basket front right corner, no other apples.")
    scenes = [{"visual_prompt": shot, "continues": False}]
    planner.keep_sources(scenes)
    assert scenes[0]["visual_prompt"] == shot  # it already says where the basket is
    assert planner.end_checks(shot)["visible"] == ["basket"]  # never asks for a "corner"
    bare = [{"visual_prompt": "T. START: a basket, 2 apples. ACTION: takes 1 from basket. END: basket empty.", "continues": False}]
    planner.keep_sources(bare)
    assert len(bare[0]["visual_prompt"].split()) < 50


def test_fixed_camera_shots_get_the_tripod_order():
    from app.pipeline import planner
    options = {"bible_style": "35mm look"}
    assert planner.CAMERA_LOCK in planner.clip_prompt(options, "Table; locked-off camera. START: a. ACTION: b. END: c.")
    assert planner.CAMERA_LOCK in planner.clip_prompt(options, "Table; camera stays still. START: a. ACTION: b. END: c.")
    assert planner.CAMERA_LOCK in planner.clip_prompt(options, "Room, medium-wide fixed 35mm shot. START: a. ACTION: b. END: c.")
    assert planner.CAMERA_LOCK in planner.clip_prompt(options, "Same table, medium-wide 35mm, locked-off. START: a. ACTION: b. END: c.")
    assert planner.CAMERA_LOCK not in planner.clip_prompt(options, "Street; slow dolly. START: a fixed price tag. ACTION: b. END: c.")
    assert planner.CAMERA_LOCK not in planner.clip_prompt(options, "Street; slow dolly. START: a. ACTION: b. END: c.")


def test_seeded_clip_is_told_what_the_previous_shot_showed_unless_it_has_a_start():
    from app.pipeline import planner
    options = {"bible_style": "35mm look"}
    prompt = planner.clip_prompt(options, "She adds an apple", seeded=True, previous="Three apples sit on the table")
    assert "previous shot, which showed: Three apples sit on the table" in prompt
    ended = planner.clip_prompt(options, "She adds an apple", seeded=True, previous="START: a. ACTION: b. END: three apples")
    assert "which showed: three apples" in ended and "ACTION: b" not in ended
    spelled = planner.clip_prompt(options, "START: three. ACTION: adds. END: four.", seeded=True, previous="x")
    assert "previous shot" not in spelled
    assert "previous shot" not in planner.clip_prompt(options, "She adds an apple", previous="x")  # not seeded


def test_video_length_follows_the_song_when_lyrics_have_no_end_marker():
    from app.pipeline import planner
    scenes = [{"idx": 0, "narration": "Satu apel!", "duration": 5}, {"idx": 1, "narration": "Dua apel!", "duration": 5}]
    lyrics = "[0:00] Satu apel!\n[0:05] Dua apel!"
    assert planner.song_lengths(scenes, lyrics, 40.0) == [5.0, 35.0]
    assert planner.song_lengths(scenes, lyrics) == [5.0, 5.0]
    assert planner.fit_lengths([5.0, 5.0], 40.0) == [20.0, 20.0]

