"""Durable Shorts production queue: topic -> draft -> render -> human review.

Rendering stops at review. Explicit scheduling uploads approved jobs only.
Only one runner works at a time (OS file lock, released automatically if the
process dies). Every job stops after MAX_ATTEMPTS failures in total, which
bounds subscription/TTS usage per topic.

Stages:
  queued -> drafting -> drafted -> rendering -> rendered (awaiting review)
  rendered -> approved | rejected
  any failure -> retried, or `failed` after MAX_ATTEMPTS
  interrupted render still holding its reservation -> needs_attention
"""

import argparse
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import SPEECH_WORDS_PER_SECOND, STORAGE_DIR
from shorts_automation.automation import series_queue
from shorts_automation.state.usage_store import DB_PATH, AlreadyUsed, UsageStore
from shorts_automation.stories.draft_story import validate_story

LOCK_PATH = STORAGE_DIR / "orchestrator.lock"
MAX_ATTEMPTS = 3
STAGES = (
    "queued",
    "drafting",
    "drafted",
    "rendering",
    "rendered",
    "approved",
    "rejected",
    "uploading",
    "upload_uncertain",
    "scheduled",
    "uploaded_private",
    "failed",
    "needs_attention",
)
_FIELDS = {
    "attempts",
    "story_path",
    "render_job",
    "output",
    "error",
    "review_note",
    "youtube_id",
    "scheduled_at",
    "youtube_url",
}


