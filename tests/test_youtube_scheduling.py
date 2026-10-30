import datetime
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from shorts_automation.automation import orchestrator
from shorts_automation.automation.orchestrator import JobQueue
from shorts_automation.publishing.youtube_uploader import (
    build_short_metadata,
    get_authenticated_service,
    get_next_publishing_slot,
    normalize_publish_time,
    public_attribution,
    upload_video,
)


class YouTubeSchedulingTests(unittest.TestCase):
    def test_private_only_upload_has_no_public_schedule_and_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / "db.sqlite3")
            output = Path(tmp) / "video.mp4"
            output.write_bytes(b"video")
            job = queue.enqueue("Private pilot")
            queue.move(job, ("queued",), "approved", output=str(output))
            with (
                patch(
                    "shorts_automation.publishing.youtube_uploader.upload_video",
                    return_value={"id": "abcdefghijk"},
                ) as upload,
                redirect_stdout(io.StringIO()),
            ):
                row = queue.schedule_job(job, object(), private_only=True)
                self.assertEqual(row["stage"], "uploaded_private")
                self.assertEqual(row["upload_mode"], "private")
                self.assertIsNone(row["scheduled_at"])
                self.assertIsNone(upload.call_args.kwargs["scheduled_time"])
                with self.assertRaises(ValueError):
                    queue.schedule_job(job, object(), private_only=True)
                upload.assert_called_once()

    def test_uncertain_private_upload_stays_private_after_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / "db.sqlite3")
            output = Path(tmp) / "video.mp4"
            output.write_bytes(b"video")
            job = queue.enqueue("Private pilot")
            queue.move(job, ("queued",), "approved", output=str(output))
            with (
                patch(
                    "shorts_automation.publishing.youtube_uploader.upload_video",
                    side_effect=TimeoutError,
                ),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(TimeoutError):
                    queue.schedule_job(job, object(), private_only=True)
            self.assertEqual(queue.get(job)["stage"], "upload_uncertain")
            self.assertEqual(
                queue.reconcile_upload(job, "abcdefghijk", "Found private upload")["stage"],
                "uploaded_private",
            )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(
            patch(
                "shorts_automation.publishing.youtube_uploader.TOKEN_LOCK",
                self.root / "youtube-token.lock",
            )
        )
        # Preserve coverage of the former timezone independently of channel defaults.
        timezone_patch = patch(
            "shorts_automation.publishing.youtube_uploader.PUBLISH_TIMEZONE", "America/Sao_Paulo"
        )
        timezone_patch.start()
        self.addCleanup(timezone_patch.stop)

    def test_channel_schedule_keeps_three_eastern_slots_across_dst(self):
        for day, expected in (
            ("2026-10-31", [11, 16, 23]),  # EDT
            ("2026-11-01", [12, 17, 0]),  # EST, last slot is next UTC day
            ("2027-03-14", [11, 16, 23]),  # EDT resumes
        ):
            with (
                self.subTest(day=day),
                patch(
                    "shorts_automation.publishing.youtube_uploader.PUBLISH_TIMEZONE",
                    "America/New_York",
                ),
            ):
                now = datetime.datetime.fromisoformat(day).replace(
                    tzinfo=ZoneInfo("America/New_York")
                )
                booked = []
                for hour, utc_hour in zip((7, 12, 19), expected):
                    slot = get_next_publishing_slot(from_time=now, existing_scheduled=booked)
                    self.assertEqual(slot["local_dt"].date(), now.date())
                    self.assertEqual(slot["local_dt"].hour, hour)
                    instant = datetime.datetime.fromisoformat(
                        slot["utc_iso"].replace("Z", "+00:00")
                    )
                    self.assertEqual(instant.hour, utc_hour)
                    booked.append(slot["utc_iso"])
                next_slot = get_next_publishing_slot(from_time=now, existing_scheduled=booked)
                self.assertEqual(
                    next_slot["local_dt"].date(), now.date() + datetime.timedelta(days=1)
                )
                self.assertEqual(next_slot["local_dt"].hour, 7)

    def test_slot_lead_time_uses_elapsed_time_across_spring_dst(self):
        with patch(
            "shorts_automation.publishing.youtube_uploader.PUBLISH_TIMEZONE", "America/New_York"
        ):
            now = datetime.datetime(2027, 3, 14, 6, 30, tzinfo=datetime.timezone.utc)
            slot = get_next_publishing_slot(from_time=now, slots=[(3, 0), (4, 0)])
            self.assertEqual(slot["utc_iso"], "2027-03-14T08:00:00Z")

    def test_get_next_publishing_slot_is_future_and_utc(self):
        # Anchor at 10:00 local time
        fixed_local = datetime.datetime(
            2026, 10, 29, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3))
        )
        slot = get_next_publishing_slot(slots=[(9, 0), (14, 0), (19, 0)], from_time=fixed_local)
        # Next slot should be 14:00 local on the same day -> 17:00 UTC
        self.assertEqual(slot["utc_iso"], "2026-10-29T17:00:00Z")
        self.assertTrue(slot["utc_iso"].endswith("Z"))

    def test_get_next_publishing_slot_skips_booked(self):
        fixed_local = datetime.datetime(
            2026, 10, 29, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3))
        )
        booked = {"2026-10-29T17:00:00Z"}  # 14:00 local already booked
        slot = get_next_publishing_slot(
            existing_scheduled=booked, slots=[(9, 0), (14, 0), (19, 0)], from_time=fixed_local
        )
        # Should pick 19:00 local -> 22:00 UTC
        self.assertEqual(slot["utc_iso"], "2026-10-29T22:00:00Z")

    def test_get_next_publishing_slot_rolls_over_to_next_day(self):
        fixed_local = datetime.datetime(
            2026, 10, 29, 21, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3))
        )
        slot = get_next_publishing_slot(slots=[(9, 0), (14, 0), (19, 0)], from_time=fixed_local)
        # Past 19:00, so rolls over to 09:00 next day -> 12:00 UTC
        self.assertEqual(slot["utc_iso"], "2026-10-30T12:00:00Z")

    def test_build_short_metadata_extracts_sidecars(self):
        video = self.root / "test_video.mp4"
        video.write_bytes(b"dummy")
        video.with_suffix(".metadata.json").write_text(
            json.dumps(
                {
                    "story": {
                        "title": "The Whispering Walls",
                        "script": "I heard footsteps inside the plaster.",
                    }
                }
            ),
            encoding="utf-8",
        )
        video.with_suffix(".credits.txt").write_text(
            "Source: Minetest CC-BY 4.0\nAuthor: John Doe", encoding="utf-8"
        )

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
                scheduled_time="2099-10-29T12:00:00Z",
                dry_run=True,
            )
        self.assertEqual(res["id"], "DRY_RUN_ID")
        self.assertTrue(res["dry_run"])

    def test_creator_credit_survives_new_legacy_and_missing_credit_sidecars(self):
        credit = "Footage by Creator\nChannel: https://example.org/creator"
        for existing in (None, "Creator and source", "Creator and source\n" + credit):
            with self.subTest(existing=existing):
                video = self.root / "credits.mp4"
                video.write_bytes(b"fixture")
                video.with_suffix(".metadata.json").write_text(
                    json.dumps(
                        {"background_source": {"credit_required": True, "credit_text": credit}}
                    ),
                    encoding="utf-8",
                )
                credits = video.with_suffix(".credits.txt")
                if existing is None:
                    credits.unlink(missing_ok=True)
                else:
                    credits.write_text(existing, encoding="utf-8")
                self.assertEqual(build_short_metadata(video)["description"].count(credit), 1)

    def test_optional_creator_provenance_stays_local_for_old_and_new_renders(self):
        note = (
            "A credit or link back to the channel is appreciated but not required, "
            "according to the creator description."
        )
        for license_name in ("User-authorized creator footage", "Creator commercial permission"):
            for sidecar_note in ("", note + "\n"):
                with self.subTest(license=license_name, sidecar_note=sidecar_note):
                    video = self.root / "optional-credit.mp4"
                    source = {
                        "license": license_name,
                        "credit_required": False,
                        "credit_text": note,
                    }
                    video.with_suffix(".metadata.json").write_text(
                        json.dumps({"background_source": source}), encoding="utf-8"
                    )
                    credits = (
                        "Gameplay: Minecraft Parkour\nCreator: Spawn Point\n"
                        "Source: https://example.org/creator\n"
                        f"License: {license_name} https://example.org/permission\n"
                        "Changes: Extracted 60 seconds; cropped to vertical and captioned.\n"
                        + sidecar_note
                        + "Local evaluation. Listed license metadata is not publication clearance.\n"
                    )
                    sidecar = video.with_suffix(".credits.txt")
                    sidecar.write_text(credits, encoding="utf-8")
                    description = build_short_metadata(video)["description"]
                    self.assertIn("Creator: Spawn Point", description)
                    self.assertIn("Source: https://example.org/creator", description)
                    self.assertNotIn("License:", description)
                    self.assertNotIn("Changes:", description)
                    self.assertNotIn(note, description)
                    self.assertNotIn("Local evaluation.", description)
                    self.assertEqual(sidecar.read_text(encoding="utf-8"), credits)
                    sidecar.unlink()
                    self.assertNotIn(note, build_short_metadata(video)["description"])

    def test_required_or_unknown_license_attribution_is_preserved(self):
        credits = "Creator: Alice\nLicense: CC BY 4.0\nChanges: Cropped and captioned."
        for source in (
            {},
            {"license": "CC BY 4.0", "credit_required": False},
            {"license": "Creator commercial permission", "credit_required": True},
            {"license": "Creator commercial permission"},
        ):
            with self.subTest(source=source):
                self.assertEqual(public_attribution(credits, source), credits)

    def test_manual_upload_cannot_take_planned_production_slot(self):
        from shorts_automation.automation import production

        queue = JobQueue(self.root / "db.sqlite3")
        config = production.load_config()
        now = datetime.datetime(2099, 1, 15, 10, tzinfo=datetime.timezone.utc)
        planned = production.plan(queue, config, now)[0]
        manual = self.approved_job(queue, "manual")
        # The equivalent offset instant must also respect the planned reservation.
        slot = datetime.datetime.fromisoformat(planned["publish_at"].replace("Z", "+00:00"))
        equivalent = slot.astimezone(datetime.timezone(datetime.timedelta(hours=-3))).isoformat()
        with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:
            with self.assertRaisesRegex(ValueError, "already reserved"):
                queue.schedule_job(manual, object(), publish_at=equivalent)
            upload.assert_not_called()
        self.assertEqual(queue.get(manual)["stage"], "approved")

    def test_manual_default_and_bulk_preview_skip_planned_slots(self):
        from shorts_automation.automation import production

        queue = JobQueue(self.root / "db.sqlite3")
        now = datetime.datetime.now(datetime.timezone.utc)
        # Match the timezone used by this test class's scheduler fixture.
        config = production.load_config() | {"timezone": "America/Sao_Paulo"}
        planned = {r["publish_at"] for r in production.plan(queue, config, now)}
        manual = self.approved_job(queue, "manual")
        self.approved_job(queue, "second")
        with (
            patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload,
            redirect_stdout(io.StringIO()),
        ):
            preview = queue.schedule_job(manual, dry_run=True)
            self.assertNotIn(preview["preview_publish_at"], planned)
            upload.reset_mock()
            with patch("shorts_automation.automation.orchestrator.JobQueue", return_value=queue):
                self.assertEqual(orchestrator.main(["schedule-approved", "--dry-run"]), 0)
            times = [call.kwargs["scheduled_time"] for call in upload.call_args_list]
        self.assertEqual(len(times), 2)
        self.assertEqual(len(set(times)), 2)
        self.assertFalse(set(times) & planned)

    def test_automatic_job_can_upload_at_its_own_planned_slot(self):
        from shorts_automation.automation import production

        queue = JobQueue(self.root / "db.sqlite3")
        now = datetime.datetime(2099, 1, 15, 10, tzinfo=datetime.timezone.utc)
        planned = production.plan(queue, production.load_config(), now)[0]
        video = self.root / "automatic.mp4"
        video.write_bytes(b"fixture")
        queue.move(planned["id"], ("queued",), "approved", output=str(video))
        with (
            patch(
                "shorts_automation.publishing.youtube_uploader.upload_video",
                return_value={"id": "abcdefghijk"},
            ),
            redirect_stdout(io.StringIO()),
        ):
            row = queue.schedule_job(planned["id"], object(), publish_at=planned["publish_at"])
        self.assertEqual(row["stage"], "scheduled")
        self.assertEqual(row["scheduled_at"], planned["publish_at"])

    def test_orchestrator_schedule_enforces_stage_and_prevents_duplicate(self):
        queue = JobQueue(self.root / "db.sqlite3")
        job = queue.enqueue("Horror story premise")

        # 1. Cannot schedule a queued job
        with self.assertRaisesRegex(ValueError, "must be in stage 'approved'"):
            queue.schedule_job(job, dry_run=True)

        # 2. Advance to approved
        video = self.root / "short.mp4"
        video.write_bytes(b"video bytes")
        video.with_suffix(".metadata.json").write_text(
            json.dumps({"story": {"title": "Ghost", "script": "Scary text."}})
        )
        queue.move(job, ("queued",), "rendered", output=str(video))
        with self.assertRaisesRegex(ValueError, "must be in stage 'approved'"):
            queue.schedule_job(job, dry_run=True)
        queue.review(job, "approved")

        # 3. Schedule in dry-run mode
        with redirect_stdout(io.StringIO()):
            before = dict(queue.get(job))
            events = len(queue.events(job))
            scheduled_row = queue.schedule_job(job, dry_run=True, publish_at="2099-10-30T15:00:00Z")

        self.assertEqual(scheduled_row["stage"], "approved")
        self.assertEqual(dict(queue.get(job)), before)
        self.assertEqual(len(queue.events(job)), events)
        self.assertEqual(scheduled_row["preview_publish_at"], "2099-10-30T15:00:00Z")

        with (
            patch(
                "shorts_automation.publishing.youtube_uploader.upload_video",
                return_value={"id": "abcdefghijk"},
            ),
            redirect_stdout(io.StringIO()),
        ):
            queue.schedule_job(job, youtube_service=object())

        # 4. Idempotency: cannot schedule an already scheduled/uploaded job!
        with self.assertRaisesRegex(ValueError, "already uploaded to YouTube"):
            queue.schedule_job(job, dry_run=True)

    def approved_job(self, queue, topic="premise"):
        video = self.root / (topic + ".mp4")
        video.write_bytes(b"video")
        job = queue.enqueue(topic)
        queue.move(job, ("queued",), "rendered", output=str(video))
        queue.review(job, "approved")
        return job

    def test_publish_time_rejects_naive_past_and_invalid(self):
        for value in ("2020-01-01T00:00:00Z", "2099-01-01T00:00:00", "bad", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_publish_time(value)
        self.assertEqual(
            normalize_publish_time("2099-01-01T09:00:00-03:00"), "2099-01-01T12:00:00Z"
        )
        service = MagicMock()
        with self.assertRaises(ValueError):
            upload_video(
                service,
                str(self.root / "missing.mp4"),
                "title",
                "",
                scheduled_time="2020-01-01T00:00:00Z",
                dry_run=True,
            )
        service.videos.assert_not_called()

    def test_equivalent_booked_offsets_and_machine_timezone_ignored(self):
        now = datetime.datetime(2026, 10, 29, 13, tzinfo=datetime.timezone.utc)
        slot = get_next_publishing_slot(
            from_time=now,
            existing_scheduled=["2026-10-29T14:00:00-03:00"],
            slots=[(9, 0), (14, 0), (19, 0)],
        )
        self.assertEqual(slot["utc_iso"], "2026-10-29T22:00:00Z")

    def test_concurrent_requests_reserve_before_network(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        queue = JobQueue(self.root / "db.sqlite3")
        job = self.approved_job(queue)
        entered, release = Event(), Event()

        def upload(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"id": "abcdefghijk"}

        with (
            patch("shorts_automation.publishing.youtube_uploader.upload_video", side_effect=upload),
            redirect_stdout(io.StringIO()),
        ):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(queue.schedule_job, job, object())
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(queue.get(job)["stage"], "uploading")
                    with self.assertRaises(ValueError):
                        JobQueue(queue.path).schedule_job(job, object())
                    second = self.approved_job(queue, "other")
                    reserved = queue.get(job)["scheduled_at"]
                    with self.assertRaisesRegex(ValueError, "already reserved"):
                        queue.schedule_job(second, object(), publish_at=reserved)
                finally:
                    release.set()
                self.assertEqual(first.result()["stage"], "scheduled")

    def test_unknown_upload_blocks_retries_until_manual_reconciliation(self):
        queue = JobQueue(self.root / "db.sqlite3")
        job = self.approved_job(queue)
        with (
            patch(
                "shorts_automation.publishing.youtube_uploader.upload_video",
                side_effect=TimeoutError("lost reply"),
            ),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(TimeoutError):
                queue.schedule_job(job, object())
        queue = JobQueue(queue.path)  # Durable across restart.
        self.assertEqual(queue.get(job)["stage"], "upload_uncertain")
        with self.assertRaises(ValueError):
            queue.schedule_job(job, object())
        row = queue.reconcile_upload(job, "abcdefghijk", "Found upload in Studio")
        self.assertEqual(row["youtube_id"], "abcdefghijk")
        self.assertEqual(row["stage"], "scheduled")

    def test_hard_crash_reservation_requires_explicit_channel_inspection(self):
        queue = JobQueue(self.root / "db.sqlite3")
        job = self.approved_job(queue)
        queue.move(job, ("approved",), "uploading", scheduled_at="2099-01-01T12:00:00Z")
        with self.assertRaises(ValueError):
            queue.reconcile_upload(job, None, "", not_uploaded=True)
        row = queue.reconcile_upload(
            job, None, "Checked Studio: no upload exists", not_uploaded=True
        )
        self.assertEqual(row["stage"], "approved")
        self.assertIsNone(row["scheduled_at"])

    def test_missing_id_is_uncertain_and_status_accepts_sqlite_rows(self):
        queue = JobQueue(self.root / "db.sqlite3")
        job = self.approved_job(queue)
        with (
            patch("shorts_automation.publishing.youtube_uploader.upload_video", return_value={}),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(RuntimeError):
                queue.schedule_job(job, object())
        self.assertIn("upload_uncertain", orchestrator._line(queue.get(job)))

    def test_no_auth_does_not_reserve_job(self):
        queue = JobQueue(self.root / "db.sqlite3")
        job = self.approved_job(queue)
        with self.assertRaisesRegex(ValueError, "authenticated"):
            queue.schedule_job(job)
        self.assertEqual(queue.get(job)["stage"], "approved")

    def test_missing_credentials_never_open_browser_in_worker(self):
        with patch("shorts_automation.publishing.youtube_uploader.InstalledAppFlow") as flow:
            with self.assertRaisesRegex(ValueError, "login required"):
                get_authenticated_service(
                    token_path=self.root / "no-token.json",
                    client_secrets_path=self.root / "no-client.json",
                )
            flow.from_client_secrets_file.assert_not_called()

    def test_bulk_dry_run_uses_distinct_slots_and_leaves_queue_unchanged(self):
        queue = JobQueue(self.root / "db.sqlite3")
        jobs = [self.approved_job(queue, topic) for topic in ("one", "two", "three", "four")]
        before = [dict(queue.get(job)) for job in jobs]
        with (
            patch("shorts_automation.automation.orchestrator.JobQueue", return_value=queue),
            patch("shorts_automation.publishing.youtube_uploader.upload_video") as uploader,
            patch(
                "shorts_automation.publishing.youtube_uploader.get_authenticated_service"
            ) as auth,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(orchestrator.main(["schedule-approved", "--dry-run"]), 0)
        auth.assert_not_called()
        times = [call.kwargs["scheduled_time"] for call in uploader.call_args_list]
        self.assertEqual(len(times), 4)
        self.assertEqual(len(set(times)), 4)
        self.assertTrue(all(call.kwargs["dry_run"] for call in uploader.call_args_list))
        self.assertEqual([dict(queue.get(job)) for job in jobs], before)


if __name__ == "__main__":
    unittest.main()
