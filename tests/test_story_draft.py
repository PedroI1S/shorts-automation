import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.stories import draft_story
from shorts_automation.stories.draft_story import parse_result, validate_story


class DraftTests(unittest.TestCase):
    def test_legacy_manual_generator_accepts_short_complete_stories(self):
        from legacy import content_hunter

        story = {"title": "The Voice Behind My Door", "script": "A short complete horror story."}
        with (
            patch.object(content_hunter, "call_ollama", return_value=json.dumps(story)),
            patch.object(content_hunter, "call_gemini") as fallback,
            patch.object(content_hunter, "fallback_viral_story") as template,
        ):
            self.assertEqual(content_hunter.generate_story(topic="a familiar voice"), story)
        fallback.assert_not_called()
        template.assert_not_called()

    def test_structural_repair_is_bounded_and_does_not_retry_tools(self):
        invalid = json.dumps(
            {
                "type": "result",
                "exit_code": 0,
                "text": json.dumps({"title": "Too Short", "script": "word " * 130}),
            }
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(draft_story.shutil, "which", return_value=sys.executable),
            patch.object(
                draft_story.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout=invalid),
            ) as run,
        ):
            with self.assertRaises(ValueError):
                draft_story.query_hermes("test")
            self.assertEqual(run.call_count, 2)
            run.reset_mock()
            run.return_value = subprocess.CompletedProcess([], 0, stdout='{"type":"tool_call"}')
            with self.assertRaises(RuntimeError):
                draft_story.query_hermes("test")
            self.assertEqual(run.call_count, 1)

    def test_rejects_overlong_and_empty_scripts(self):
        for count in (0, 147, 150, 300):
            with self.subTest(count=count), self.assertRaises(ValueError):
                validate_story({"title": "The Voice Behind My Door", "script": "word " * count})

    def test_accepts_boundaries_and_normalizes(self):
        for count in (1, 30, 80, 119, 120, 146):
            story = validate_story(
                {"title": "The Voice Behind My Door", "script": "word\n" * count}
            )
            self.assertEqual(len(story["script"].split()), count)

    def test_short_draft_prompt_prioritizes_quality_without_padding(self):
        story = {
            "title": "The Voice Behind My Door",
            "script": "A short complete horror story.",
            "protagonist_gender": "female",
            "narrator_gender": "female",
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(draft_story, "STORAGE_DIR", Path(tmp)),
            patch.object(draft_story, "query_hermes", return_value=story) as query,
        ):
            path = draft_story.draft("a familiar voice")
            self.assertEqual(json.loads(path.read_text())["script"], story["script"])
        for call in query.call_args_list:
            self.assertIn("no minimum length", call.args[0])
            self.assertIn("never pad", call.args[0])

    def test_rejects_tools_and_failed_results(self):
        for event in ({"type": "tool_call"}, {"type": "result", "exit_code": 1}):
            with self.assertRaises(RuntimeError):
                parse_result(json.dumps(event))

    def test_requires_single_structured_result(self):
        story = {"title": "The Voice Behind My Door", "script": "word " * 140}
        event = json.dumps({"type": "result", "exit_code": 0, "text": json.dumps(story)})
        self.assertEqual(parse_result(event)["title"], story["title"])
        with self.assertRaises(RuntimeError):
            parse_result(event + "\n" + event)

    def test_voice_metadata_survives_validation(self):
        data = {
            "title": "The Voice Behind My Door",
            "script": "word " * 130,
            "protagonist_gender": "female",
            "narrator_gender": "female",
        }
        self.assertEqual(validate_story(data)["protagonist_gender"], "female")
        data["narrator_gender"] = "guess"
        with self.assertRaises(ValueError):
            validate_story(data)

    def test_final_editor_runs_before_saving_gendered_draft(self):
        candidate = {
            "title": "The Voice Behind My Door",
            "script": "draft " * 130,
            "protagonist_gender": "female",
            "narrator_gender": "female",
        }
        final = {**candidate, "script": "edited " * 130}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(draft_story, "STORAGE_DIR", Path(tmp)),
            patch.object(draft_story, "query_hermes", side_effect=[candidate, final]) as query,
        ):
            saved = json.loads(
                draft_story.draft("a mother hears her own voice outside").read_text()
            )
            self.assertEqual(query.call_count, 2)
            self.assertEqual(saved["script"], final["script"])
            self.assertEqual(saved["story_revision"], "horror-v2")
            self.assertEqual(saved["protagonist_gender"], "female")

    def test_new_drafts_cannot_silently_drop_voice_metadata(self):
        legacy = {"title": "The Voice Behind My Door", "script": "word " * 130}
        with patch.object(draft_story, "query_hermes", return_value=legacy):
            with self.assertRaisesRegex(ValueError, "must declare"):
                draft_story.draft("a night shift")
