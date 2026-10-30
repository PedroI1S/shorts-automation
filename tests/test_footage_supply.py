import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.footage import creator_footage as footage
from shorts_automation.state.usage_store import UsageStore


class FootageSupplyTests(unittest.TestCase):
    def test_exhausted_local_source_falls_back_to_known_creator(self):
        record = {"download_landing_url": "https://example.org/file", "source_duration": 120}
        with (
            patch.object(footage, "cached_creator_clip", return_value=None),
            patch.object(
                footage, "import_local_creator_clip", side_effect=footage.SourceExhausted()
            ),
            patch.object(footage, "known_creator_records", return_value={"other": record}),
            patch.object(footage, "UsageStore") as store,
            patch.object(footage, "import_creator_clip", return_value=Path("backup.mp4")),
        ):
            store.return_value.next_segment_start.return_value = 5
            result = footage.get_creator_background(
                {
                    "background_licenses": [footage.LICENSE],
                    "authorized_local_creator_source": "local.mp4",
                }
            )
        self.assertEqual(result, Path("backup.mp4"))

    def test_low_local_supply_researches_and_imports_one_verified_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "owned.mp4"
            source.write_bytes(b"owned")
            source.with_suffix(".source.json").write_text(
                json.dumps(
                    {
                        "youtube_video_id": "local",
                        "source_url": "https://example.org/local",
                        "ffprobe_duration_seconds": 125,
                    }
                )
            )
            store = UsageStore(root / "usage.db")
            candidate = {"video_url": "https://www.youtube.com/watch?v=other"}
            with (
                patch.object(footage, "BACKGROUNDS_DIR", root),
                patch(
                    "shorts_automation.footage.agy_footage_research.research",
                    return_value=(root / "catalog.json", {"ready": [candidate]}),
                ) as research,
                patch.object(
                    footage, "import_creator_clip", return_value=root / "creator_other.mp4"
                ) as importer,
            ):
                result = footage.replenish_low_supply(
                    {
                        "authorized_local_creator_source": str(source),
                        "background_licenses": [footage.LOCAL_LICENSE, footage.LICENSE],
                        "antigravity_model": "model",
                    },
                    store,
                )
            self.assertEqual(result["remaining_local_segments"], 2)
            self.assertEqual(result["status"], "replenished")
            research.assert_called_once()
            importer.assert_called_once()
            self.assertTrue(source.exists())
