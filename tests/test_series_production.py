import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from shorts_automation.automation import production as p
from shorts_automation.automation import series_queue
from shorts_automation.automation.orchestrator import JobQueue
from shorts_automation.state.usage_store import UsageStore
from tests.series_helpers import SeriesHarness


class SeriesProductionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in (
            ("STORAGE_DIR", self.root),
            ("TEMP_DIR", self.root / "temp"),
            ("OUTPUT_DIR", self.root),
        ):
            self.enterContext(patch.object(p, name, value))
        self.queue = JobQueue(self.root / "queue.sqlite3")
        self.usage = UsageStore(self.queue.path)
        self.usage.import_outputs = lambda: 0
        self.harness = SeriesHarness(self.root)
        self.now = datetime(2099, 1, 1, tzinfo=timezone.utc)
        self.config = p.load_config() | {
            "story_format": "mixed",
            "minimum_scheduled_videos": 3,
            "footage_discovery": "fixed",
            "publish_enabled": True,
            "private_upload_enabled": False,
            "telegram_notify_enabled": False,
            "lookahead_hours": 72,
            "max_jobs_per_pass": 1,
            "series_parts": [3, 4],
            "series_standalones_between": 3,
            "series_min_lead_hours": 4,
        }
        self.enterContext(redirect_stdout(io.StringIO()))

    def seed(self, count=3):
        rows = p.plan(self.queue, self.config, self.now)
        for n, row in enumerate(rows[:count]):
            self.queue.move(
                row["id"],
                ("queued",),
                "scheduled",
                youtube_id=f"buffer{n:05d}",
                scheduled_at=row["publish_at"],
            )
        return rows

    def cycle(self):
        return p.cycle(
            self.config,
            self.queue,
            self.usage,
            self.harness.drafter,
            self.harness.renderer,
            validator=lambda *a: {},
            service_factory=lambda: object(),
            now=self.now,
            health_path=self.root / "health.json",
            lock_path=self.root / "runner.lock",
            series_drafter=self.harness.series_drafter,
        )

    def test_mixed_series_renders_one_part_per_pass_then_schedules_whole_arc_in_order(self):
        self.seed()
        responses = [{"id": f"serial{n:05d}"} for n in range(3)]
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video", side_effect=responses
        ) as upload:
            for n in range(2):
                self.cycle()
                self.assertEqual(len(self.harness.renders), n + 1)
                upload.assert_not_called()
            result = self.cycle()
            self.assertEqual(len(result["published"]), 3)
            self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 6)
            times = [call.kwargs["scheduled_time"] for call in upload.call_args_list]
            self.assertEqual(times, sorted(times))
            self.assertTrue(
                all(
                    f"Part {n}/3" in call.kwargs["title"]
                    for n, call in enumerate(upload.call_args_list, 1)
                )
            )
            self.cycle()
        self.assertEqual(len(self.harness.drafts), 1)
        self.assertEqual(len(self.harness.renders), 3)

    def test_four_part_series_can_finish_without_exceeding_per_pass_generation_budget(self):
        self.config["series_parts"] = [4]
        self.seed()
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            side_effect=[{"id": f"serial{n:05d}"} for n in range(4)],
        ) as upload:
            for n in range(4):
                result = self.cycle()
                self.assertEqual(len(self.harness.renders), n + 1)
            self.assertEqual(upload.call_count, 4)
            self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 7)

    def test_full_reserve_does_not_assign_or_spend_on_series(self):
        self.seed(4)
        result = self.cycle()
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 4)
        self.assertFalse(self.harness.drafts)
        self.assertFalse(self.harness.renders)
        with self.queue.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM story_series").fetchone()[0], 0)

    def test_imminent_release_prioritizes_a_standalone_reserve_replacement(self):
        rows = self.seed()
        self.queue.move(
            rows[0]["id"], ("scheduled",), "scheduled", scheduled_at="2099-01-01T01:00:00Z"
        )
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "extra000001"},
        ):
            result = self.cycle()
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 4)
        self.assertFalse(self.harness.drafts)
        self.assertEqual(len(self.harness.renders), 1)
        self.assertNotIn("series", self.harness.renders[0])

    def test_assignment_is_durable_and_does_not_convert_drafted_standalones(self):
        rows = self.seed()
        self.queue.move(rows[3]["id"], ("queued",), "drafted", story_path="already-saved.json")
        self.assertIsNone(p.assign_series(self.queue, self.config, self.now))
        self.queue.move(rows[3]["id"], ("drafted",), "queued", story_path=None)
        identity = p.assign_series(self.queue, self.config, self.now)
        self.assertEqual(
            p.assign_series(JobQueue(self.queue.path), self.config, self.now), identity
        )
        self.assertEqual(len(series_queue.members(self.queue, identity)), 3)

    def test_manual_gap_prevents_series_from_claiming_nonconsecutive_slots(self):
        rows = self.seed()
        with self.queue.connect() as db:
            db.execute("DELETE FROM production_slots WHERE job_id=?", (rows[4]["id"],))
        self.assertIsNone(p.assign_series(self.queue, self.config, self.now))

    def test_unconfirmed_standalones_do_not_count_toward_spacing(self):
        rows = self.seed()
        self.queue.move(
            rows[2]["id"], ("scheduled",), "rendered", youtube_id=None, scheduled_at=None
        )
        self.config["minimum_scheduled_videos"] = 2
        self.assertIsNone(p.assign_series(self.queue, self.config, self.now))

    def test_uncertain_open_arc_holds_later_standalone_upload(self):
        rows = self.seed()
        series_queue.link(self.queue, [row["id"] for row in rows[3:6]])
        self.queue.move(rows[4]["id"], ("queued",), "upload_uncertain")
        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            self.cycle()
            upload.assert_not_called()
        self.assertEqual(self.queue.get(rows[6]["id"])["stage"], "rendered")

    def test_failed_arc_releases_later_standalones_without_publishing_its_parts(self):
        rows = self.seed()
        identity = series_queue.link(self.queue, [row["id"] for row in rows[3:6]])
        self.queue.move(rows[4]["id"], ("queued",), "failed")
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "standalone1"},
        ) as upload:
            self.cycle()
        upload.assert_called_once()
        self.assertEqual(self.queue.get(rows[6]["id"])["stage"], "scheduled")
        self.assertEqual(
            [row["stage"] for row in series_queue.members(self.queue, identity)],
            ["queued", "failed", "queued"],
        )

    def test_past_unresolved_arc_does_not_stall_later_releases(self):
        rows = self.seed()
        series_queue.link(self.queue, [row["id"] for row in rows[3:6]])
        self.queue.move(rows[4]["id"], ("queued",), "needs_attention")
        self.now = datetime.fromisoformat(rows[5]["publish_at"].replace("Z", "+00:00")) + (
            timedelta(hours=1)
        )
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "standalone1"},
        ) as upload:
            result = self.cycle()
        upload.assert_called_once()
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 1)
        self.assertEqual(self.queue.get(rows[4]["id"])["stage"], "needs_attention")

    def test_upload_failure_stops_continuations_and_keeps_uncertain_outcome(self):
        self.seed()
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            side_effect=[{"id": "serial00001"}, TimeoutError("unknown")],
        ) as upload:
            self.cycle()
            self.cycle()
            result = self.cycle()
            self.assertEqual(upload.call_count, 2)
            series = [
                row for row in p.owned_jobs(self.queue) if series_queue.info(self.queue, row["id"])
            ]
            self.assertEqual(
                [row["stage"] for row in series], ["scheduled", "upload_uncertain", "approved"]
            )
            self.cycle()
            self.assertEqual(upload.call_count, 2)
            self.assertEqual(result["status"], "needs_attention")

    def test_invalid_series_configuration_is_rejected(self):
        for key, value in (
            ("series_parts", [2]),
            ("series_parts", [True]),
            ("series_parts", [3, 3]),
            ("story_format", "unknown"),
            ("series_standalones_between", 0),
        ):
            path = self.root / "invalid.json"
            path.write_text(json.dumps(self.config | {key: value}))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                p.load_config(path)
