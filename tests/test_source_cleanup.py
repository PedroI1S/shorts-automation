import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.footage import source_cleanup
from shorts_automation.footage.source_cleanup import cleanup_exhausted_segments
from shorts_automation.state.source_lock import source_lock
from shorts_automation.state.usage_store import SEGMENT_POLICY, UsageStore


class SourceCleanupTests(unittest.TestCase):
    def test_lock_is_reentrant_and_excludes_other_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            code = (
                "import sys; from shorts_automation.state.source_lock import source_lock\n"
                'with source_lock(sys.argv[1], blocking=False): print("acquired")'
            )
            with source_lock(path):
                with source_lock(path):
                    result = subprocess.run(
                        [sys.executable, "-c", code, str(path)], capture_output=True, check=False
                    )
                    self.assertNotEqual(result.returncode, 0)
            result = subprocess.run(
                [sys.executable, "-c", code, str(path)], capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonblocking_lock_does_not_wait_for_other_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            result = []

            def contender():
                try:
                    with source_lock(path, blocking=False):
                        result.append("acquired")
                except OSError:
                    result.append("busy")

            with source_lock(path):
                thread = threading.Thread(target=contender)
                thread.start()
                thread.join(0.5)
                completed = not thread.is_alive()
            thread.join(2)
            self.assertTrue(completed)
            self.assertEqual(result, ["busy"])

    def test_rejects_caller_supplied_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = UsageStore(root / "usage.sqlite3")
            with patch.object(source_cleanup, "BACKGROUNDS_DIR", root / "managed", create=True):
                with self.assertRaises(ValueError):
                    cleanup_exhausted_segments(root, store)

    def test_only_completed_matching_managed_segment_is_removed_and_provenance_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = UsageStore(root / "usage.sqlite3")
            patcher = patch.object(source_cleanup, "BACKGROUNDS_DIR", root)
            patcher.start()
            self.addCleanup(patcher.stop)
            video = root / "creator_abc_000005000_000065000.mp4"
            video.write_bytes(b"video")
            metadata = {
                "youtube_video_id": "abc",
                "segment_policy": SEGMENT_POLICY,
                "segment_start": 5,
                "segment_duration": 60,
                "source_duration": 65,
                "sha256": hashlib.sha256(b"video").hexdigest(),
            }
            sidecar = video.with_suffix(".source.json")
            sidecar.write_text(json.dumps(metadata))
            job = store.begin("story")
            store.reserve_source(job, metadata, video)
            self.assertEqual(cleanup_exhausted_segments(root, store), 0)
            self.assertTrue(video.exists())
            store.complete(job, root / "output.mp4")
            second = store.begin("other story")
            metadata["original_sha256"] = "other"
            sidecar.write_text(json.dumps(metadata))
            with store.connect() as db:
                db.execute("INSERT INTO claims VALUES (?,?)", ("sha256:other", second))
            self.assertEqual(cleanup_exhausted_segments(root, store), 0)
            self.assertTrue(video.exists())
            store.fail(second)
            self.assertEqual(cleanup_exhausted_segments(root, store), 1)
            self.assertFalse(video.exists())
            self.assertTrue(sidecar.exists())
            self.assertTrue(store.source_unavailable(metadata))
