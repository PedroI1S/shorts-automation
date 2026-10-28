import json
import unittest
from draft_story import parse_result, validate_story


class DraftTests(unittest.TestCase):
    def test_rejects_overlong_and_short_scripts(self):
        for count in (80, 129, 151, 300):
            with self.subTest(count=count), self.assertRaises(ValueError):
                validate_story({"title": "The Voice Behind My Door", "script": "word " * count})

    def test_accepts_boundaries_and_normalizes(self):
        for count in (130, 150):
            story = validate_story({"title": "The Voice Behind My Door", "script": "word\n" * count})
            self.assertEqual(len(story["script"].split()), count)

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
