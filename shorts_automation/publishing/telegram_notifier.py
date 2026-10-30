"""Durable upload notifications using the user's existing Hermes Telegram bot."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from config import SECRETS_DIR

ROUTE_FILE = SECRETS_DIR / "telegram.local.json"


def send_telegram(message):
    try:
        chat_id = str(json.loads(ROUTE_FILE.read_text(encoding="utf-8"))["chat_id"])
        if not chat_id or not chat_id.lstrip("-").isdigit():
            raise ValueError("invalid chat")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Telegram route is missing or invalid.") from exc
    home = os.environ.get("HERMES_HOME")
    executable = str(Path(home) / "bin/hermes.exe") if home else shutil.which("hermes")
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Hermes executable unavailable for Telegram delivery.")
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    result = subprocess.run(
        [executable, "send", "--to", f"telegram:{chat_id}", "--json"],
        input=message,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError):
        response = {}
    if (
        result.returncode
        or not isinstance(response, dict)
        or not response.get("success")
        or not response.get("message_id")
    ):
        # CLI diagnostics can contain routing details; keep them out of health/logs.
        raise RuntimeError("Hermes Telegram delivery failed; inspect Hermes locally.")


def flush_notifications(queue, sender=None):
    """Separate message retries from uploads; a failed message never reuploads a video."""
    sender = sender or send_telegram
    with queue.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS upload_notifications (
            job_id TEXT PRIMARY KEY REFERENCES queue_jobs(id),
            sent_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT)""")
        db.execute("""INSERT OR IGNORE INTO upload_notifications (job_id)
            SELECT id FROM queue_jobs WHERE stage IN ('uploaded_private','scheduled')
            AND youtube_id IS NOT NULL""")
        pending = db.execute("""SELECT q.*, n.attempts AS notification_attempts FROM upload_notifications n
            JOIN queue_jobs q ON q.id=n.job_id WHERE n.sent_at IS NULL""").fetchall()
    sent, problems = [], []
    from shorts_automation.automation.orchestrator import _now

    for job in pending:
        title = Path(job["output"]).stem
        try:
            metadata = json.loads(
                Path(job["output"]).with_suffix(".metadata.json").read_text(encoding="utf-8")
            )
            title = metadata["story"]["title"]
            if metadata["story"].get("series"):
                series = metadata["story"]["series"]
                title = f"{series['title']} — Part {series['part']}/{series['total']}"
        except (OSError, ValueError, KeyError):
            pass
        label = (
            "Uploaded privately to YouTube"
            if job["stage"] == "uploaded_private"
            else "Uploaded to YouTube; public release scheduled"
        )
        message = f"{label}\n{title}\n{job['youtube_url']}"
        if job["stage"] == "scheduled":
            message += f"\nRelease: {job['scheduled_at']}"
        with queue.connect() as db:
            db.execute(
                "UPDATE upload_notifications SET attempts=attempts+1 WHERE job_id=?", (job["id"],)
            )
        try:
            sender(message)
        except Exception:
            with queue.connect() as db:
                db.execute(
                    "UPDATE upload_notifications SET error=? WHERE job_id=?",
                    ("Hermes delivery failed; upload retained", job["id"]),
                )
            problems.append(job["id"][:8] + ": Telegram notification pending")
        else:
            with queue.connect() as db:
                db.execute(
                    "UPDATE upload_notifications SET sent_at=?,error=NULL WHERE job_id=?",
                    (_now(), job["id"]),
                )
            sent.append(job["id"][:8])
    return sent, problems
