import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from shorts_automation.automation import production as p
from shorts_automation.automation.orchestrator import JobQueue, RunnerBusy, runner_lock
from shorts_automation.state.usage_store import UsageStore
from tests.helpers import Harness


class ProductionTests(unittest.TestCase):
    def test_fixture_disables_notifications_and_injects_sender(self):
        self.assertFalse(self.config["telegram_notify_enabled"])
        self.config["telegram_notify_enabled"] = True
        with (
            patch(
                "shorts_automation.publishing.youtube_uploader.upload_video",
                return_value={"id": "abcdefghijk"},
            ),
            patch(
                "shorts_automation.publishing.telegram_notifier.send_telegram",
                side_effect=AssertionError("real sender reached"),
            ) as sender,
        ):
            result = self.cycle()
        sender.assert_not_called()
        self.assertEqual(len(result["notified"]), 1)
        self.assertEqual(len(self.notifications), 1)

    def test_supply_failure_is_reported_without_stopping_production(self):
        self.config.update(
            footage_discovery="creator_downloads",
            authorized_local_creator_source="fixture.mp4",
            publish_enabled=False,
        )
        with patch(
            "shorts_automation.footage.creator_footage.replenish_low_supply",
            side_effect=RuntimeError("offline"),
        ) as replenish:
            result = self.cycle()
        replenish.assert_called_once()
        self.assertEqual(result["status"], "needs_attention")
        self.assertTrue(any("footage replenishment" in problem for problem in result["problems"]))

    def test_private_mode_waits_for_slot_never_sets_publish_at_and_notifies_once(self):
        self.config.update(
            publish_enabled=False, private_upload_enabled=True, telegram_notify_enabled=True
        )
        messages = []
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "abcdefghijk"},
        ) as upload:
            self.cycle(notification_sender=messages.append)
            first = p.owned_jobs(self.queue)[0]
            self.assertEqual(first["stage"], "approved")
            upload.assert_not_called()
            due = datetime.fromisoformat(first["publish_at"].replace("Z", "+00:00"))
            result = self.cycle(now=due, notification_sender=messages.append)
            self.assertEqual(self.queue.get(first["id"])["stage"], "uploaded_private")
            self.assertIsNone(upload.call_args.kwargs["scheduled_time"])
            self.assertEqual(len(messages), 1)
            self.assertIn("Uploaded privately", messages[0])
            self.assertEqual(result["notified"], [first["id"][:8]])
            self.cycle(now=due + timedelta(minutes=30), notification_sender=messages.append)
            self.assertEqual(upload.call_count, 1)
            self.assertEqual(len(messages), 1)

    def test_mutually_exclusive_upload_modes(self):
        invalid = self.config | {"publish_enabled": True, "private_upload_enabled": True}
        path = self.root / "invalid.json"
        path.write_text(json.dumps(invalid))
        with self.assertRaisesRegex(ValueError, "never both"):
            p.load_config(path)

    def test_only_the_local_kokoro_voice_provider_is_accepted(self):
        for provider in ("fish", "elevenlabs", "edge"):
            with self.subTest(provider=provider):
                path = self.root / "provider.json"
                path.write_text(json.dumps(self.config | {"tts_provider": provider}))
                with self.assertRaisesRegex(ValueError, "kokoro"):
                    p.load_config(path)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        # Every filesystem effect, including housekeeping with a simulated
        # future clock, belongs to this test's temporary workspace.
        for name, value in (
            ("TEMP_DIR", self.root / "temp"),
            ("STORAGE_DIR", self.root),
            ("OUTPUT_DIR", self.root),
        ):
            patcher = patch.object(p, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.queue = JobQueue(self.root / "db.sqlite3")
        self.usage = UsageStore(self.queue.path)
        self.usage.import_outputs = lambda: 0
        self.harness = Harness(self.root)
        self.config = p.load_config()
        self.config.update(
            story_format="standalone",
            publish_enabled=True,
            private_upload_enabled=False,
            telegram_notify_enabled=False,
            minimum_scheduled_videos=0,  # Existing transition tests isolate the reserve policy.
            lookahead_hours=36,
            max_jobs_per_pass=1,
            footage_discovery="fixed",
        )
        cache_patch = patch(
            "shorts_automation.automation.production.cached_background", return_value=None
        )
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.now = datetime(2099, 1, 15, 10, tzinfo=timezone.utc)
        self.health = self.root / "health.json"
        self.notifications = []

    def cycle(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return p.cycle(
                self.config,
                self.queue,
                self.usage,
                self.harness.drafter,
                self.harness.renderer,
                kwargs.pop("validator", lambda *a: {}),
                service_factory=kwargs.pop("service_factory", lambda: object()),
                now=kwargs.pop("now", self.now),
                lock_path=self.root / "worker.lock",
                health_path=self.health,
                notification_sender=kwargs.pop("notification_sender", self.notifications.append),
                **kwargs,
            )

    def test_automatic_happy_path_and_restart_do_not_duplicate_slots(self):
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "abcdefghijk"},
        ) as upload:
            result = self.cycle()
            count = len(p.owned_jobs(self.queue))
            self.assertEqual(len(result["published"]), 1)
            first = p.owned_jobs(self.queue)[0]
            self.assertEqual(first["stage"], "scheduled")
            self.assertEqual(first["scheduled_at"], first["publish_at"])
            # A second worker invocation advances the next distinct job.
            self.cycle()
            self.assertEqual(len(p.owned_jobs(self.queue)), count)
            self.assertEqual(upload.call_count, 2)
            self.assertEqual(len(set(c.kwargs["scheduled_time"] for c in upload.call_args_list)), 2)

    def seed_scheduled(self, count):
        self.config.update(minimum_scheduled_videos=3, lookahead_hours=72)
        rows = p.plan(self.queue, self.config, self.now)
        for i, job in enumerate(rows[:count]):
            self.queue.move(
                job["id"],
                ("queued",),
                "scheduled",
                scheduled_at=job["publish_at"],
                youtube_id=f"buffer{i:05d}",
            )
        return rows

    def test_full_scheduled_reserve_skips_generation_research_and_upload(self):
        self.seed_scheduled(4)
        self.config.update(
            footage_discovery="creator_downloads", authorized_local_creator_source="fixture.mp4"
        )
        with (
            patch("shorts_automation.footage.creator_footage.replenish_low_supply") as research,
            patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload,
        ):
            result = self.cycle()
        self.assertEqual(self.harness.drafts, [])
        self.assertEqual(result["processed"], [])
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 4)
        self.assertEqual(result["scheduled_buffer"]["status"], "ok")
        research.assert_not_called()
        upload.assert_not_called()

    def test_release_replenishes_four_before_the_reserve_drops_below_three(self):
        rows = self.seed_scheduled(4)
        self.config["max_jobs_per_pass"] = 3
        due = datetime.fromisoformat(rows[0]["publish_at"].replace("Z", "+00:00"))
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "newvid00001"},
        ) as upload:
            result = self.cycle(now=due)
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 4)
        self.assertEqual(len(self.harness.drafts), 1)
        upload.assert_called_once()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.queue.get(rows[0]["id"])["stage"], "scheduled")  # History retained.

    def test_ready_output_refills_reserve_before_spending_on_a_new_draft(self):
        rows = self.seed_scheduled(3)
        output = self.root / "ready.mp4"
        output.write_bytes(b"fixture")
        ready = rows[3]
        self.queue.move(ready["id"], ("queued",), "rendered", output=str(output))
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "newvid00001"},
        ):
            result = self.cycle()
        self.assertEqual(self.queue.get(ready["id"])["stage"], "scheduled")
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 4)
        self.assertEqual(self.harness.drafts, [])

    def test_reserve_shortfall_remains_visible_when_generation_fails(self):
        self.seed_scheduled(2)
        self.harness.draft_error = ConnectionError("offline")
        result = self.cycle()
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 2)
        self.assertEqual(result["scheduled_buffer"]["deficit"], 1)
        self.assertTrue(any("minimum 3" in problem for problem in result["problems"]))
        self.assertEqual(
            json.loads(self.health.read_text())["scheduled_buffer"]["status"], "below_minimum"
        )

    def test_shortfall_does_not_bypass_media_validation(self):
        rows = self.seed_scheduled(2)
        output = self.root / "bad.mp4"
        output.write_bytes(b"fixture")
        self.queue.move(rows[2]["id"], ("queued",), "rendered", output=str(output))
        self.harness.draft_error = ConnectionError("offline")

        def reject(*args):
            raise ValueError("Invalid media")

        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            result = self.cycle(validator=reject)
        upload.assert_not_called()
        self.assertEqual(self.queue.get(rows[2]["id"])["stage"], "needs_attention")
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 2)

    def test_only_unique_confirmed_future_public_uploads_count(self):
        self.config["minimum_scheduled_videos"] = 3
        future = (self.now + timedelta(hours=1)).isoformat()
        cases = [
            ("scheduled", self.now.isoformat(), "pastvid0001"),
            ("scheduled", (self.now - timedelta(seconds=1)).isoformat(), "pastvid0002"),
            ("uploaded_private", future, "private0001"),
            ("uploading", future, "pending0001"),
            ("upload_uncertain", future, "unknown0001"),
            ("approved", future, "approve0001"),
            ("rendered", future, "renderd0001"),
            ("scheduled", future, None),
            ("scheduled", future, "DRY_RUN_ID"),
            ("scheduled", future, "future00001"),
            ("scheduled", future, "future00001"),
        ]
        for index, (stage, release, video_id) in enumerate(cases):
            job = self.queue.enqueue(f"Counting fixture {index}")
            self.queue.move(job, ("queued",), stage, scheduled_at=release, youtube_id=video_id)
        buffer = p.scheduled_buffer(self.queue, self.config, self.now)
        self.assertEqual(buffer["future_scheduled"], 1)
        self.assertEqual(buffer["deficit"], 2)
        self.assertEqual(buffer["next_release"], future)
        self.config["publish_enabled"] = False
        self.assertIsNone(p.scheduled_buffer(self.queue, self.config, self.now))

    def test_live_clock_rechecks_reserve_after_a_release_during_upload(self):
        self.seed_scheduled(3)
        current = [self.now]

        class LiveDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return current[0]

        def service():
            current[0] += timedelta(hours=3)  # First release passes during the operation.
            return object()

        with (
            patch.object(p, "datetime", LiveDateTime),
            patch(
                "shorts_automation.publishing.youtube_uploader.upload_video",
                return_value={"id": "newvid00001"},
            ),
        ):
            result = self.cycle(now=None, service_factory=service)
        self.assertEqual(result["scheduled_buffer"]["future_scheduled"], 3)
        self.assertEqual(result["scheduled_buffer"]["checked_at"], current[0].isoformat())
        self.assertEqual(result["scheduled_buffer"]["status"], "replenishing")

    def test_invalid_reserve_config_rejected(self):
        for minimum in (0, -1, True, 1.5, 13):
            with self.subTest(minimum=minimum):
                path = self.root / "invalid_reserve.json"
                path.write_text(json.dumps(self.config | {"minimum_scheduled_videos": minimum}))
                with self.assertRaisesRegex(ValueError, "minimum_scheduled_videos"):
                    p.load_config(path)

    def test_old_footage_is_retired_and_slot_replaced_once_without_deleting_media(self):
        self.config["footage_discovery"] = "creator_downloads"
        self.config["publish_enabled"] = False
        rows = p.plan(self.queue, self.config, self.now)
        old = rows[0]
        output = self.root / "old_preview.mp4"
        output.write_bytes(b"old media retained")
        output.with_suffix(".metadata.json").write_text(
            json.dumps({"background_source": {"title": "NodeCore cave"}}), encoding="utf-8"
        )
        self.queue.move(old["id"], ("queued",), "rendered", output=str(output))
        retired = p.retire_outdated_previews(self.queue, self.config)
        self.assertEqual(retired, [old["id"][:8]])
        self.assertTrue(output.exists())
        self.assertEqual(self.queue.get(old["id"])["stage"], "rejected")
        replacement = p.plan(self.queue, self.config, self.now)[0]
        self.assertEqual(replacement["publish_at"], old["publish_at"])
        self.assertNotEqual(replacement["id"], old["id"])
        p.plan(self.queue, self.config, self.now)
        self.assertEqual(len(self.queue.list()), len(rows) + 1)

    def test_replacement_runs_earlier_publish_slot_before_older_future_job(self):
        rows = p.plan(self.queue, self.config, self.now)
        first = rows[0]
        self.queue.move(first["id"], ("queued",), "rejected", review_note=p.SUPERSEDED_STYLE)
        new = p.plan(self.queue, self.config, self.now)[0]
        self.harness.draft_error = ConnectionError("offline")
        self.cycle()
        self.assertEqual(self.queue.get(new["id"])["attempts"], 1)
        self.assertEqual(self.queue.get(rows[-1]["id"])["attempts"], 0)

    def test_retry_keeps_same_slot_and_skips_manual_queue(self):
        manual = self.queue.enqueue("Manual topic must not be published automatically")
        self.harness.draft_error = ConnectionError("offline")
        self.cycle()
        row = p.owned_jobs(self.queue)[0]
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(self.queue.get(manual)["stage"], "queued")
        self.harness.draft_error = None
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            return_value={"id": "abcdefghijk"},
        ):
            self.cycle()
        self.assertEqual(self.queue.get(row["id"])["scheduled_at"], row["publish_at"])

    def test_publish_disabled_renders_without_oauth_or_autoapproval(self):
        self.config["publish_enabled"] = False
        with (
            patch(
                "shorts_automation.publishing.youtube_uploader.get_authenticated_service"
            ) as auth,
            patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload,
        ):
            self.cycle()
        self.assertEqual(p.owned_jobs(self.queue)[0]["stage"], "rendered")
        auth.assert_not_called()
        upload.assert_not_called()

    def test_invalid_video_stops_at_attention_without_upload(self):
        def reject(*args):
            raise ValueError("corrupt")

        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            self.cycle(validator=reject)
        self.assertEqual(p.owned_jobs(self.queue)[0]["stage"], "needs_attention")
        upload.assert_not_called()

    def test_paused_publication_caps_prepared_backlog_at_one_day(self):
        self.config["publish_enabled"] = False
        for _ in range(3):
            self.cycle()
        result = self.cycle()
        self.assertEqual(len(self.harness.drafts), 3)
        self.assertEqual(result["processed"], [])
        self.assertIn("three prepared", result["publishing"])

    def test_full_paused_backlog_skips_footage_replenishment(self):
        self.config.update(publish_enabled=False, private_upload_enabled=False)
        for _ in range(3):
            self.cycle()
        self.config.update(
            footage_discovery="creator_downloads", authorized_local_creator_source="fixture.mp4"
        )
        with (
            patch(
                "shorts_automation.automation.production.retire_outdated_previews", return_value=[]
            ),
            patch("shorts_automation.footage.creator_footage.replenish_low_supply") as replenish,
            patch("shorts_automation.footage.agy_footage_research.research") as research,
        ):
            result = self.cycle()
        replenish.assert_not_called()
        research.assert_not_called()
        self.assertEqual(len(self.harness.drafts), 3)
        self.assertEqual(result["processed"], [])
        self.assertEqual(result["status"], "ok")

    def past_job(self, stage, days=14):
        p.initialize(self.queue)
        job = self.queue.enqueue(f"Historical {stage} fixture")
        self.queue.move(job, ("queued",), stage, error="Retained diagnostic")
        slot = (self.now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.queue.connect() as db:
            db.execute(
                "INSERT INTO production_slots VALUES (?,?,?)", (slot, job, self.now.isoformat())
            )
        return job

    def test_full_paused_backlog_keeps_unresolved_uploads_visible(self):
        self.config.update(publish_enabled=False, private_upload_enabled=False)
        for _ in range(3):
            self.cycle()
        old = self.past_job("upload_uncertain")
        result = self.cycle(now=self.now + timedelta(days=1))
        self.assertEqual(result["status"], "needs_attention")
        self.assertIn(old[:8] + ": upload_uncertain", result["problems"])
        self.assertEqual(len(self.harness.drafts), 3)
        self.assertEqual(sum(job["stage"] == "rendered" for job in p.owned_jobs(self.queue)), 3)

    def test_past_failed_jobs_are_history_without_failing_current_pass(self):
        self.config.update(publish_enabled=False, private_upload_enabled=True)
        old = self.past_job("failed")
        before = dict(self.queue.get(old))
        result = self.cycle()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["historical_failed_jobs"], 1)
        self.assertEqual(dict(self.queue.get(old)), before)

    def test_old_unresolved_jobs_and_future_failures_still_need_attention(self):
        self.config.update(publish_enabled=False, private_upload_enabled=True)
        unresolved = [
            self.past_job(stage, days)
            for days, stage in enumerate(("needs_attention", "uploading", "upload_uncertain"), 1)
        ]
        future = p.plan(self.queue, self.config, self.now)[-1]
        self.queue.move(future["id"], ("queued",), "failed", error="Current failure")
        result = self.cycle()
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["historical_failed_jobs"], 0)
        for job in unresolved + [future["id"]]:
            self.assertTrue(any(job[:8] in problem for problem in result["problems"]))

    def test_newly_missed_slot_is_reported_once_then_retained_as_history(self):
        self.config.update(publish_enabled=False, private_upload_enabled=True)
        first = p.plan(self.queue, self.config, self.now)[0]
        later = datetime.fromisoformat(first["publish_at"].replace("Z", "+00:00")) + timedelta(
            hours=3
        )
        result = self.cycle(now=later)
        self.assertEqual(result["status"], "needs_attention")
        self.assertTrue(any("missed publishing slot" in problem for problem in result["problems"]))
        result = self.cycle(now=later)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["historical_failed_jobs"], 1)
        self.assertEqual(self.queue.get(first["id"])["stage"], "failed")

    def test_uncertain_upload_not_retried_after_restart(self):
        with patch(
            "shorts_automation.publishing.youtube_uploader.upload_video",
            side_effect=TimeoutError("reply lost"),
        ) as upload:
            self.cycle()
            first = p.owned_jobs(self.queue)[0]
            self.assertEqual(first["stage"], "upload_uncertain")
            self.config["max_jobs_per_pass"] = 1
            self.cycle()
            self.assertEqual(self.queue.get(first["id"])["stage"], "upload_uncertain")
            self.assertEqual(
                upload.call_count, 2
            )  # one attempt per distinct job, never the first again

    def test_missed_slot_is_failed_without_immediate_upload(self):
        self.harness.draft_error = ConnectionError("offline")
        self.cycle()
        first = p.owned_jobs(self.queue)[0]
        later = datetime.fromisoformat(first["publish_at"].replace("Z", "+00:00")) + timedelta(
            minutes=1
        )
        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            self.cycle(now=later)
        self.assertEqual(self.queue.get(first["id"])["stage"], "failed")
        self.assertIn("Missed publishing slot", self.queue.get(first["id"])["error"])
        upload.assert_not_called()

    def test_disk_and_pause_prevent_generation(self):
        for mode in ("disk", "paused"):
            with self.subTest(mode=mode):
                self.config.update(enabled=True, min_free_disk_gb=5)
                if mode == "paused":
                    self.config["enabled"] = False
                with patch("shorts_automation.automation.production.shutil.disk_usage") as disk:
                    disk.return_value.free = 0 if mode == "disk" else 100 * 1024**3
                    if mode == "paused":
                        self.assertEqual(self.cycle()["status"], "paused")
                    else:
                        with self.assertRaises(RuntimeError):
                            self.cycle()
        self.assertEqual(self.harness.drafts, [])

    def test_lock_prevents_competing_worker(self):
        with runner_lock(self.root / "worker.lock"), self.assertRaises(RunnerBusy):
            self.cycle()

    def test_fresh_topics_unique_and_plan_idempotent(self):
        one = p.plan(self.queue, self.config, self.now)
        two = p.plan(self.queue, self.config, self.now)
        self.assertEqual([r["id"] for r in one], [r["id"] for r in two])
        self.assertEqual(len({r["topic"] for r in one}), len(one))
        self.assertEqual(len({r["publish_at"] for r in one}), len(one))

    def test_eastern_dst_slot_counts_and_utc_day_rollover(self):
        config = {**self.config, "lookahead_hours": 24}
        now = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)
        slots = list(p.future_slots(config, now))
        self.assertEqual(
            slots, ["2026-11-01T12:00:00Z", "2026-11-01T17:00:00Z", "2026-11-02T00:00:00Z"]
        )

    def test_cleanup_leaves_outputs_and_recent_or_unrelated_files(self):
        import os

        (self.root / "temp").mkdir()
        old = self.root / "temp" / "captions_old"
        old.mkdir()
        (old / "card.png").write_bytes(b"generated")
        unrelated = self.root / "temp" / "keep_me"
        unrelated.mkdir()
        recent = self.root / "temp" / "captions_recent"
        recent.mkdir()
        video = self.root / "video.mp4"
        video.write_bytes(b"video")
        os.utime(old, (0, 0))
        os.utime(unrelated, (0, 0))
        self.assertEqual(p.cleanup(self.config, datetime.now(timezone.utc)), 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(video.exists())

    def test_validator_requires_source_credits_and_correct_media(self):
        video = self.root / "valid.mp4"
        video.write_bytes(b"fake video; ffmpeg mocked")
        metadata = {
            "story": {"title": "The Room Behind My Door", "script": " ".join(["word"] * 130)},
            "tts_provider": "kokoro",
            "narration_duration": 49.2,
            "background_source": {
                "title": "File:Minetest gameplay.webm",
                "license": "CC BY 3.0",
                "source_url": "https://commons.wikimedia.org/wiki/File:x",
                "author": "Creator",
                "license_url": "https://creativecommons.org/licenses/by/3.0/",
            },
        }
        video.with_suffix(".metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        video.with_suffix(".credits.txt").write_text("Creator and license", encoding="utf-8")
        job = {"output": str(video), "tts_provider": "kokoro"}
        probe = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "50"},
        }
        with patch("shorts_automation.automation.production.subprocess.run") as run:
            run.return_value.stdout = json.dumps(probe)
            p.validate_output(job, {"CC BY 3.0"})
            self.assertEqual(run.call_count, 2)  # Probe and full decode.
            probe["streams"][0]["width"] = 1920
            run.return_value.stdout = json.dumps(probe)
            with self.assertRaises(ValueError):
                p.validate_output(job, {"CC BY 3.0"})
        with self.assertRaises(ValueError):
            p.validate_output(job, {"CC0"})

    def test_validator_accepts_short_outputs_but_rejects_invalid_durations(self):
        video = self.root / "short.mp4"
        video.write_bytes(b"fixture")
        metadata = {
            "story": {
                "title": "The Voice Behind My Door",
                "script": "It answered before I knocked.",
            },
            "tts_provider": "kokoro",
            "background_source": {
                "title": "Minecraft Parkour",
                "license": "Creator commercial permission",
                "source_url": "https://example.org/video",
                "author": "Creator",
                "license_url": "https://example.org/permission",
            },
        }
        video.with_suffix(".credits.txt").write_text("Creator")
        probe = {
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {},
        }
        for duration in (1.3, 10, 40.333, 44.764, 58, 0, -1, 59, float("nan"), float("inf")):
            with self.subTest(duration=duration):
                metadata["narration_duration"] = duration - 0.8
                video.with_suffix(".metadata.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                probe["format"]["duration"] = str(duration)
                with patch("shorts_automation.automation.production.subprocess.run") as run:
                    run.return_value.stdout = json.dumps(probe)
                    if 0.8 < duration <= 58:
                        p.validate_output(
                            {"output": str(video), "tts_provider": "kokoro"},
                            {"Creator commercial permission"},
                        )
                        self.assertEqual(run.call_count, 2)
                    else:
                        with self.assertRaises(ValueError):
                            p.validate_output(
                                {"output": str(video), "tts_provider": "kokoro"},
                                {"Creator commercial permission"},
                            )

    def test_source_search_precedes_quota_use_and_keeps_provider(self):
        self.config["background_queries"] = ["voxel", "racing"]
        with (
            patch(
                "shorts_automation.footage.gameplay_fetcher.get_background_clip",
                side_effect=RuntimeError("none"),
            ),
            patch("shorts_automation.rendering.pipeline.run_pipeline") as renderer,
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(RuntimeError):
                p.render_automatic(
                    self.config, story_file=self.root / "story.json", tts_provider="kokoro"
                )
            renderer.assert_not_called()
        with (
            patch(
                "shorts_automation.footage.gameplay_fetcher.get_background_clip",
                return_value=(self.root / "game.mp4", 0),
            ),
            patch("shorts_automation.rendering.pipeline.run_pipeline") as renderer,
        ):
            (self.root / "game.source.json").write_text(
                json.dumps({"title": "NodeCore gameplay"}), encoding="utf-8"
            )
            p.render_automatic(
                self.config, story_file=self.root / "story.json", tts_provider="kokoro"
            )
            self.assertEqual(renderer.call_args.kwargs["tts_provider"], "kokoro")

    def test_antigravity_queries_feed_real_worker_sourcing(self):
        self.config["footage_discovery"] = "antigravity"
        (self.root / "game.source.json").write_text(
            json.dumps({"title": "NodeCore gameplay"}), encoding="utf-8"
        )
        with (
            patch(
                "legacy.replenish_clips.ask_agy_for_queries", return_value=["AGY gameplay query"]
            ) as agy,
            patch(
                "shorts_automation.footage.gameplay_fetcher.get_background_clip",
                return_value=(self.root / "game.mp4", 0),
            ) as source,
            patch("shorts_automation.rendering.pipeline.run_pipeline"),
        ):
            p.render_automatic(
                self.config, story_file=self.root / "story.json", tts_provider="kokoro"
            )
        agy.assert_called_once()
        self.assertEqual(source.call_args.args[1], "AGY gameplay query")

    def test_stocked_footage_avoids_unnecessary_antigravity_call(self):
        self.config["footage_discovery"] = "antigravity"
        with (
            patch(
                "shorts_automation.automation.production.cached_background",
                return_value=self.root / "stock.mp4",
            ),
            patch("legacy.replenish_clips.ask_agy_for_queries") as agy,
            patch("shorts_automation.rendering.pipeline.run_pipeline") as render,
        ):
            p.render_automatic(
                self.config, story_file=self.root / "story.json", tts_provider="kokoro"
            )
        agy.assert_not_called()
        self.assertEqual(render.call_args.kwargs["background_file"], self.root / "stock.mp4")


if __name__ == "__main__":
    unittest.main()
