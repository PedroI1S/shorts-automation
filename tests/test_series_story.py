import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.stories import series_story as series
from shorts_automation.stories.draft_story import parse_result, validate_story
from tests.series_helpers import arc, chat_arc


class SeriesStoryTests(unittest.TestCase):
    def test_three_and_four_part_arcs_keep_gender_and_cliffhangers(self):
        for count in (3, 4):
            with self.subTest(count=count):
                normalized = series.validate_series(arc(count), count)
                self.assertEqual(len(normalized["parts"]), count)
                self.assertTrue(
                    all(part["narrator_gender"] == "female" for part in normalized["parts"])
                )
                self.assertEqual(
                    [part["ending"] for part in normalized["parts"]],
                    ["cliffhanger"] * (count - 1) + ["finale"],
                )

    def test_rejects_wrong_count_gender_duplicate_and_empty_scripts(self):
        invalid = []
        data = arc()
        data["parts"].pop()
        invalid.append(data)
        data = arc()
        data["narrator_gender"] = "male"
        invalid.append(data)
        data = arc()
        data["parts"][1]["script"] = data["parts"][0]["script"]
        invalid.append(data)
        data = arc()
        data["parts"][0]["script"] = ""
        invalid.append(data)
        data = arc()
        data["parts"][0]["script"] = "word " * 147
        invalid.append(data)
        data = arc()
        data["parts"][1]["protagonist_gender"] = "male"
        invalid.append(data)
        data = arc()
        data["parts"][-1]["ending"] = "cliffhanger"
        invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                series.validate_series(data, 3)

    def test_series_metadata_survives_each_render_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = series.save_series(arc(), "1" * 32, Path(tmp))
            story = json.loads((path.parent / "part_01.json").read_text())
            normalized = validate_story(story)
            self.assertEqual(
                normalized["series"],
                {
                    "id": "1" * 32,
                    "title": arc()["title"],
                    "part": 1,
                    "total": 3,
                    "ending": "cliffhanger",
                },
            )
            for bad in (True, 0, 4):
                story["series"]["part"] = bad
                with self.assertRaises(ValueError):
                    validate_story(story)

    def test_two_editorial_calls_save_whole_arc_once_and_restart_reuses_it(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                series, "query_hermes", side_effect=[arc(4), arc(4, token="edited")]
            ) as model,
        ):
            path = series.draft_series("a recorded voice", 4, "2" * 32, Path(tmp))
            manifest = series.read_manifest(path, "2" * 32, 4)
            self.assertEqual(len(manifest["parts"]), 4)
            self.assertIn("edited", manifest["parts"][0]["script"])
            self.assertEqual(model.call_count, 2)
            self.assertEqual(series.draft_series("a recorded voice", 4, "2" * 32, Path(tmp)), path)
            self.assertEqual(model.call_count, 2)
            self.assertIn("No tools", model.call_args.args[0])
            self.assertIn("final payoff", model.call_args.args[0])

    def test_editor_cannot_change_narrator_and_incomplete_model_output_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            for response in (arc(3, "male"), {"parts": []}):
                with patch.object(series, "query_hermes", side_effect=[arc(), response]):
                    with self.assertRaises(ValueError):
                        series.draft_series("a recorded voice", 3, "3" * 32, Path(tmp))
            self.assertFalse((Path(tmp) / ("3" * 32)).exists())

    def test_modified_part_cannot_be_admitted_against_the_complete_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = series.save_series(arc(), "4" * 32, Path(tmp))
            part = path.parent / "part_02.json"
            data = json.loads(part.read_text())
            data["script"] = "A different story appears here."
            part.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "differs"):
                series.read_manifest(path)

    def test_generic_hermes_parser_still_rejects_tools_for_series(self):
        event = json.dumps({"type": "result", "exit_code": 0, "text": json.dumps(arc())})
        self.assertEqual(len(parse_result(event, series.validate_series)["parts"]), 3)
        with self.assertRaises(RuntimeError):
            parse_result('{"type":"tool_call"}\n' + event, series.validate_series)

    def test_series_schema_repair_is_bounded_and_preserves_the_validator(self):
        from shorts_automation.stories import draft_story

        def event(data):
            return subprocess.CompletedProcess(
                [],
                0,
                stdout=json.dumps({"type": "result", "exit_code": 0, "text": json.dumps(data)}),
            )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(draft_story.shutil, "which", return_value=sys.executable),
            patch.object(
                draft_story.subprocess, "run", side_effect=[event({}), event(arc())]
            ) as run,
        ):
            result = draft_story.query_hermes("series prompt", validator=series.validate_series)
        self.assertEqual(len(result["parts"]), 3)
        self.assertEqual(run.call_count, 2)


class HorrorUpgradeTests(unittest.TestCase):
    def test_new_drafts_reject_warm_up_openings_and_stock_endings(self):
        from shorts_automation.stories.draft_story import opening_problem

        self.assertIsNone(opening_problem("The baby monitor said my name in my own voice."))
        self.assertIn("Open on", opening_problem("It was a normal night at the motel."))
        self.assertIn("Open on", opening_problem("I still don’t know what I saw."))
        self.assertIn("stock ending", opening_problem("I ran. Then everything went black."))

    def test_cliche_draft_is_not_saved_but_saved_arcs_are_never_rejudged(self):
        cliche = arc()
        cliche["parts"][0]["script"] = "It was a normal night. " + cliche["parts"][0]["script"]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(series, "query_hermes", side_effect=[cliche, cliche]):
                with self.assertRaisesRegex(ValueError, "Part 1"):
                    series.draft_series("a recorded voice", 3, "5" * 32, Path(tmp))
            self.assertFalse((Path(tmp) / ("5" * 32)).exists())
            path = series.save_series(cliche, "6" * 32, Path(tmp), "old premise")
            self.assertEqual(len(series.read_manifest(path, "6" * 32, 3)["parts"]), 3)

    def test_prompt_lists_recent_arcs_of_the_same_format_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = arc(token="old")
            old["title"] = "The Lighthouse Keeper Keeps Counting"
            series.save_series(old, "7" * 32, Path(tmp), "older premise")
            series.save_series(chat_arc(), "8" * 32, Path(tmp), "chat premise")
            with patch.object(
                series, "query_hermes", side_effect=[arc(), arc(token="ed")]
            ) as model:
                series.draft_series("a recorded voice", 3, "9" * 32, Path(tmp))
            prompt = model.call_args_list[0].args[0]
            self.assertIn("The Lighthouse Keeper Keeps Counting", prompt)
            self.assertNotIn("The Receipt In His Jacket", prompt)
            self.assertIn("first two sentences", model.call_args_list[1].args[0])

    def test_horror_premises_carry_one_learnable_threat_rule(self):
        from shorts_automation.automation import production

        premise = production.fresh_topic("2099-01-01T12:00:00Z", set())
        self.assertIn("The threat follows one rule:", premise)
        self.assertTrue(any(rule in premise for rule in production.THREAT_RULES))
        self.assertEqual(premise, production.fresh_topic("2099-01-01T12:00:00Z", set()))
