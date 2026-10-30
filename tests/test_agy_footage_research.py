import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.footage.agy_footage_research import (
    make_prompt,
    parse_research,
    research,
    validate_against_evidence,
)


class ResearchTests(unittest.TestCase):
    def catalog(self):
        return {
            "reference_assessment": {},
            "ready": [
                {
                    "title": "Minecraft parkour",
                    "creator": "A creator",
                    "video_url": "https://www.youtube.com/watch?v=example1234",
                    "download_landing_url": "https://example.com/download",
                    "direct_file_url": "https://example.com/gameplay.mp4",
                    "permission_url": "https://example.com/terms",
                    "permission_excerpt": "Monetized edited videos allowed with credit.",
                    "commercial_use": "explicitly_allowed",
                    "access_status": "free_direct",
                    "verified_price": "0",
                }
            ],
            "blocked": [],
            "searches_used": [],
            "limitations": [],
        }

    def test_accepts_evidence_catalog_and_rejects_old_query_output(self):
        self.assertEqual(len(parse_research(json.dumps(self.catalog()))["ready"]), 1)
        with self.assertRaises(ValueError):
            parse_research('["Minetest caves", "voxel maze"]')

    def test_paid_unknown_or_unsupported_ready_sources_rejected(self):
        for key, value in [
            ("access_status", "paid"),
            ("verified_price", "5"),
            ("commercial_use", "unknown"),
            ("permission_excerpt", ""),
            ("download_landing_url", "file:///C:/private"),
        ]:
            with self.subTest(key=key):
                data = self.catalog()
                data["ready"][0][key] = value
                with self.assertRaises(ValueError):
                    parse_research(json.dumps(data))

    def test_empty_findings_and_concrete_blockers_remain_honest(self):
        data = self.catalog()
        data["ready"] = []
        data["blocked"] = [
            {
                "access_status": "free_zero_checkout",
                "reason": "Zero-price checkout requires email submission.",
            }
        ]
        self.assertEqual(parse_research(json.dumps(data))["ready"], [])

    def test_duplicate_sources_rejected(self):
        data = self.catalog()
        data["ready"].append(copy.deepcopy(data["ready"][0]))
        with self.assertRaises(ValueError):
            parse_research(json.dumps(data))

    def test_cli_envelope_decoded_and_permission_denial_reported(self):
        wrapped = {"status": "SUCCESS", "response": json.dumps(self.catalog())}
        self.assertEqual(len(parse_research(json.dumps(wrapped))["ready"]), 1)
        with self.assertRaisesRegex(RuntimeError, "RunCommand"):
            parse_research(
                json.dumps(
                    {
                        "status": "SUCCESS",
                        "response": "",
                        "denied_actions": [{"action": "command", "display_name": "RunCommand"}],
                    }
                )
            )

    def test_prompt_resolves_count_and_reference(self):
        prompt = make_prompt(3, "First-person parkour")
        self.assertIn("up to 3 genuinely useful candidates", prompt)
        self.assertIn("https://www.youtube.com/watch?v=u7kdVe8q5zs", prompt)
        self.assertNotIn("{{COUNT}}", prompt)
        self.assertNotIn("{{GUIDANCE}}", prompt)

    def test_complete_brokered_research_saves_verified_catalog(self):
        data = self.catalog()
        ready = data["ready"][0]
        evidence = {
            "searches": ["Minecraft free MediaFire download"],
            "videos": [],
            "download_pages": [
                {
                    "landing_url": ready["download_landing_url"],
                    "linked_from_video": ready["video_url"],
                    "access_status": "free_direct",
                    "direct_file_url": ready["direct_file_url"],
                    "file_probe": {"http_status": 200, "content_type": "video/mp4"},
                }
            ],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "shorts_automation.footage.agy_footage_research.shutil.which", return_value="agy"
            ),
            patch(
                "shorts_automation.footage.agy_footage_research.invoke_json",
                side_effect=[json.dumps({"searches": evidence["searches"]}), json.dumps(data)],
            ) as agy,
            patch(
                "shorts_automation.footage.creator_evidence.collect_evidence", return_value=evidence
            ) as broker,
        ):
            path, result = research(directory=Path(directory))
            self.assertTrue(path.is_file())
            self.assertEqual(result["ready"][0]["file_probe"]["http_status"], 200)
            self.assertFalse(result["ready"][0]["visual_checked"])
            self.assertEqual(agy.call_count, 2)
            broker.assert_called_once_with(evidence["searches"])

    def test_exhausted_recording_cannot_reenter_ready_catalog(self):
        data = self.catalog()
        identity = data["ready"][0]["video_url"].split("v=")[1]
        with self.assertRaisesRegex(ValueError, "already exhausted"):
            validate_against_evidence(
                data, {"excluded_video_ids": [identity], "download_pages": []}
            )


if __name__ == "__main__":
    unittest.main()
