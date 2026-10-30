"""Durable render reservations. Crashed jobs stay reserved until explicitly released."""

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from config import OUTPUT_DIR, STORAGE_DIR

DB_PATH = STORAGE_DIR / "usage.sqlite3"
SEGMENT_POLICY = "nonoverlapping-v1"


class AlreadyUsed(RuntimeError):
    pass


def story_key(script):
    normalized = " ".join(script.casefold().split())
    return "story:" + hashlib.sha256(normalized.encode()).hexdigest()


def source_origins(metadata):
    """Stable whole-recording identities, independent of prepared segment hashes."""
    keys = []
    if metadata.get("youtube_video_id"):
        keys.append("youtube:" + str(metadata["youtube_video_id"]))
    if metadata.get("pageid"):
        keys.append("commons:" + str(metadata["pageid"]))
    url = metadata.get("download_url") or metadata.get("source_url") or metadata.get("source")
    if url and str(url).startswith("https://"):
        parsed = urlsplit(url)
        keys.append("url:" + parsed.netloc.lower() + unquote(parsed.path).replace(" ", "_"))
    if metadata.get("download_landing_url"):
        parsed = urlsplit(metadata["download_landing_url"])
        keys.append("url:" + parsed.netloc.lower().removeprefix("www.") + unquote(parsed.path))
    return list(dict.fromkeys(keys))


def segment_range(metadata):
    policy = metadata.get("segment_policy")
    if policy is None:
        return None
    if policy != SEGMENT_POLICY or not metadata.get("youtube_video_id"):
        raise ValueError("Unknown or unidentified source segment policy.")
    start = float(metadata["segment_start"])
    duration = float(metadata["segment_duration"])
    total = float(metadata["source_duration"])
    if (
        not all(math.isfinite(n) for n in (start, duration, total))
        or start < 0
        or duration <= 0
        or start + duration > total + 0.001
    ):
        raise ValueError("Source segment must be positive and within the recording.")
    begin, end = round(start * 1000), round((start + duration) * 1000)
    if end <= begin:
        raise ValueError("Source segment is shorter than millisecond precision.")
    return begin, end