class RunnerBusy(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _summary(error):
    return f"{type(error).__name__}: {str(error)[:300]}"


def _read_story(path):
    return validate_story(json.loads(Path(path).read_text(encoding="utf-8")))


class JobQueue:
    def __init__(self, path=None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    id TEXT PRIMARY KEY, topic TEXT NOT NULL, tts_provider TEXT NOT NULL,
                    gameplay_query TEXT, background_file TEXT, stage TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, story_path TEXT, render_job TEXT,
                    output TEXT, error TEXT, review_note TEXT,
                    youtube_id TEXT, scheduled_at TEXT, youtube_url TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS queue_jobs_stage ON queue_jobs(stage, created_at);
                CREATE TABLE IF NOT EXISTS queue_events (
                    job_id TEXT NOT NULL REFERENCES queue_jobs(id), at TEXT NOT NULL,
                    stage TEXT NOT NULL, detail TEXT);
                CREATE INDEX IF NOT EXISTS queue_events_job ON queue_events(job_id);
            """)
            for col in ("youtube_id", "scheduled_at", "youtube_url"):
                try:
                    db.execute(f"ALTER TABLE queue_jobs ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass
            if "upload_mode" not in {r[1] for r in db.execute("PRAGMA table_info(queue_jobs)")}:
                db.execute("ALTER TABLE queue_jobs ADD COLUMN upload_mode TEXT")
            db.executescript(series_queue.SCHEMA)
            series_queue.migrate(db)

    def assign_gender(self, kind, identity):
        """Reserve one alternating assignment per story or complete arc."""
        if kind not in ("story", "series") or not identity:
            raise ValueError("A story or series identity is required.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS protagonist_assignments (kind TEXT NOT NULL, identity TEXT NOT NULL, gender TEXT NOT NULL, PRIMARY KEY(kind, identity))"
            )
            row = db.execute(
                "SELECT gender FROM protagonist_assignments WHERE kind=? AND identity=?",
                (kind, identity),
            ).fetchone()
            if row:
                return row[0]
            count = db.execute("SELECT COUNT(*) FROM protagonist_assignments").fetchone()[0]
            gender = "male" if count % 2 == 0 else "female"
            db.execute(
                "INSERT INTO protagonist_assignments VALUES (?,?,?)", (kind, identity, gender)
            )
            return gender

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _event(db, job, stage, detail=None):
        db.execute("INSERT INTO queue_events VALUES (?,?,?,?)", (job, _now(), stage, detail))

    # ---- queries -------------------------------------------------------
    def get(self, ref):
        """Fetch by full id or a unique prefix (handy from Telegram)."""
        ref = (ref or "").strip().lower()
        if len(ref) < 4:
            raise ValueError("Use at least 4 characters of the job id.")
        with self.connect() as db:
            rows = db.execute("SELECT * FROM queue_jobs WHERE id LIKE ?", (ref + "%",)).fetchall()
        if len(rows) != 1:
            raise ValueError(f"{'No' if not rows else 'Ambiguous'} job matches {ref!r}.")
        return rows[0]

    def list(self, stage=None):
        with self.connect() as db:
            if stage:
                return db.execute(
                    "SELECT * FROM queue_jobs WHERE stage=? ORDER BY created_at, rowid", (stage,)
                ).fetchall()
            return db.execute("SELECT * FROM queue_jobs ORDER BY created_at, rowid").fetchall()

    def events(self, job):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM queue_events WHERE job_id=? ORDER BY rowid", (job,)
            ).fetchall()

    # ---- transitions ---------------------------------------------------
    def enqueue(self, topic, tts_provider="kokoro", gameplay_query=None, background_file=None):
        topic = " ".join((topic or "").split())
        if not 1 <= len(topic) <= 1000:
            raise ValueError("Topic must contain 1 to 1,000 characters.")
        if tts_provider not in SPEECH_WORDS_PER_SECOND:
            raise ValueError(f"Unknown speech provider: {tts_provider}")
        if background_file:
            background_file = str(Path(background_file).resolve(strict=True))
        job, now = uuid4().hex, _now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO queue_jobs (id, topic, tts_provider, gameplay_query, background_file,"
                " stage, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (job, topic, tts_provider, gameplay_query, background_file, "queued", now, now),
            )
            self._event(db, job, "queued", "enqueued")
        return job

    def move(self, job, expected, stage, detail=None, **fields):
        """Conditional transition: fails loudly if another actor already moved the job."""
        assert stage in STAGES and set(fields) <= _FIELDS
        sets = ", ".join(["stage=?", "updated_at=?"] + [f"{k}=?" for k in fields])
        marks = ",".join("?" * len(expected))
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE queue_jobs SET {sets} WHERE id=? AND stage IN ({marks})",
                (stage, _now(), *fields.values(), job, *expected),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Job {job[:8]} is not in stage {'/'.join(expected)}.")
            self._event(db, job, stage, detail)
        return self.get(job)

    def claim_next(self, exclude=(), include=None):
        """Atomically take the oldest actionable job and mark it in progress."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exclusions = (
                " AND id NOT IN (" + ",".join("?" for _ in exclude) + ")" if exclude else ""
            )
            if include is not None:
                if not include:
                    return None
                exclusions += " AND id IN (" + ",".join("?" for _ in include) + ")"
            row = db.execute(
                "SELECT id, stage FROM queue_jobs WHERE stage IN ('queued','drafted') "
                + exclusions
                + " ORDER BY created_at, rowid LIMIT 1",
                (*exclude, *(include or ())),
            ).fetchone()
            if row is None:
                return None
            stage = "drafting" if row["stage"] == "queued" else "rendering"
            db.execute(
                "UPDATE queue_jobs SET stage=?, updated_at=? WHERE id=?", (stage, _now(), row["id"])
            )
            self._event(db, row["id"], stage, "claimed by runner")
        return self.get(row["id"])

    def fail_attempt(self, job, retry_stage, error, clear_story=False):
        attempts = job["attempts"] + 1
        stage = retry_stage if attempts < MAX_ATTEMPTS else "failed"
        fields = {"attempts": attempts, "error": _summary(error)}
        if clear_story:
            fields["story_path"] = None
        detail = f"attempt {attempts}/{MAX_ATTEMPTS} failed: {_summary(error)}"
        return self.move(job["id"], (job["stage"],), stage, detail, **fields)

    def review(self, ref, decision, note=None):
        if decision not in ("approved", "rejected"):
            raise ValueError("Decision must be approved or rejected.")
        job = self.get(ref)
        return self.move(job["id"], ("rendered",), decision, note or "reviewed", review_note=note)

    def retry(self, ref, usage):
        """Manually requeue a failed or needs_attention job with a fresh attempt budget."""
        job = self.get(ref)
        if job["stage"] not in ("failed", "needs_attention"):
            raise ValueError("Only failed or needs_attention jobs can be retried.")
        stage, story_path = "queued", None
        if job["story_path"]:
            try:
                story = _read_story(job["story_path"])
            except (OSError, ValueError):
                story = None
            owner = usage.story_owner(story["script"]) if story else None
            if owner and owner[1] == "reserved":
                raise ValueError(
                    f"Render {owner[0]} still holds this story. Inspect it, then run: "
                    f"python -m shorts_automation.state.usage_store --release-reservation {owner[0]}"
                )
            if story and not owner:
                stage, story_path = "drafted", job["story_path"]
        return self.move(
            job["id"],
            (job["stage"],),
            stage,
            "manual retry",
            attempts=0,
            error=None,
            story_path=story_path,
        )

    @staticmethod
    def _booked_slots(db, job_id):
        """Include planned production work in the same transaction as uploads."""
        booked = [
            row[0]
            for row in db.execute(
                "SELECT scheduled_at FROM queue_jobs WHERE scheduled_at IS NOT NULL AND id != ?",
                (job_id,),
            )
        ]
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_slots'"
        ).fetchone():
            booked.extend(
                row[0]
                for row in db.execute(
                    "SELECT publish_at FROM production_slots WHERE job_id != ?", (job_id,)
                )
            )
        return booked

    def schedule_job(
        self,
        ref,
        youtube_service=None,
        dry_run=False,
        publish_at=None,
        private_only=False,
        preview_series_slots=None,
    ):
        """Reserve a job and slot before any network call; never auto-repeat an uncertain upload."""
        from shorts_automation.publishing.youtube_uploader import (
            build_short_metadata,
            get_next_publishing_slot,
            normalize_publish_time,
            upload_video,
        )

        job = self.get(ref)
        if job["youtube_id"]:
            raise ValueError(
                f"Job {job['id'][:8]} is already uploaded to YouTube (ID: {job['youtube_id']})."
            )
        if job["stage"] != "approved":
            raise ValueError(
                f"Job {job['id'][:8]} must be in stage 'approved' to schedule (current: {job['stage']})."
            )
        if not job["output"] or not Path(job["output"]).is_file():
            raise ValueError(f"Job output video file does not exist: {job['output']}")

        video_path = Path(job["output"])
        meta = build_short_metadata(video_path)
        if not dry_run and youtube_service is None:
            raise ValueError("YouTube service is not authenticated.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT stage, youtube_id FROM queue_jobs WHERE id=?", (job["id"],)
            ).fetchone()
            if current["stage"] != "approved" or current["youtube_id"]:
                raise ValueError("Job is no longer approved or already has an upload reservation.")
            booked = self._booked_slots(db, job["id"])
            # Canonicalize legacy offset strings as well as Z timestamps.
            from shorts_automation.publishing.youtube_uploader import _scheduled_instant

            if private_only:
                utc_iso = None
            elif publish_at:
                utc_iso = normalize_publish_time(publish_at)
                if _scheduled_instant(utc_iso) in {_scheduled_instant(t) for t in booked}:
                    raise ValueError("This publishing slot is already reserved.")
            else:
                utc_iso = get_next_publishing_slot(existing_scheduled=booked)["utc_iso"]
            series_queue.guard_schedule(
                db, job["id"], utc_iso, private_only, preview_series_slots if dry_run else None
            )
            if not dry_run:
                db.execute(
                    "UPDATE queue_jobs SET stage='uploading', scheduled_at=?, upload_mode=?, updated_at=?, error=NULL WHERE id=?",
                    (utc_iso, "private" if private_only else "scheduled", _now(), job["id"]),
                )
                self._event(
                    db,
                    job["id"],
                    "uploading",
                    f"upload reserved {'private only' if private_only else 'for ' + utc_iso}; do not retry automatically",
                )
        print(f"[*] Scheduling '{meta['title']}' for {utc_iso}...")
        if dry_run:
            upload_video(
                None,
                str(video_path),
                title=meta["title"],
                description=meta["description"],
                tags=meta["tags"],
                scheduled_time=utc_iso,
                dry_run=True,
            )
            return {**dict(job), "preview_publish_at": utc_iso}
        try:
            res = upload_video(
                youtube_service,
                str(video_path),
                title=meta["title"],
                description=meta["description"],
                tags=meta["tags"],
                scheduled_time=utc_iso,
            )
            vid = res.get("id")
            if not isinstance(vid, str) or not vid.strip() or vid == "DRY_RUN_ID":
                raise RuntimeError("Upload returned no real video ID.")
        except BaseException:
            self.move(
                job["id"],
                ("uploading",),
                "upload_uncertain",
                "Upload may have reached YouTube. Inspect channel before reconciliation.",
                error="Upload outcome unknown. Automatic retry blocked; inspect YouTube Studio.",
            )
            raise
        url = f"https://youtube.com/shorts/{vid}"
        return self.move(
            job["id"],
            ("uploading",),
            "uploaded_private" if private_only else "scheduled",
            f"{'uploaded privately' if private_only else 'scheduled for ' + utc_iso} (YouTube ID: {vid})",
            youtube_id=vid,
            scheduled_at=utc_iso,
            youtube_url=url,
        )

    def reconcile_upload(self, ref, video_id, note, not_uploaded=False):
        """Record manual channel inspection after an exception or hard process termination."""
        import re

        job = self.get(ref)
        if not note or not note.strip():
            raise ValueError("A channel inspection note is required.")
        if bool(video_id) == bool(not_uploaded):
            raise ValueError("Supply a YouTube video ID or confirm that no upload exists.")
        if video_id and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("YouTube video ID must contain 11 URL-safe characters.")
        fields = {"error": None}
        if video_id:
            fields.update(youtube_id=video_id, youtube_url=f"https://youtube.com/shorts/{video_id}")
        else:
            fields.update(scheduled_at=None, youtube_id=None, youtube_url=None)
        return self.move(
            job["id"],
            ("uploading", "upload_uncertain"),
            ("uploaded_private" if job["upload_mode"] == "private" else "scheduled")
            if video_id
            else "approved",
            "manual upload reconciliation: " + note,
            **fields,
        )

    def recover_interrupted(self, usage):
        """Resolve jobs left in progress by a runner that died. Call only while holding the lock."""
        recovered = []
        for job in self.list("drafting"):
            recovered.append(
                self.move(
                    job["id"],
                    ("drafting",),
                    "queued",
                    "runner stopped during drafting; will redraft",
                )
            )
        for job in self.list("rendering"):
            try:
                owner = usage.story_owner(_read_story(job["story_path"])["script"])
            except (OSError, ValueError, TypeError):
                owner = None
            if owner is None:
                job = self.move(
                    job["id"],
                    ("rendering",),
                    "drafted",
                    "render interrupted with no held reservation; will retry",
                )
            elif owner[1] == "rendered" and owner[2] and Path(owner[2]).is_file():
                job = self.move(
                    job["id"],
                    ("rendering",),
                    "rendered",
                    "render had finished before the runner stopped",
                    output=owner[2],
                    render_job=owner[0],
                    error=None,
                )
            else:
                problem = (
                    f"Render {owner[0]} was interrupted (status {owner[1]}, output "
                    f"{owner[2] or 'not planned'}). Inspect the output. If none exists, run "
                    f"python -m shorts_automation.state.usage_store --release-reservation {owner[0]}, then orchestrator.py retry {job['id'][:8]}."
                )
                job = self.move(
                    job["id"],
                    ("rendering",),
                    "needs_attention",
                    problem,
                    render_job=owner[0],
                    error=problem,
                )
            recovered.append(job)
        return recovered


