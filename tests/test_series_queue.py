import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from shorts_automation.automation import orchestrator, series_queue
from shorts_automation.automation.orchestrator import JobQueue, process_one
from shorts_automation.rendering.pipeline import NarrationTooLong
from shorts_automation.state.usage_store import UsageStore
from tests.series_helpers import SeriesHarness, queued_series, render_series


class SeriesQueueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.queue = JobQueue(self.root / "usage.sqlite3")
        self.usage = UsageStore(self.queue.path)
        self.harness = SeriesHarness(self.root)
        self.enterContext(redirect_stdout(io.StringIO()))

    def process(self, job):
        return process_one(
            self.queue,
            self.usage,
            self.harness.drafter,
            self.harness.renderer,
            include=[job],
            series_drafter=self.harness.series_drafter,
        )

    def approve_all(self, jobs):
        for job in jobs:
            self.queue.review(job, "approved", "reviewed whole arc")

    def test_first_draft_admits_all_parts_and_restart_does_not_draft_again(self):
        identity, jobs = queued_series(self.queue, 4)
        self.process(jobs[0])
        self.assertEqual(
            [row["stage"] for row in series_queue.members(self.queue, identity)],
            ["rendered", "drafted", "drafted", "drafted"],
        )
        self.queue = JobQueue(self.queue.path)
        self.process(jobs[1])
        self.assertEqual(len(self.harness.drafts), 1)
        self.assertEqual(len(self.harness.renders), 2)

    def test_never_uploads_part_one_while_any_continuation_is_unrendered(self):
        _, jobs = queued_series(self.queue)
        self.process(jobs[0])
        self.queue.review(jobs[0], "approved")
        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            with self.assertRaisesRegex(ValueError, "entire series"):
                self.queue.schedule_job(jobs[0], object(), publish_at="2099-01-01T12:00:00Z")
        upload.assert_not_called()
        self.assertEqual(self.queue.get(jobs[0])["stage"], "approved")

    def test_cannot_skip_earlier_part_or_reverse_publish_times(self):
        _, jobs = render_series(self.queue, self.usage, self.harness)
        self.approve_all(jobs)
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "serial00001"},
        ) as upload:
            with self.assertRaisesRegex(ValueError, "earlier parts"):
                self.queue.schedule_job(jobs[1], object(), publish_at="2099-01-01T12:00:00Z")
            upload.assert_not_called()
            self.queue.schedule_job(jobs[0], object(), publish_at="2099-01-01T17:00:00Z")
            with self.assertRaisesRegex(ValueError, "story order"):
                self.queue.schedule_job(jobs[1], object(), publish_at="2099-01-01T12:00:00Z")
            self.assertEqual(upload.call_count, 1)

    def test_uncertain_middle_upload_blocks_later_parts_without_reuploading_first(self):
        _, jobs = render_series(self.queue, self.usage, self.harness)
        self.approve_all(jobs)
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            side_effect=[{"id": "serial00001"}, TimeoutError("lost response")],
        ) as upload:
            self.queue.schedule_job(jobs[0], object(), publish_at="2099-01-01T12:00:00Z")
            with self.assertRaises(TimeoutError):
                self.queue.schedule_job(jobs[1], object(), publish_at="2099-01-01T17:00:00Z")
            self.assertEqual(self.queue.get(jobs[1])["stage"], "upload_uncertain")
            with self.assertRaises(ValueError):
                self.queue.schedule_job(jobs[2], object(), publish_at="2099-01-02T00:00:00Z")
            with self.assertRaises(ValueError):
                self.queue.schedule_job(jobs[0], object(), publish_at="2099-01-03T12:00:00Z")
            self.assertEqual(upload.call_count, 2)

    def test_changed_voice_blocks_complete_arc_before_upload(self):
        identity, jobs = render_series(self.queue, self.usage, self.harness)
        self.approve_all(jobs)
        output = Path(self.queue.get(jobs[-1])["output"])
        metadata = json.loads(output.with_suffix(".metadata.json").read_text())
        Path(metadata["narration"]).with_suffix(".json").write_text('{"voice":"different-voice"}')
        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            with self.assertRaisesRegex(ValueError, "same voice"):
                self.queue.schedule_job(jobs[0], object(), publish_at="2099-01-01T12:00:00Z")
        upload.assert_not_called()
        self.assertEqual(len(series_queue.members(self.queue, identity)), 3)

    def test_overlong_episode_requires_attention_without_independent_redrafting(self):
        _, jobs = queued_series(self.queue)
        self.process(jobs[0])
        self.harness.fail_part, self.harness.render_error = 2, NarrationTooLong("too long")
        result = self.process(jobs[1])
        self.assertEqual(result["stage"], "needs_attention")
        self.assertIsNotNone(result["story_path"])
        self.assertEqual(len(self.harness.drafts), 1)
        self.assertFalse(series_queue.can_process(self.queue, jobs[2]))
        rendered_before = len(self.harness.renders)
        self.assertIsNone(self.process(jobs[2]))
        self.assertEqual(len(self.harness.renders), rendered_before)

    def test_ordinary_source_failure_keeps_the_complete_draft_for_retry(self):
        _, jobs = queued_series(self.queue)
        self.process(jobs[0])
        self.harness.fail_part, self.harness.render_error = 2, RuntimeError("source unavailable")
        result = self.process(jobs[1])
        self.assertEqual(result["stage"], "drafted")
        self.harness.render_error = None
        self.assertEqual(self.process(jobs[1])["stage"], "rendered")
        self.assertEqual(len(self.harness.drafts), 1)

    def test_bulk_series_dry_run_keeps_database_and_upload_state_unchanged(self):
        _, jobs = render_series(self.queue, self.usage, self.harness)
        self.approve_all(jobs)
        before = [dict(self.queue.get(job)) for job in jobs]
        with (
            patch.object(orchestrator, "JobQueue", return_value=self.queue),
            patch(
                "shorts_automation.publishing.youtube_uploader.get_authenticated_service"
            ) as auth,
            patch(
                "shorts_automation.publishing.youtube_uploader.upload_video",
                return_value={"dry_run": True},
            ) as upload,
        ):
            self.assertEqual(orchestrator.main(["schedule-approved", "--dry-run"]), 0)
        auth.assert_not_called()
        self.assertEqual(upload.call_count, 3)
        self.assertEqual([dict(self.queue.get(job)) for job in jobs], before)
        self.assertTrue(all(call.kwargs["dry_run"] for call in upload.call_args_list))

    def test_status_and_details_identify_the_series_parts(self):
        _, jobs = queued_series(self.queue)
        output = io.StringIO()
        with (
            patch.object(orchestrator, "JobQueue", return_value=self.queue),
            redirect_stdout(output),
        ):
            orchestrator.main(["status"])
            orchestrator.main(["show", jobs[1]])
        self.assertIn("Part 1/3", output.getvalue())
        self.assertIn("Part 2/3", output.getvalue())
        self.assertIn("series_manifest", output.getvalue())
