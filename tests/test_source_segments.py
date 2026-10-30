"""Durable interval reservations and compatibility with whole-source history."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shorts_automation.state.usage_store import SEGMENT_POLICY, AlreadyUsed, UsageStore, source_keys


class SourceSegmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = UsageStore(self.root / "usage.sqlite3")

    def segment(
        self, start=5, video_id="abcdefghijk", landing="https://mediafire.com/file/shared/file"
    ):
        return {
            "youtube_video_id": video_id,
            "source_url": "https://youtu.be/" + video_id,
            "download_landing_url": landing,
            "source_duration": 409.7,
            "segment_policy": SEGMENT_POLICY,
            "segment_start": start,
            "segment_duration": 60,
        }

    def test_adjacent_windows_allowed_overlap_rejected(self):
        first, second, overlap = [self.store.begin(s) for s in ("first", "second", "overlap")]
        self.store.reserve_source(first, self.segment())
        self.store.reserve_source(second, self.segment(65))
        with self.assertRaises(AlreadyUsed):
            self.store.reserve_source(overlap, self.segment(64.999))
        self.assertEqual(self.store.next_segment_start(self.segment(), 409.7), 125)

    def test_failure_frees_interval_completion_survives_restart(self):
        first = self.store.begin("first")
        self.store.reserve_source(first, self.segment())
        self.store.fail(first)
        self.assertEqual(self.store.next_segment_start(self.segment(), 409.7), 5)
        job = self.store.begin("completed")
        self.store.reserve_source(job, self.segment())
        self.store.complete(job, self.root / "completed.mp4")
        self.store.fail(job)
        reopened = UsageStore(self.store.path)
        self.assertTrue(reopened.source_unavailable(self.segment()))
        self.assertEqual(reopened.next_segment_start(self.segment(), 409.7), 65)

    def test_killed_job_holds_interval_until_explicit_release(self):
        job = self.store.begin("interrupted")
        self.store.reserve_source(job, self.segment())
        reopened = UsageStore(self.store.path)
        self.assertEqual(reopened.next_segment_start(self.segment(), 409.7), 65)
        reopened.release_reservation(job)
        self.assertEqual(reopened.next_segment_start(self.segment(), 409.7), 5)

    def test_concurrent_overlapping_claims_have_one_winner(self):
        jobs = [self.store.begin(s) for s in ("one", "two")]

        def claim(job):
            try:
                UsageStore(self.store.path).reserve_source(job, self.segment())
                return True
            except AlreadyUsed:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(claim, jobs)), [False, True])

    def test_legacy_whole_claim_and_segment_claim_block_each_other(self):
        whole = self.segment()
        whole.pop("segment_policy")
        old = self.store.begin("old whole source")
        self.store.reserve_source(old, whole)
        self.assertIsNone(self.store.next_segment_start(self.segment(), 409.7))
        new = self.store.begin("new")
        with self.assertRaises(AlreadyUsed):
            self.store.reserve_source(new, self.segment(65))
        self.store.fail(old)
        self.store.reserve_source(new, self.segment())
        with self.assertRaises(AlreadyUsed):
            self.store.reserve_source(self.store.begin("another whole-source job"), whole)

    def test_mirrored_recording_sharing_download_cannot_overlap(self):
        first, second = self.store.begin("first"), self.store.begin("second")
        self.store.reserve_source(first, self.segment())
        mirror = self.segment(video_id="123456789ab")
        with self.assertRaises(AlreadyUsed):
            self.store.reserve_source(second, mirror)
        self.assertEqual(self.store.next_segment_start(mirror, 409.7), 65)

    def test_history_import_restores_range_reservations(self):
        (self.root / "old.mp4").write_bytes(b"output")
        (self.root / "old.metadata.json").write_text(
            json.dumps({"story": {"script": "old story"}, "background_source": self.segment()}),
            encoding="utf-8",
        )
        self.assertEqual(self.store.import_outputs(self.root), 1)
        self.assertEqual(self.store.import_outputs(self.root), 0)
        self.assertTrue(self.store.source_unavailable(self.segment()))
        self.assertEqual(self.store.next_segment_start(self.segment(), 409.7), 65)

    def test_invalid_and_out_of_bounds_windows_rejected(self):
        for start, duration in ((-1, 60), (400, 60), (5, 0), (float("nan"), 60)):
            metadata = {**self.segment(start), "segment_duration": duration}
            with self.subTest(start=start, duration=duration), self.assertRaises(ValueError):
                source_keys(metadata)

    def test_exhaustion_never_loops_or_reuses_an_interval(self):
        for i in range(6):
            start = self.store.next_segment_start(self.segment(), 409.7)
            self.assertEqual(start, 5 + 60 * i)
            self.store.reserve_source(self.store.begin("story " + str(i)), self.segment(start))
        self.assertIsNone(self.store.next_segment_start(self.segment(), 409.7))


if __name__ == "__main__":
    unittest.main()
