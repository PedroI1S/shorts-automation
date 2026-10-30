import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.footage import gameplay_fetcher as g


class SourcingTests(unittest.TestCase):
    def page(self):
        return {
            "pageid": 12,
            "title": "File:Voxel gameplay.webm",
            "imageinfo": [
                {
                    "url": "https://upload.wikimedia.org/test.webm",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:test",
                    "size": 100,
                    "extmetadata": {
                        "Artist": {"value": "<a>Creator</a>"},
                        "LicenseShortName": {"value": "CC BY 4.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                    },
                }
            ],
        }

    def test_license_and_download_host_are_required(self):
        for license in ("", "All rights reserved", "No copyright", "CC BY-NC 4.0"):
            p = self.page()
            p["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = license
            self.assertIsNone(g.candidate_from_page(p, "voxel"))
        p = self.page()
        p["imageinfo"][0]["url"] = "https://example.com/test.mp4"
        self.assertIsNone(g.candidate_from_page(p, "voxel"))

    def test_metadata_preserves_credit_and_review_status(self):
        c = g.candidate_from_page(self.page(), "voxel")
        self.assertEqual(c["author"], "Creator")
        self.assertFalse(c["publication_cleared"])
        self.assertTrue(c["requires_visual_review"])

    def test_oversized_sources_rejected_before_download(self):
        p = self.page()
        p["imageinfo"][0]["size"] = g.MAX_BYTES + 1
        self.assertIsNone(g.candidate_from_page(p, "voxel"))

    def test_matching_cache_avoids_network_and_covers_tail(self):
        with (
            patch.object(g, "cached_clips", return_value=iter([Path("cached.mp4")])),
            patch.object(g, "get_video_duration", return_value=60),
            patch.object(g, "download_gameplay_clip") as download,
        ):
            p, start = g.get_background_clip(56.3, "voxel")
            download.assert_not_called()
            self.assertEqual(p, Path("cached.mp4"))
            self.assertLessEqual(start + 56.3 + 0.8, 60)

    def test_no_search_result_fails_without_unrelated_fallback(self):
        with patch.object(g, "search_candidates", return_value=[]):
            with self.assertRaises(RuntimeError):
                g.download_gameplay_clip("unknown")

    def test_audio_only_or_bad_probe_rejected(self):
        with patch.object(g.subprocess, "run") as probe:
            probe.return_value.stdout = json.dumps({"streams": [], "format": {"duration": "90"}})
            self.assertEqual(g.get_video_duration(Path("audio.mp4")), 0)

    def test_cache_ignores_wrong_query_or_modified_media(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(g, "BACKGROUNDS_DIR", Path(temp)),
            patch.object(g, "UsageStore") as store,
        ):
            store.return_value.unavailable.return_value = False
            p = Path(temp) / "commons_test.mp4"
            p.write_bytes(b"modified")
            p.with_suffix(".source.json").write_text(
                json.dumps({"schema": 1, "query": "voxel", "license": "CC BY 4.0", "sha256": "bad"})
            )
            self.assertEqual(list(g.cached_clips("voxel", 57)), [])
            self.assertEqual(list(g.cached_clips("different", 57)), [])
