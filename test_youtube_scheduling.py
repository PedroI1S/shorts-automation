import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import orchestrator
from orchestrator import JobQueue
from youtube_uploader import build_short_metadata, get_next_publishing_slot, upload_video


class YouTubeSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_get_next_publishing_slot_is_future_and_utc(self):
        # Anchor at 10:00 local time
        fixed_local = datetime.datetime(2026, 10, 29, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        slot = get_next_publishing_slot(slots=[(9, 0), (14, 0), (19, 0)], from_time=fixed_local)
        # Next slot should be 14:00 local on the same day -> 17:00 UTC
        self.assertEqual(slot["utc_iso"], "2026-10-29T17:00:00Z")
        self.assertTrue(slot["utc_iso"].endswith("Z"))

    def test_get_next_publishing_slot_skips_booked(self):
        fixed_local = datetime.datetime(2026, 10, 29, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        booked = {"2026-10-29T17:00:00Z"}  # 14:00 local already booked
        slot = get_next_publishing_slot(existing_scheduled=booked, slots=[(9, 0), (14, 0), (19, 0)], from_time=fixed_local)
        # Should pick 19:00 local -> 22:00 UTC
        self.assertEqual(slot["utc_iso"], "2026-10-29T22:00:00Z")

    def test_get_next_publishing_slot_rolls_over_to_next_day(self):
        fixed_local = datetime.datetime(2026, 10, 29, 21, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        slot = get_next_publishing_slot(slots=[(9, 0), (14, 0), (19, 0)], from_time=fixed_local)
        # Past 19:00, so rolls over to 09:00 next day -> 12:00 UTC
        self.assertEqual(slot["utc_iso"], "2026-10-30T12:00:00Z")

    def test_build_short_metadata_extracts_sidecars(self):
        video = self.root / "test_video.mp4"
        video.write_bytes(b"dummy")
        video.with_suffix(".metadata.json").write_text(
            json.dumps({"story": {"title": "The Whispering Walls", "script": "I heard footsteps inside the plaster."}}),
            encoding="utf-8",
        )
        video.with_suffix(".credits.txt").write_text("Source: Minetest CC-BY 4.0\nAuthor: John Doe", encoding="utf-8")

        meta = build_short_metadata(video)
        self.assertEqual(meta["title"], "The Whispering Walls #shorts #story")
        self.assertIn("footsteps inside the plaster", meta["description"])
        self.assertIn("John Doe", meta["description"])
        self.assertIn("shorts", meta["tags"])

    def test_upload_video_dry_run_does_not_call_api(self):
        video = self.root / "test.mp4"
        video.write_bytes(b"dummy")
        with redirect_stdout(io.StringIO()):
            res = upload_video(
                youtube=None,
                file_path=str(video),
                title="Test Title",
                description="Test Desc",
                scheduled_time="2026-10-29T12:00:00Z",
                dry_run=True,
            )
        self.assertEqual(res["id"], "DRY_RUN_ID")
        self.assertTrue(res["dry_run"])

    def test_orchestrator_schedule_enforces_stage_and_prevents_duplicate(self):
        queue = JobQueue(self.root / "db.sqlite3")
        job = queue.enqueue("Horror story premise")

        # 1. Cannot schedule a queued job
        with self.assertRaisesRegex(ValueError, "must be in stage 'approved' or 'rendered'"):
            queue.schedule_job(job, dry_run=True)

        # 2. Advance to approved
        video = self.root / "short.mp4"
        video.write_bytes(b"video bytes")
        video.with_suffix(".metadata.json").write_text(json.dumps({"story": {"title": "Ghost", "script": "Scary text."}}))
        queue.move(job, ("queued",), "rendered", output=str(video))
        queue.review(job, "approved")

        # 3. Schedule in dry-run mode
        with redirect_stdout(io.StringIO()):
            scheduled_row = queue.schedule_job(job, dry_run=True, publish_at="2026-10-30T15:00:00Z")

        self.assertEqual(scheduled_row["stage"], "scheduled")
        self.assertEqual(scheduled_row["youtube_id"], "DRY_RUN_ID")
        self.assertEqual(scheduled_row["scheduled_at"], "2026-10-30T15:00:00Z")

        # 4. Idempotency: cannot schedule an already scheduled/uploaded job!
        with self.assertRaisesRegex(ValueError, "already uploaded to YouTube"):
            queue.schedule_job(job, dry_run=True)


if __name__ == "__main__":
    unittest.main()
