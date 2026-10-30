import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from shorts_automation.publishing.youtube_uploader import build_short_metadata
from shorts_automation.rendering import pipeline
from shorts_automation.state.usage_store import SEGMENT_POLICY, AlreadyUsed, UsageStore


class PipelineUsageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        lock = patch(
            "shorts_automation.state.source_lock.LOCK_PATH", Path(temporary.name) / "source.lock"
        )
        lock.start()
        self.addCleanup(lock.stop)
        imports = patch.object(UsageStore, "import_outputs", return_value=0)
        imports.start()
        self.addCleanup(imports.stop)

    def test_short_narration_reaches_sourcing_without_redrafting(self):
        for duration in (0.5, 10, 40.333, 43.967, 44.199, 44.2):
            with self.subTest(duration=duration), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store = UsageStore(root / "db.sqlite3")
                story = root / "story.json"
                script = "fresh " * 130
                story.write_text(
                    json.dumps({"title": "The Voice Behind The Door", "script": script})
                )
                with (
                    patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                    patch.object(
                        pipeline, "generate_speech", return_value=(root / "audio.mp3", duration, [])
                    ),
                    patch.object(
                        pipeline,
                        "get_background_clip",
                        side_effect=RuntimeError("sourcing reached"),
                    ) as sourcing,
                    patch.object(pipeline, "compile_short") as compile_video,
                    redirect_stdout(io.StringIO()),
                ):
                    with self.assertRaisesRegex(RuntimeError, "sourcing reached"):
                        pipeline.run_pipeline(story_file=story)
                    sourcing.assert_called_once()
                    compile_video.assert_not_called()
                store.begin(script)  # The failed attempt releases its reservation.

    def test_invalid_narration_duration_stops_before_sourcing(self):
        for duration in (0, -1, float("nan"), float("inf")):
            with self.subTest(duration=duration), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store = UsageStore(root / "db.sqlite3")
                story = root / "story.json"
                story.write_text(
                    json.dumps({"title": "The Voice Behind My Door", "script": "A short story."})
                )
                with (
                    patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                    patch.object(
                        pipeline, "generate_speech", return_value=(root / "audio.mp3", duration, [])
                    ),
                    patch.object(pipeline, "get_background_clip") as sourcing,
                    redirect_stdout(io.StringIO()),
                ):
                    with self.assertRaisesRegex(ValueError, "positive and finite"):
                        pipeline.run_pipeline(story_file=story)
                sourcing.assert_not_called()

    def test_short_render_preserves_creator_credit_through_upload_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = UsageStore(root / "db.sqlite3")
            story = root / "story.json"
            story.write_text(
                json.dumps(
                    {
                        "title": "The Voice Behind My Door",
                        "script": "My mother called from downstairs. I buried her yesterday. Then she used the name only she knew.",
                    }
                ),
                encoding="utf-8",
            )
            footage = root / "background.mp4"
            footage.write_bytes(b"fixture")
            credit = "Footage by Creator\nChannel: https://example.org/channel"
            footage.with_suffix(".source.json").write_text(
                json.dumps(
                    {
                        "title": "Minecraft Parkour",
                        "author": "Creator",
                        "source_url": "https://example.org/video",
                        "license": "Creator commercial permission",
                        "license_url": "https://example.org/permission",
                        "credit_required": True,
                        "credit_text": credit,
                    }
                ),
                encoding="utf-8",
            )

            def compile_fixture(**kwargs):
                output = root / kwargs["output_filename"]
                output.write_bytes(b"rendered fixture")
                return output

            with (
                patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                patch.object(pipeline, "OUTPUT_DIR", root),
                patch.object(pipeline, "get_video_duration", return_value=60),
                patch.object(pipeline, "generate_speech", return_value=(root / "audio.mp3", 8, [])),
                patch.object(
                    pipeline, "generate_subtitles_stream", return_value=root / "captions.ffconcat"
                ),
                patch.object(pipeline, "compile_short", side_effect=compile_fixture),
                redirect_stdout(io.StringIO()),
            ):
                output = pipeline.run_pipeline(story_file=story, background_file=footage)
            self.assertIn(credit, output.with_suffix(".credits.txt").read_text(encoding="utf-8"))
            self.assertEqual(build_short_metadata(output)["description"].count(credit), 1)
            with store.connect() as db:
                self.assertEqual(db.execute("SELECT status FROM jobs").fetchone()[0], "rendered")

    def test_overlapping_supplied_segment_stops_before_tts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = UsageStore(root / "usage.sqlite3")
            background = root / "creator.mp4"
            background.write_bytes(b"footage")
            metadata = {
                "youtube_video_id": "abcdefghijk",
                "source_url": "https://youtu.be/abcdefghijk",
                "segment_policy": SEGMENT_POLICY,
                "source_duration": 400,
                "segment_start": 5,
                "segment_duration": 60,
            }
            background.with_suffix(".source.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            other = store.begin("Other story")
            store.reserve_source(other, metadata, background)
            script = "fresh " * 130
            story = root / "story.json"
            story.write_text(
                json.dumps({"title": "The Voice Behind The Door", "script": script}),
                encoding="utf-8",
            )
            with (
                patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                patch.object(pipeline, "get_video_duration", return_value=60),
                patch.object(pipeline, "generate_speech") as speech,
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(AlreadyUsed):
                    pipeline.run_pipeline(story_file=story, background_file=background)
            speech.assert_not_called()
            store.begin(script)  # Failed admission released the new story claim.

    def test_duplicate_story_stops_before_tts(self):
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp) / "db.sqlite3")
            script = "unique " * 130
            store.begin(script)
            story = Path(temp) / "draft.json"
            story.write_text(json.dumps({"title": "The Voice Behind The Door", "script": script}))
            with (
                patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                patch.object(pipeline, "generate_speech") as speech,
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(AlreadyUsed):
                    pipeline.run_pipeline(story_file=story)
                speech.assert_not_called()

    def test_tts_failure_releases_story_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp) / "db.sqlite3")
            script = "another " * 130
            story = Path(temp) / "draft.json"
            story.write_text(json.dumps({"title": "The Voice Behind The Door", "script": script}))
            with (
                patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                patch.object(pipeline, "generate_speech", side_effect=RuntimeError("offline")),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(RuntimeError):
                    pipeline.run_pipeline(story_file=story)
            store.begin(script)  # Retry remains possible after an ordinary failure.
