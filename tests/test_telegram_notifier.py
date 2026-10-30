import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.automation.orchestrator import JobQueue
from shorts_automation.publishing.telegram_notifier import flush_notifications


class NotificationTests(unittest.TestCase):
    def test_failure_retries_only_notification_and_persists_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / "db.sqlite3")
            path = Path(tmp) / "video.mp4"
            path.write_bytes(b"video")
            path.with_suffix(".metadata.json").write_text(
                json.dumps({"story": {"title": "A Test Story Title"}})
            )
            job = queue.enqueue("private test")
            queue.move(
                job,
                ("queued",),
                "uploaded_private",
                output=str(path),
                youtube_id="abcdefghijk",
                youtube_url="https://youtube.com/shorts/abcdefghijk",
            )
            with patch("shorts_automation.publishing.youtube_uploader.upload_video") as upload:

                def fail(message):
                    raise RuntimeError("network")

                sent, problems = flush_notifications(queue, fail)
                self.assertFalse(sent)
                self.assertTrue(problems)
                messages = []
                sent, problems = flush_notifications(queue, messages.append)
                self.assertEqual(sent, [job[:8]])
                self.assertFalse(problems)
                self.assertIn("A Test Story Title", messages[0])
                self.assertEqual(
                    flush_notifications(JobQueue(queue.path), messages.append), ([], [])
                )
                self.assertEqual(len(messages), 1)
                upload.assert_not_called()

    def test_exhausted_pending_notification_can_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / "db.sqlite3")
            job = queue.enqueue("private test")
            queue.move(
                job,
                ("queued",),
                "uploaded_private",
                output=str(Path(tmp) / "v.mp4"),
                youtube_id="abcdefghijk",
                youtube_url="https://youtube.com/shorts/abcdefghijk",
            )
            flush_notifications(
                queue, lambda message: (_ for _ in ()).throw(RuntimeError("offline"))
            )
            with queue.connect() as db:
                db.execute("UPDATE upload_notifications SET attempts=6 WHERE job_id=?", (job,))
            messages = []
            self.assertEqual(flush_notifications(queue, messages.append), ([job[:8]], []))
            self.assertEqual(len(messages), 1)

    def test_failed_unknown_and_rendered_jobs_do_not_notify(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / "db.sqlite3")
            for stage in ("rendered", "upload_uncertain", "failed"):
                job = queue.enqueue(stage)
                queue.move(job, ("queued",), stage)
            messages = []
            self.assertEqual(flush_notifications(queue, messages.append), ([], []))
            self.assertFalse(messages)
