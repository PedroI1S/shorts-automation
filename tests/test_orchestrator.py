import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from shorts_automation.automation import orchestrator
from shorts_automation.automation.orchestrator import (
    MAX_ATTEMPTS,
    JobQueue,
    RunnerBusy,
    runner_lock,
)
from shorts_automation.rendering.pipeline import NarrationTooLong
from shorts_automation.state.usage_store import UsageStore
from tests.helpers import Harness


class QueueTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.queue = JobQueue(self.root / "db.sqlite3")
        self.usage = UsageStore(self.root / "db.sqlite3")
        self.usage.import_outputs = lambda *a, **k: 0  # Don't scan the real output folder.
        self.h = Harness(self.root)

    def run_once(self, max_jobs=1):
        with redirect_stdout(io.StringIO()):
            return orchestrator.run(
                max_jobs,
                self.queue,
                self.usage,
                self.h.drafter,
                self.h.renderer,
                lock_path=self.root / "runner.lock",
            )


class OrchestratorTests(QueueTestCase):
    def test_happy_path_stops_at_review_and_is_idempotent(self):
        job = self.queue.enqueue(
            "a lighthouse keeper hears knocking", "kokoro", "Labyrinth Minetest"
        )
        _, processed = self.run_once()
        row = self.queue.get(job)
        self.assertEqual(row["stage"], "rendered")
        self.assertEqual(row["render_job"], "render-123")
        self.assertTrue(Path(row["output"]).is_file())
        self.assertEqual(self.h.renders[0][1]["tts_provider"], "kokoro")
        self.assertEqual(self.h.renders[0][1]["gameplay_query"], "Labyrinth Minetest")
        self.assertEqual(self.run_once()[1], [])  # Nothing left: no duplicate draft or render.
        self.assertEqual((len(self.h.drafts), len(self.h.renders)), (1, 1))

    def test_max_jobs_limits_work_per_run_in_fifo_order(self):
        first, second = self.queue.enqueue("first premise"), self.queue.enqueue("second premise")
        self.run_once(max_jobs=1)
        self.assertEqual(self.queue.get(first)["stage"], "rendered")
        self.assertEqual(self.queue.get(second)["stage"], "queued")

    def test_draft_failures_retry_then_fail_without_rendering(self):
        job = self.queue.enqueue("premise")
        self.h.draft_error = RuntimeError("Hermes offline")
        for _ in range(MAX_ATTEMPTS):
            self.run_once()
        row = self.queue.get(job)
        self.assertEqual((row["stage"], row["attempts"]), ("failed", MAX_ATTEMPTS))
        self.assertIn("Hermes offline", row["error"])
        self.assertEqual(self.h.renders, [])
        self.run_once()
        self.assertEqual(len(self.h.drafts), MAX_ATTEMPTS)  # Failed jobs are not picked up again.

    def test_out_of_range_draft_is_not_advanced(self):
        job = self.queue.enqueue("premise")
        self.h.words = 160
        self.run_once()
        self.assertEqual(self.queue.get(job)["stage"], "queued")
        self.assertEqual(self.h.renders, [])

    def test_batch_does_not_spend_retry_budget_on_same_job_in_one_run(self):
        first = self.queue.enqueue("first")
        second = self.queue.enqueue("second")
        self.h.draft_error = ConnectionError("Hermes offline")
        _, processed = self.run_once(max_jobs=3)
        self.assertEqual([row["id"] for row in processed], [first, second])
        self.assertEqual(self.h.drafts, ["first", "second"])
        self.assertEqual(self.queue.get(first)["attempts"], 1)
        self.assertEqual(self.queue.get(second)["attempts"], 1)

    def test_too_long_narration_redrafts(self):
        job = self.queue.enqueue("premise")
        self.h.render_error = NarrationTooLong("too long")
        self.run_once()
        row = self.queue.get(job)
        self.assertEqual((row["stage"], row["attempts"], row["story_path"]), ("queued", 1, None))
        self.h.render_error = None
        self.run_once()
        self.assertEqual(self.queue.get(job)["stage"], "rendered")
        self.assertEqual(len(self.h.drafts), 2)

    def test_short_story_renders_without_a_minimum_word_count(self):
        job = self.queue.enqueue("premise")
        self.h.words = 30
        self.run_once()
        row = self.queue.get(job)
        self.assertEqual((row["stage"], row["attempts"]), ("rendered", 0))
        self.assertEqual(len(self.h.drafts), 1)

    def test_transient_render_failure_keeps_story(self):
        job = self.queue.enqueue("premise")
        self.h.render_error = ConnectionError("Commons timeout")
        self.run_once()
        row = self.queue.get(job)
        self.assertEqual(row["stage"], "drafted")
        story = row["story_path"]
        self.h.render_error = None
        self.run_once()
        self.assertEqual(self.queue.get(job)["stage"], "rendered")
        self.assertEqual(len(self.h.drafts), 1)
        self.assertEqual(self.h.renders[-1][0], Path(story))

    def test_duplicate_story_redrafts_before_render(self):
        job = self.queue.enqueue("premise")
        original = self.h.drafter

        def duplicate(topic):
            path = original(topic)
            self.usage.begin(json.loads(path.read_text())["script"])  # Someone already used it.
            return path

        self.h.drafter = duplicate
        self.run_once()
        self.assertEqual(self.queue.get(job)["stage"], "queued")
        self.assertEqual(self.h.renders, [])

    def test_review_only_from_rendered(self):
        job = self.queue.enqueue("premise")
        with self.assertRaises(ValueError):
            self.queue.review(job, "approved")
        self.run_once()
        self.assertEqual(self.queue.review(job[:6], "approved", "great hook")["stage"], "approved")
        with self.assertRaises(ValueError):
            self.queue.review(job, "rejected")

    def test_concurrent_runner_is_refused(self):
        with runner_lock(self.root / "runner.lock"):
            with self.assertRaises(RunnerBusy):
                self.run_once()
        self.run_once()  # Lock is released afterwards.

    def test_enqueue_validation(self):
        for bad in (
            {"topic": " "},
            {"topic": "x" * 1001},
            {"topic": "ok", "tts_provider": "mystery"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.queue.enqueue(**bad)


class RecoveryTests(QueueTestCase):
    def interrupted_render(self):
        """Simulate a runner killed mid-render: job left in 'rendering'."""
        job = self.queue.enqueue("premise")
        story = self.h.drafter("premise")
        self.queue.move(job, ("queued",), "rendering", story_path=str(story))
        return job, json.loads(story.read_text())["script"]

    def test_interrupted_draft_is_requeued(self):
        job = self.queue.enqueue("premise")
        self.queue.move(job, ("queued",), "drafting")
        recovered, _ = self.run_once()
        self.assertEqual(recovered[0]["stage"], "queued")
        self.assertEqual(self.queue.get(job)["stage"], "rendered")  # Then processed normally.

    def test_interrupted_render_without_reservation_retries(self):
        job, _ = self.interrupted_render()
        recovered, _ = self.run_once()
        self.assertEqual(recovered[0]["stage"], "drafted")
        self.assertEqual(self.queue.get(job)["stage"], "rendered")

    def test_interrupted_render_holding_reservation_needs_attention(self):
        job, script = self.interrupted_render()
        render = self.usage.begin(script)
        recovered, processed = self.run_once()
        row = self.queue.get(job)
        self.assertEqual(row["stage"], "needs_attention")
        self.assertIn(f"--release-reservation {render}", row["error"])
        self.assertEqual(self.h.renders, [])
        with self.assertRaisesRegex(ValueError, "still holds"):
            self.queue.retry(job, self.usage)
        self.usage.release_reservation(render)
        self.assertEqual(self.queue.retry(job[:8], self.usage)["stage"], "drafted")

    def test_render_finished_before_crash_is_reconciled(self):
        job, script = self.interrupted_render()
        render = self.usage.begin(script)
        output = self.root / "done.mp4"
        output.write_bytes(b"video")
        self.usage.complete(render, output)
        recovered, _ = self.run_once()
        row = self.queue.get(job)
        self.assertEqual((row["stage"], row["render_job"]), ("rendered", render))
        self.assertEqual(self.h.renders, [])

    def test_manual_retry_resets_budget(self):
        job = self.queue.enqueue("premise")
        self.h.draft_error = RuntimeError("down")
        for _ in range(MAX_ATTEMPTS):
            self.run_once()
        self.assertEqual(self.queue.retry(job, self.usage)["attempts"], 0)
        self.h.draft_error = None
        self.run_once()
        self.assertEqual(self.queue.get(job)["stage"], "rendered")


if __name__ == "__main__":
    unittest.main()
