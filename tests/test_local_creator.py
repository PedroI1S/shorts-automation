import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shorts_automation.footage import creator_footage as f
from shorts_automation.state.usage_store import UsageStore


class LocalCreatorTests(unittest.TestCase):
    def test_production_config_accepts_explicit_local_authorization(self):
        from shorts_automation.automation import production

        config = production.load_config()
        config["background_licenses"].append(f.LOCAL_LICENSE)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(config), encoding="utf8")
            self.assertIn(f.LOCAL_LICENSE, production.load_config(path)["background_licenses"])

    def test_local_source_uses_reserved_disjoint_segments_and_truthful_rights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "creator_sources"
            registry.mkdir()
            original = registry / "source.mp4"
            original.write_bytes(b"original")
            provenance = {
                "title": "Minecraft Parkour",
                "author": "Spawn Point",
                "source_url": "https://www.youtube.com/watch?v=Io2-_UUlUOg",
                "youtube_video_id": "Io2-_UUlUOg",
                "download_landing_url": "https://example.com/file",
                "permission_excerpt": "Use this as background footage for your own storytime videos, edits, or shorts.",
                "monetization_permission": "unspecified; not verified",
                "ffprobe_duration_seconds": 150,
                "download_bytes": 8,
                "sha256": "local hash",
            }
            original.with_suffix(".source.json").write_text(json.dumps(provenance), encoding="utf8")
            store = UsageStore(root / "usage.db")

            def render(command, **kwargs):
                Path(command[-1]).write_bytes(
                    ("segment " + command[command.index("-ss") + 1]).encode()
                )
                return MagicMock(returncode=0)

            with (
                patch.object(f, "BACKGROUNDS_DIR", root),
                patch.object(f, "UsageStore", return_value=store),
                patch.object(f, "get_video_duration", return_value=60),
                patch.object(f.subprocess, "run", side_effect=render),
            ):
                first = f.import_local_creator_clip(original, {f.LOCAL_LICENSE})
                meta = json.loads(first.with_suffix(".source.json").read_text(encoding="utf8"))
                self.assertEqual(meta["monetization_permission"], "unspecified; not verified")
                self.assertEqual(meta["license"], f.LOCAL_LICENSE)
                self.assertTrue(meta["user_authorized_monetized_reels"])
                self.assertFalse(meta["publication_cleared"])
                job = store.begin("one")
                store.reserve_source(job, meta, first)
                second = f.import_local_creator_clip(original, {f.LOCAL_LICENSE})
                meta2 = json.loads(second.with_suffix(".source.json").read_text(encoding="utf8"))
                self.assertEqual((meta["segment_start"], meta2["segment_start"]), (5, 65))
                self.assertFalse(store.source_unavailable(meta2, second))
