"""Chat-thread arcs: validation, distinct voices, overlay timing and series-only production.

Offline: speech is mocked with locally generated tones, and no model, TTS or
upload request is made.
"""

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from config import DEFAULT_VOICE, NARRATION_TAIL_SECONDS
from shorts_automation.automation import production as p
from shorts_automation.automation import series_queue
from shorts_automation.automation.orchestrator import JobQueue
from shorts_automation.publishing.youtube_uploader import build_short_metadata
from shorts_automation.rendering import chat_overlay
from shorts_automation.state.usage_store import UsageStore
from shorts_automation.stories import tts_engine as tts
from shorts_automation.stories.draft_story import validate_story
from shorts_automation.stories.series_story import episode_story, read_manifest, save_series
from tests.series_helpers import SeriesHarness, chat_arc


def chat_story(**changes):
    story = {
        "title": "The Receipt In His Jacket",
        "format": "chat",
        "protagonist_gender": "female",
        "narrator_gender": "female",
        "chat": {
            "contacts": [{"name": "Jordan", "gender": "male"}],
            "contact": "Jordan",
            "messages": [
                {"from": "me", "text": "Why is there a ring receipt in your jacket?"},
                {"from": "me", "text": "Answer me."},
                {"from": "Jordan", "text": "It is for my sister."},
                {"from": "me", "text": "Your sister told me she is not engaged."},
            ],
        },
    }
    story["chat"].update(changes)
    return story


class ChatValidationTests(unittest.TestCase):
    def test_valid_chat_derives_transcript_and_keeps_thread(self):
        story = validate_story(chat_story())
        self.assertEqual(story["format"], "chat")
        self.assertTrue(story["script"].startswith("Me: Why is there"))
        self.assertIn("Jordan: It is for my sister.", story["script"])
        self.assertEqual(story["chat"]["messages"][2]["from"], "Jordan")

    def test_rejects_emoji_links_strangers_and_one_sided_threads(self):
        bad = [
            {"messages": [{"from": "me", "text": "Hi 😡"}] * 4},
            {
                "messages": [{"from": "me", "text": "see www.example.com"}] * 2
                + [{"from": "Jordan", "text": "ok"}] * 2
            },
            {"messages": [{"from": "Casey", "text": "hello there"}] * 4},
            {"messages": [{"from": "me", "text": "hello there"}] * 4},
            {"contact": "Casey"},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_story(chat_story(**change))

    def test_rejects_chats_too_long_to_voice(self):
        long = [{"from": "me", "text": " ".join(["word"] * 29)}, {"from": "Jordan", "text": "no"}]
        with self.assertRaisesRegex(ValueError, "at most"):
            validate_story(chat_story(messages=long * 4))

    def test_series_round_trip_keeps_format_cast_and_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity = "a" * 32
            path = save_series(chat_arc(token="x"), identity, tmp, "premise")
            manifest = read_manifest(path, identity, 3, "premise")
            self.assertEqual(manifest["format"], "chat")
            story = episode_story(manifest, 2)
            self.assertEqual(story["story_revision"], "chat-v1")
            self.assertEqual(story["chat"]["contacts"], [{"name": "Jordan", "gender": "male"}])
            self.assertEqual(story["series"]["part"], 2)

    def test_series_rejects_parts_with_unlisted_contacts(self):
        data = chat_arc()
        data["parts"][1]["contact"] = "Casey"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            save_series(data, "b" * 32, tmp, "premise")


class ChatVoiceTests(unittest.TestCase):
    def settings(self, tmp, **extra):
        (Path(tmp) / "fish.local.json").write_text(
            json.dumps({"voice_id": "male-ref", "female_voice_id": "female-ref", **extra})
        )

    def test_opposite_gender_contact_uses_the_two_story_voices(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tts, "SECRETS_DIR", Path(tmp)),
            patch.dict("os.environ", {}, clear=True),
        ):
            self.settings(tmp)
            story = validate_story(chat_story())
            self.assertEqual(
                tts.chat_voice_plan(story, "fish"), {"me": "female-ref", "Jordan": DEFAULT_VOICE}
            )
            self.assertEqual(
                tts.chat_voice_identity(story, "fish"), "chat:me=female-ref|Jordan=male-ref"
            )
            self.assertEqual(tts.chat_contact_capacity("fish", "female"), {"male": 1, "female": 0})

    def test_same_gender_contact_needs_an_extra_voice_before_any_tts(self):
        story = chat_story(contacts=[{"name": "Jordan", "gender": "female"}])
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tts, "SECRETS_DIR", Path(tmp)),
            patch.dict("os.environ", {}, clear=True),
        ):
            self.settings(tmp)
            with self.assertRaisesRegex(RuntimeError, "chat_extra_voice_ids"):
                tts.chat_voice_plan(validate_story(story), "fish")
            self.settings(tmp, chat_extra_voice_ids={"female": ["female-2"]})
            plan = tts.chat_voice_plan(validate_story(story), "fish")
            self.assertEqual(plan, {"me": "female-ref", "Jordan": "female-2"})

    def test_generate_chat_speech_offsets_words_and_joins_gaps(self):
        # Edge needs no settings; keep PATH so the local ffmpeg can run.
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts, "AUDIO_DIR", Path(tmp)):

            def fake_speech(text, voice, provider):
                path = Path(tmp) / f"clip_{abs(hash((text, voice)))}.mp3"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=440:duration=1",
                        str(path),
                    ],
                    check=True,
                )
                path.with_suffix(".json").write_text(json.dumps({"voice": voice}))
                words = text.split()
                return (
                    path,
                    tts.audio_duration(path),
                    [
                        {"text": w, "start": i / len(words), "end": (i + 1) / len(words)}
                        for i, w in enumerate(words)
                    ],
                )

            story = validate_story(chat_story())
            with (
                patch.object(tts, "generate_speech", side_effect=fake_speech),
                redirect_stdout(io.StringIO()),
            ):
                path, duration, words, timeline = tts.generate_chat_speech(story, "edge")
            starts = [item["start"] for item in timeline["messages"]]
            clip = timeline["messages"][0]["end"]
            # me -> me is a short gap; me -> Jordan leaves time to show typing.
            self.assertAlmostEqual(starts[1] - starts[0], clip + 0.25, places=2)
            self.assertAlmostEqual(starts[2] - starts[1], clip + 0.5, places=2)
            self.assertAlmostEqual(duration, starts[-1] + clip, delta=0.08)
            self.assertEqual({w["message"] for w in words}, {0, 1, 2, 3})
            self.assertGreaterEqual(words[-1]["start"], starts[3])
            saved = json.loads(path.with_suffix(".json").read_text())
            self.assertEqual(saved["voice"], tts.chat_voice_identity(story, "edge"))