def source_keys(metadata, path=None):
    origins = source_origins(metadata)
    interval = segment_range(metadata)
    keys = (
        [f"segment:{origin}:{interval[0]}:{interval[1]}" for origin in origins]
        if interval
        else list(origins)
    )
    for field in ("original_sha256", "sha256"):
        if metadata.get(field):
            keys.append("sha256:" + metadata[field])
    if path and Path(path).is_file():
        keys.append("sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest())
    return list(dict.fromkeys(keys))


class UsageStore:
    def __init__(self, path=None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, output TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS claims (
                    key TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id));
                CREATE INDEX IF NOT EXISTS claims_job ON claims(job_id);
                CREATE TABLE IF NOT EXISTS source_segments (
                    source_key TEXT NOT NULL, start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id),
                    PRIMARY KEY (source_key, start_ms, end_ms),
                    CHECK (start_ms >= 0 AND end_ms > start_ms));
                CREATE INDEX IF NOT EXISTS source_segments_job ON source_segments(job_id);
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def begin(self, script):
        job = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, NULL, NULL)",
                (job, "reserved", datetime.now(timezone.utc).isoformat()),
            )
            try:
                db.execute("INSERT INTO claims VALUES (?,?)", (story_key(script), job))
            except sqlite3.IntegrityError:
                raise AlreadyUsed("This story is already rendered or reserved.") from None
        return job

    def unavailable(self, keys):
        with self.connect() as db:
            return any(
                db.execute("SELECT 1 FROM claims WHERE key=?", (k,)).fetchone() for k in keys
            )

    def story_owner(self, script):
        """Return (job_id, status, output) of the job holding this story's claim, or None."""
        with self.connect() as db:
            return db.execute(
                "SELECT jobs.id, jobs.status, jobs.output FROM claims "
                "JOIN jobs ON jobs.id = claims.job_id WHERE claims.key=?",
                (story_key(script),),
            ).fetchone()

    @staticmethod
    def _source_conflict(db, metadata, keys, job=None):
        for key in keys:
            owner = db.execute("SELECT job_id FROM claims WHERE key=?", (key,)).fetchone()
            if owner and owner[0] != job:
                return True
        interval = segment_range(metadata)
        origins = source_origins(metadata)
        if interval:
            for origin in origins:
                # An older whole-recording claim remains conservative. Never
                # silently release historical/reserved work during migration.
                owner = db.execute("SELECT job_id FROM claims WHERE key=?", (origin,)).fetchone()
                if owner and owner[0] != job:
                    return True
                rows = db.execute(
                    "SELECT job_id,start_ms,end_ms FROM source_segments "
                    "WHERE source_key=? AND start_ms<? AND end_ms>?",
                    (origin, interval[1], interval[0]),
                ).fetchall()
                if any(row != (job, interval[0], interval[1]) for row in rows):
                    return True
        else:
            # The inverse matters too: a whole-source claim cannot cover a
            # recording with existing segment reservations or completed usage.
            for origin in origins:
                if db.execute(
                    "SELECT 1 FROM source_segments WHERE source_key=? LIMIT 1", (origin,)
                ).fetchone():
                    return True
        return False

    def source_unavailable(self, metadata, path=None):
        with self.connect() as db:
            return self._source_conflict(db, metadata, source_keys(metadata, path))

    def next_segment_start(self, metadata, total_duration, duration=60, first_start=5):
        """Find a disjoint slot; reserve_source is the final atomic admission."""
        if (
            not all(math.isfinite(n) for n in (total_duration, duration, first_start))
            or duration <= 0
            or first_start < 0
        ):
            raise ValueError("Invalid footage allocation bounds.")
        origins = source_origins(metadata)
        if not origins:
            raise ValueError("A recording needs stable identity before allocation.")
        with self.connect() as db:
            if any(
                db.execute("SELECT 1 FROM claims WHERE key=?", (origin,)).fetchone()
                for origin in origins
            ):
                return None
            ranges = [
                row
                for origin in origins
                for row in db.execute(
                    "SELECT start_ms,end_ms FROM source_segments WHERE source_key=?", (origin,)
                )
            ]
        start = first_start
        while start + duration <= total_duration + 0.001:
            begin, end = round(start * 1000), round((start + duration) * 1000)
            if not any(a < end and b > begin for a, b in ranges):
                return start
            start += duration
        return None

    def reserve_source(self, job, metadata, path=None):
        keys = source_keys(metadata, path)
        if not keys:
            raise ValueError("Cannot reserve footage without source identity.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone() != ("reserved",):
                raise ValueError("Job is not reservable.")
            if self._source_conflict(db, metadata, keys, job):
                raise AlreadyUsed(
                    "This footage or an overlapping segment is already rendered or reserved."
                )
            for key in keys:
                owner = db.execute("SELECT job_id FROM claims WHERE key=?", (key,)).fetchone()
                if owner and owner[0] != job:
                    raise AlreadyUsed("This footage is already rendered or reserved.")
                db.execute("INSERT OR IGNORE INTO claims VALUES (?,?)", (key, job))
            interval = segment_range(metadata)
            if interval:
                for origin in source_origins(metadata):
                    db.execute(
                        "INSERT OR IGNORE INTO source_segments VALUES (?,?,?,?)",
                        (origin, *interval, job),
                    )

    def complete(self, job, output):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status='rendered', output=? WHERE id=? AND status='reserved'",
                (str(Path(output).resolve()), job),
            )
            if cursor.rowcount != 1:
                raise ValueError("Cannot complete an inactive job.")

    def plan_output(self, job, output):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET output=? WHERE id=? AND status='reserved'",
                (str(Path(output).resolve()), job),
            )

    def release_reservation(self, job):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,output FROM jobs WHERE id=?", (job,)).fetchone()
            if not row or row[0] != "reserved":
                raise ValueError("Only reserved jobs can be released.")
            if row[1] and Path(row[1]).exists():
                raise ValueError(
                    "An output exists. Inspect/reconcile it before releasing this job."
                )
            db.execute("DELETE FROM claims WHERE job_id=?", (job,))
            db.execute("DELETE FROM source_segments WHERE job_id=?", (job,))
            db.execute(
                "UPDATE jobs SET status='failed', error='Reservation manually released' WHERE id=?",
                (job,),
            )

    def fail(self, job):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone() == ("reserved",):
                db.execute("DELETE FROM claims WHERE job_id=?", (job,))
                db.execute("DELETE FROM source_segments WHERE job_id=?", (job,))
                db.execute(
                    "UPDATE jobs SET status='failed', error='Render interrupted or failed' WHERE id=?",
                    (job,),
                )

    def import_outputs(self, directory=OUTPUT_DIR):
        count = 0
        for sidecar in Path(directory).glob("*.metadata.json"):
            output = sidecar.with_name(sidecar.name.replace(".metadata.json", ".mp4"))
            if not output.is_file():
                continue
            d = json.loads(sidecar.read_text(encoding="utf-8"))
            keys = [story_key(d["story"]["script"]), *source_keys(d.get("background_source", {}))]
            job = "import:" + hashlib.sha256(str(output.resolve()).encode()).hexdigest()
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT 1 FROM jobs WHERE id=? OR output=?", (job, str(output.resolve()))
                ).fetchone():
                    continue
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,NULL)",
                    (
                        job,
                        "rendered",
                        datetime.now(timezone.utc).isoformat(),
                        str(output.resolve()),
                    ),
                )
                for key in keys:
                    db.execute("INSERT OR IGNORE INTO claims VALUES (?,?)", (key, job))
                source = d.get("background_source", {})
                interval = segment_range(source)
                if interval:
                    for origin in source_origins(source):
                        db.execute(
                            "INSERT OR IGNORE INTO source_segments VALUES (?,?,?,?)",
                            (origin, *interval, job),
                        )
                count += 1
        return count


@contextmanager
def render_job(script):
    store = UsageStore()
    store.import_outputs()
    job = store.begin(script)
    try:
        yield store, job
    finally:
        # A completed render keeps its claims even if writing the sidecar fails.
        store.fail(job)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-reservation",
        help="Only for a stopped job with no output; never release a running job.",
    )
    args = parser.parse_args()
    store = UsageStore()
    print("Imported output records:", store.import_outputs())
    if args.release_reservation:
        store.release_reservation(args.release_reservation)
    with store.connect() as db:
        for row in db.execute("SELECT id,status,output FROM jobs ORDER BY created_at"):
            print(*row)