@contextmanager
def runner_lock(path=LOCK_PATH):
    """Non-blocking exclusive lock; the OS releases it if the process crashes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RunnerBusy("Another orchestrator run is active.") from None
    try:
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


# ---- runner --------------------------------------------------------------
def _draft(queue, job, drafter, series_drafter=None):
    try:
        if series_queue.info(queue, job["id"]):
            if series_drafter is None:
                from shorts_automation.stories.series_story import draft_series as series_drafter
            return series_queue.draft_job(queue, job, series_drafter)
        path = drafter(job["topic"], gender=queue.assign_gender("story", job["id"]))
        story = _read_story(path)  # Never advance an unreadable or out-of-range draft.
        if story.get("protagonist_gender") != queue.assign_gender("story", job["id"]) or story.get(
            "narrator_gender"
        ) != story.get("protagonist_gender"):
            raise ValueError("Draft did not respect assigned protagonist gender.")
    except Exception as error:
        return queue.fail_attempt(job, "queued", error)
    return queue.move(
        job["id"],
        ("drafting",),
        "drafted",
        f"story saved: {Path(path).name}",
        story_path=str(path),
        error=None,
    )


def _render(queue, job, renderer, usage):
    from shorts_automation.rendering.pipeline import NarrationTooLong

    serial = series_queue.info(queue, job["id"])
    try:
        story = _read_story(job["story_path"])
        series_queue.check_story(queue, job, story)
    except (OSError, ValueError, TypeError) as error:
        if serial:
            return queue.move(
                job["id"],
                ("rendering",),
                "needs_attention",
                "Inspect the complete series draft",
                error=_summary(error),
            )
        return queue.fail_attempt(job, "queued", error, clear_story=True)
    if usage.story_owner(story["script"]):
        if serial:
            return queue.move(
                job["id"],
                ("rendering",),
                "needs_attention",
                "Series draft duplicates used narration",
                error="Inspect the full arc; no independent episode redraft performed.",
            )
        # Checked before any TTS call: an identical story would be blocked anyway.
        return queue.fail_attempt(
            job, "queued", AlreadyUsed("Draft duplicates an existing story."), clear_story=True
        )
    background = job["background_file"]
    try:
        output = Path(
            renderer(
                story_file=Path(job["story_path"]),
                tts_provider=job["tts_provider"],
                gameplay_query=job["gameplay_query"],
                background_file=Path(background) if background else None,
            )
        )
    except NarrationTooLong as error:
        if serial:
            return queue.move(
                job["id"],
                ("rendering",),
                "needs_attention",
                "Shorten the complete series draft consistently",
                error=_summary(error),
            )
        return queue.fail_attempt(job, "queued", error, clear_story=True)
    except Exception as error:
        return queue.fail_attempt(job, "drafted", error)
    sidecar = output.with_suffix(".metadata.json")
    render_job = (
        json.loads(sidecar.read_text(encoding="utf-8")).get("job_id") if sidecar.is_file() else None
    )
    return queue.move(
        job["id"],
        ("rendering",),
        "rendered",
        "awaiting review",
        output=str(output),
        render_job=render_job,
        error=None,
    )


def process_one(queue, usage, drafter, renderer, exclude=(), include=None, series_drafter=None):
    """Advance the oldest actionable job as far as it can go. Returns its final row or None."""
    if include is None:
        include = [row["id"] for row in queue.list() if row["stage"] in ("queued", "drafted")]
    include = [identity for identity in include if series_queue.can_process(queue, identity)]
    job = queue.claim_next(exclude, include)
    if job is None:
        return None
    if job["stage"] == "drafting":
        job = _draft(queue, job, drafter, series_drafter)
        if job["stage"] != "drafted":
            return job
        job = queue.move(job["id"], ("drafted",), "rendering", "continuing to render")
    return _render(queue, job, renderer, usage)


def run(max_jobs=1, queue=None, usage=None, drafter=None, renderer=None, lock_path=LOCK_PATH):
    queue, usage = queue or JobQueue(), usage or UsageStore()
    if drafter is None:
        from shorts_automation.stories.draft_story import draft as drafter
    if renderer is None:
        from shorts_automation.rendering.pipeline import run_pipeline as renderer
    with runner_lock(lock_path):
        usage.import_outputs()
        recovered = queue.recover_interrupted(usage)
        processed = []
        while len(processed) < max_jobs:
            job = process_one(queue, usage, drafter, renderer, exclude=[j["id"] for j in processed])
            if job is None:
                break
            processed.append(job)
    return recovered, processed


# ---- CLI -----------------------------------------------------------------
def _line(job, series=None):
    job = dict(job)
    note = job["error"] or job["review_note"] or ""
    if job.get("youtube_id"):
        note = f"YouTube: {job['youtube_id']}"
    sched = f" [{job['scheduled_at'][:16]}]" if job.get("scheduled_at") else ""
    label = f" [Part {series['part']}/{series['part_count']}]" if series else ""
    return (
        f"{job['id'][:8]}  {job['stage']:<15} {job['attempts']}/{MAX_ATTEMPTS}  "
        f"{job['tts_provider']:<10} {job['topic'][:35]:<35}  {note[:45]}{sched}{label}"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("enqueue", help="Add topics to the queue.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--topic")
    group.add_argument("--topics-file", type=Path, help="UTF-8 text file, one premise per line.")
    p.add_argument("--provider", choices=sorted(SPEECH_WORDS_PER_SECOND), default="kokoro")
    p.add_argument("--gameplay", help="Commons search query for background footage.")
    p.add_argument("--background-file", type=Path, help="Owned/licensed local footage.")
    p = sub.add_parser("run", help="Draft and render queued jobs, then stop at review.")
    p.add_argument("--max-jobs", type=int, default=1)
    p = sub.add_parser("status", help="List jobs.")
    p.add_argument("--stage", choices=STAGES)
    p = sub.add_parser("show", help="Job details and history.")
    p.add_argument("job")
    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name.title()} a rendered video.")
        p.add_argument("job")
        p.add_argument("--note")
    p = sub.add_parser("retry", help="Requeue a failed or needs_attention job.")
    p.add_argument("job")
    p = sub.add_parser("replenish", help="Replenish unreserved background footage pool.")
    p.add_argument("--target", type=int, default=3)
    p.add_argument("--query", type=str, default=None)
    p.add_argument(
        "--with-agy", action="store_true", help="Summon AGY Flash agent to discover queries."
    )
    p.add_argument("--hint", type=str, default=None)
    p = sub.add_parser("schedule", help="Schedule an approved video on YouTube.")
    p.add_argument("job")
    p.add_argument(
        "--publish-at",
        type=str,
        default=None,
        help="Explicit UTC ISO timestamp (e.g. 2026-10-29T15:00:00Z).",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Simulate upload without sending API requests."
    )
    p = sub.add_parser("schedule-approved", help="Schedule all approved videos automatically.")
    p.add_argument(
        "--dry-run", action="store_true", help="Simulate upload without sending API requests."
    )
    p = sub.add_parser("reconcile-upload", help="Record manual inspection of an uncertain upload.")
    p.add_argument("job")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--video-id")
    group.add_argument("--not-uploaded", action="store_true")
    p.add_argument("--note", required=True)
    args = parser.parse_args(argv)

    queue = JobQueue()
    try:
        if args.command == "enqueue":
            topics = (
                [args.topic]
                if args.topic
                else [
                    t
                    for t in args.topics_file.read_text(encoding="utf-8").splitlines()
                    if t.strip()
                ]
            )
            for topic in topics:
                print(
                    "queued",
                    queue.enqueue(topic, args.provider, args.gameplay, args.background_file)[:8],
                    topic[:60],
                )
        elif args.command == "run":
            if args.max_jobs < 1:
                parser.error("--max-jobs must be at least 1.")
            try:
                recovered, processed = run(args.max_jobs, queue)
            except RunnerBusy as error:
                print(error)
                return 0
            for job in recovered:
                print("recovered", _line(job))
            for job in processed:
                print("processed", _line(job))
            if not processed:
                print("Nothing to do.")
            return (
                1
                if any(j["stage"] in ("failed", "needs_attention") for j in recovered + processed)
                else 0
            )
        elif args.command == "status":
            for job in queue.list(args.stage):
                print(_line(job, series_queue.info(queue, job["id"])))
        elif args.command == "show":
            job = queue.get(args.job)
            for key in job.keys():
                print(f"{key:>15}: {job[key]}")
            series = series_queue.info(queue, job["id"])
            if series:
                print(
                    f"{'series':>15}: {series['id']} — Part {series['part']}/{series['part_count']}"
                )
                print(f"{'series_manifest':>15}: {series['manifest_path'] or 'not drafted'}")
                for part in series_queue.members(queue, series["id"]):
                    print(f"  Part {part['series_part']}: {part['id'][:8]} {part['stage']}")
            print("\nHistory:")
            for event in queue.events(job["id"]):
                print(f"  {event['at']}  {event['stage']:<15} {event['detail'] or ''}")
        elif args.command in ("approve", "reject"):
            decision = {"approve": "approved", "reject": "rejected"}[args.command]
            print(_line(queue.review(args.job, decision, args.note)))
        elif args.command == "retry":
            print(_line(queue.retry(args.job, UsageStore())))
        elif args.command == "replenish":
            from legacy.replenish_clips import replenish

            replenish(
                target=args.target, query=args.query, with_agy=args.with_agy, prompt_hint=args.hint
            )
        elif args.command == "schedule":
            from shorts_automation.publishing.youtube_uploader import get_authenticated_service

            yt = None if args.dry_run else get_authenticated_service(interactive=False)
            job = queue.schedule_job(
                args.job, youtube_service=yt, dry_run=args.dry_run, publish_at=args.publish_at
            )
            print(_line(job))
        elif args.command == "schedule-approved":
            from shorts_automation.publishing.youtube_uploader import get_authenticated_service

            approved = queue.list("approved")
            if not approved:
                print("No approved jobs to schedule.")
                return 0
            yt = None if args.dry_run else get_authenticated_service(interactive=False)
            preview_slots = []
            preview_series_slots = {}
            for row in approved:
                publish_at = None
                if args.dry_run:
                    from shorts_automation.publishing.youtube_uploader import (
                        get_next_publishing_slot,
                    )

                    with queue.connect() as db:
                        booked = queue._booked_slots(db, row["id"])
                    publish_at = get_next_publishing_slot(
                        existing_scheduled=booked + preview_slots
                    )["utc_iso"]
                    preview_slots.append(publish_at)
                job = queue.schedule_job(
                    row["id"],
                    youtube_service=yt,
                    dry_run=args.dry_run,
                    publish_at=publish_at,
                    preview_series_slots=preview_series_slots,
                )
                if args.dry_run:
                    preview_series_slots[row["id"]] = job["preview_publish_at"]
                print(_line(job))
        elif args.command == "reconcile-upload":
            print(
                _line(queue.reconcile_upload(args.job, args.video_id, args.note, args.not_uploaded))
            )
    except ValueError as error:
        print("Error:", error)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