class ChatOverlayTests(unittest.TestCase):
    def timeline(self):
        story = validate_story(chat_story())
        timeline = [
            {"start": 0.0, "end": 1.0, "from": "me"},
            {"start": 1.25, "end": 2.0, "from": "me"},
            {"start": 2.5, "end": 3.5, "from": "Jordan"},
            {"start": 3.75, "end": 5.0, "from": "me"},
        ]
        words = []
        for index, item in enumerate(timeline):
            tokens = story["chat"]["messages"][index]["text"].split()
            step = (item["end"] - item["start"]) / len(tokens)
            words += [
                {
                    "text": t,
                    "start": item["start"] + i * step,
                    "end": item["start"] + (i + 1) * step,
                    "message": index,
                }
                for i, t in enumerate(tokens)
            ]
        return story, words, timeline

    def test_states_cover_audio_and_tail_with_typing_and_highlight(self):
        story, words, timeline = self.timeline()
        series = {"part": 1, "total": 3}
        states = chat_overlay.build_chat_states(story, words, timeline, 5.0, series)
        self.assertAlmostEqual(states[0][1], 0.0)
        self.assertAlmostEqual(states[-1][2], 5.0 + NARRATION_TAIL_SECONDS)
        for (_, _, end), (_, start, _) in zip(states, states[1:]):
            self.assertAlmostEqual(end, start)
        typing = [s for s in states if s[0][2]]
        self.assertTrue(typing and all(2.0 <= s[1] and s[2] <= 2.5 for s in typing))
        self.assertEqual(states[0][0][1], (0, 0))  # first spoken word is highlighted
        self.assertTrue(states[-1][0][3])  # continuation cue at the end of nonfinal parts
        self.assertEqual(states[-1][0][0], 4)

    def test_mismatched_provider_tokens_map_forward(self):
        mapping = chat_overlay.map_spoken_words(
            ["Meet", "at", "3am,", "okay?"], ["Meet", "at", "3", "am", "okay"]
        )
        self.assertEqual(mapping, [0, 1, 2, 2, 3])

    def test_stream_renders_frames_with_exact_total_duration(self):
        story, words, timeline = self.timeline()
        story["series"] = {
            "id": "c" * 32,
            "title": "The Receipt In His Jacket",
            "part": 3,
            "total": 3,
            "ending": "finale",
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(chat_overlay, "TEMP_DIR", Path(tmp)),
            redirect_stdout(io.StringIO()),
        ):
            concat = chat_overlay.generate_chat_stream(
                story, words, timeline, 5.0, series=story["series"]
            )
            durations = [
                float(line.split()[1])
                for line in concat.read_text().splitlines()
                if line.startswith("duration")
            ]
            frames = list(Path(concat).parent.glob("chat_*.png"))
        self.assertAlmostEqual(sum(durations), 5.0 + NARRATION_TAIL_SECONDS, places=4)
        self.assertGreater(len(frames), 10)


class SeriesOnlyProductionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in (
            ("STORAGE_DIR", self.root),
            ("TEMP_DIR", self.root / "temp"),
            ("OUTPUT_DIR", self.root),
        ):
            self.enterContext(patch.object(p, name, value))
        self.queue = JobQueue(self.root / "queue.sqlite3")
        self.usage = UsageStore(self.queue.path)
        self.usage.import_outputs = lambda: 0
        self.harness = SeriesHarness(self.root)
        self.now = datetime(2099, 1, 1, tzinfo=timezone.utc)
        self.config = p.load_config() | {
            "story_format": "series",
            "series_formats": ["narrated", "chat"],
            "minimum_scheduled_videos": 3,
            "footage_discovery": "fixed",
            "fish_free_until": "2099-12-31",
            "publish_enabled": True,
            "private_upload_enabled": False,
            "telegram_notify_enabled": False,
            "lookahead_hours": 72,
            "max_jobs_per_pass": 1,
            "series_parts": [3],
            "series_min_lead_hours": 4,
        }
        self.enterContext(redirect_stdout(io.StringIO()))

    def seed(self, count=3):
        rows = p.plan(self.queue, self.config, self.now)
        for n, row in enumerate(rows[:count]):
            self.queue.move(
                row["id"],
                ("queued",),
                "scheduled",
                youtube_id=f"buffer{n:05d}",
                scheduled_at=row["publish_at"],
            )
        return rows

    def cycle(self):
        return p.cycle(
            self.config,
            self.queue,
            self.usage,
            self.harness.drafter,
            self.harness.renderer,
            validator=lambda *a: {},
            service_factory=lambda: object(),
            now=self.now,
            health_path=self.root / "health.json",
            lock_path=self.root / "runner.lock",
            series_drafter=self.harness.series_drafter,
        )

    def test_config_accepts_series_mode_and_rejects_unknown_formats(self):
        self.assertEqual(p.load_config()["series_formats"], ["narrated", "chat"])
        with tempfile.TemporaryDirectory() as tmp:
            raw = json.loads(p.CONFIG_PATH.read_text(encoding="utf-8-sig"))
            path = Path(tmp) / "production.json"
            path.write_text(json.dumps(raw | {"story_format": "series"}))
            self.assertEqual(p.load_config(path)["story_format"], "series")
            path.write_text(json.dumps(raw | {"series_formats": ["podcast"]}))
            with self.assertRaises(ValueError):
                p.load_config(path)

    def test_below_minimum_reserve_still_prepares_an_arc_never_a_standalone(self):
        self.seed(2)
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            side_effect=[{"id": f"serial{n:05d}"} for n in range(3)],
        ) as upload:
            for _ in range(3):
                self.cycle()
        self.assertEqual(len(self.harness.drafts), 1)
        self.assertEqual(len(self.harness.renders), 3)
        self.assertTrue(all("series" in story for story in self.harness.renders))
        self.assertEqual(upload.call_count, 3)

    def test_arcs_alternate_between_narrated_and_chat(self):
        rows = self.seed()
        first = p.assign_series(self.queue, self.config, self.now)
        slots = {row["id"]: row["publish_at"] for row in rows}
        for member in series_queue.members(self.queue, first):
            self.queue.move(
                member["id"],
                ("queued",),
                "scheduled",
                youtube_id=f"arc{member['series_part']:08d}",
                scheduled_at=slots[member["id"]],
            )
        second = p.assign_series(self.queue, self.config, self.now)
        formats = [series_queue.info(self.queue, rows[i]["id"])["format"] for i in (3, 6)]
        self.assertEqual(formats, ["narrated", "chat"])
        self.assertNotEqual(first, second)
        chat = series_queue.info(self.queue, rows[6]["id"])
        self.assertTrue(chat["topic"].startswith("Texting with"))

    def test_chat_arc_drafts_with_chat_format_and_renders_in_order(self):
        rows = self.seed()
        with self.queue.connect() as db:
            db.execute(
                "INSERT INTO story_series (id,topic,tts_provider,part_count,created_at,format) "
                "VALUES (?,?,?,?,?,?)",
                ("d" * 32, "old", "fish", 3, "2000-01-01", "narrated"),
            )
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            side_effect=[{"id": f"serial{n:05d}"} for n in range(3)],
        ):
            for _ in range(3):
                self.cycle()
        self.assertEqual([s["series"]["part"] for s in self.harness.renders], [1, 2, 3])
        self.assertTrue(all(s["format"] == "chat" for s in self.harness.renders))
        self.assertEqual(self.queue.get(rows[3]["id"])["stage"], "scheduled")

    def test_imminent_unassigned_slot_is_skipped_not_drafted_as_standalone(self):
        self.now = datetime(2099, 1, 1, 10, tzinfo=timezone.utc)  # 12:00Z slot is 2h away
        rows = self.seed(0)
        identity = p.assign_series(self.queue, self.config, self.now)
        members = [m["id"] for m in series_queue.members(self.queue, identity)]
        self.assertNotIn(rows[0]["id"], members)  # first slot is within the 4-hour lead
        self.assertIsNone(series_queue.info(self.queue, rows[0]["id"]))

    def test_existing_drafted_standalone_keeps_its_slot(self):
        rows = self.seed()
        self.queue.move(rows[3]["id"], ("queued",), "drafted", story_path="already-saved.json")
        identity = p.assign_series(self.queue, self.config, self.now)
        members = [m["id"] for m in series_queue.members(self.queue, identity)]
        self.assertEqual(members, [row["id"] for row in rows[4:7]])


class ChatPublishingTests(unittest.TestCase):
    def test_chat_metadata_uses_drama_tags_and_part_titles(self):
        story = validate_story(
            chat_story()
            | {
                "series": {
                    "id": "e" * 32,
                    "title": "The Receipt In His Jacket",
                    "part": 1,
                    "total": 3,
                    "ending": "cliffhanger",
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "short.mp4"
            video.with_suffix(".metadata.json").write_text(json.dumps({"story": story}))
            meta = build_short_metadata(video)
        self.assertTrue(meta["title"].startswith("Part 1/3: The Receipt"))
        self.assertIn("textstory", meta["tags"])
        self.assertNotIn("horror", meta["tags"])
        self.assertIn("#textstory", meta["description"])

    def test_current_story_format_checks_the_whole_cast_voice_identity(self):
        story = validate_story(chat_story() | {"story_revision": "chat-v1"})
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tts, "SECRETS_DIR", Path(tmp)),
            patch.dict("os.environ", {}, clear=True),
        ):
            (Path(tmp) / "fish.local.json").write_text(
                json.dumps({"voice_id": "male-ref", "female_voice_id": "female-ref"})
            )
            audio = Path(tmp) / "chat.mp3"
            output = Path(tmp) / "short.mp4"
            output.with_suffix(".metadata.json").write_text(
                json.dumps({"story": story, "narration": str(audio), "tts_provider": "fish"})
            )
            config = {"story_revision": "horror-v2"}
            audio.with_suffix(".json").write_text(
                json.dumps({"voice": "chat:me=female-ref|Jordan=male-ref"})
            )
            self.assertTrue(p.current_story_format({"output": str(output)}, config))
            audio.with_suffix(".json").write_text(json.dumps({"voice": "chat:me=other"}))
            self.assertFalse(p.current_story_format({"output": str(output)}, config))


if __name__ == "__main__":
    unittest.main()
