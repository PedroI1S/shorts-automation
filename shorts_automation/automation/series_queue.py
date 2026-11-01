"""Durable series membership, complete-arc admission and ordered publication."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from shorts_automation.stories.draft_story import validate_story
from shorts_automation.stories.series_story import episode_story, read_manifest

SCHEMA = """
    CREATE TABLE IF NOT EXISTS story_series (
        id TEXT PRIMARY KEY, topic TEXT NOT NULL, tts_provider TEXT NOT NULL,
        part_count INTEGER NOT NULL CHECK (part_count IN (3,4)),
        title TEXT, manifest_path TEXT, created_at TEXT NOT NULL,
        format TEXT NOT NULL DEFAULT 'narrated');
    CREATE TABLE IF NOT EXISTS series_episodes (
        job_id TEXT PRIMARY KEY REFERENCES queue_jobs(id),
        series_id TEXT NOT NULL REFERENCES story_series(id),
        part INTEGER NOT NULL CHECK (part BETWEEN 1 AND 4),
        UNIQUE (series_id, part));
"""


def migrate(db):
    """Arcs created before chat support are narrated."""
    if "format" not in {r[1] for r in db.execute("PRAGMA table_info(story_series)")}:
        db.execute("ALTER TABLE story_series ADD COLUMN format TEXT NOT NULL DEFAULT 'narrated'")


BLOCKING = {"failed", "needs_attention", "rejected", "uploading", "upload_uncertain"}


def info(queue, job_id):
    with queue.connect() as db:
        return db.execute(
            "SELECT s.*, e.part FROM series_episodes e JOIN story_series s ON s.id=e.series_id WHERE e.job_id=?",
            (job_id,),
        ).fetchone()


def members(queue, identity):
    with queue.connect() as db:
        return _members(db, identity)


def _members(db, identity):
    return db.execute(
        "SELECT q.*, e.part AS series_part FROM series_episodes e JOIN queue_jobs q ON q.id=e.job_id "
        "WHERE e.series_id=? ORDER BY e.part",
        (identity,),
    ).fetchall()


def link(queue, jobs, story_format="narrated", topic=None):
    """Bind untouched queued jobs in one transaction; keep their original topics in events."""
    if len(jobs) not in (3, 4) or len(set(jobs)) != len(jobs):
        raise ValueError("A series needs 3 or 4 distinct queued jobs.")
    if story_format not in ("narrated", "chat"):
        raise ValueError("A series is narrated or chat.")
    identity, now = uuid4().hex, datetime.now(timezone.utc).isoformat(timespec="seconds")
    with queue.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = [
            db.execute("SELECT * FROM queue_jobs WHERE id=?", (job,)).fetchone() for job in jobs
        ]
        if any(
            not row
            or row["stage"] != "queued"
            or row["story_path"]
            or row["output"]
            or row["youtube_id"]
            for row in rows
        ):
            raise ValueError("Only untouched queued jobs can join a series.")
        if len({row["tts_provider"] for row in rows}) != 1:
            raise ValueError("A series must use one narration provider.")
        if any(
            db.execute("SELECT 1 FROM series_episodes WHERE job_id=?", (job,)).fetchone()
            for job in jobs
        ):
            raise ValueError("Job already belongs to a series.")
        topic = topic or rows[0]["topic"]
        db.execute(
            "INSERT INTO story_series (id,topic,tts_provider,part_count,created_at,format) "
            "VALUES (?,?,?,?,?,?)",
            (identity, topic, rows[0]["tts_provider"], len(jobs), now, story_format),
        )
        for part, row in enumerate(rows, 1):
            db.execute("INSERT INTO series_episodes VALUES (?,?,?)", (row["id"], identity, part))
            db.execute(
                "UPDATE queue_jobs SET topic=?,updated_at=? WHERE id=?", (topic, now, row["id"])
            )
            queue._event(
                db,
                row["id"],
                "queued",
                f"{story_format} series {identity} part {part}/{len(jobs)}; "
                f"original premise: {row['topic']}",
            )
    return identity


def can_process(queue, job_id):
    series = info(queue, job_id)
    return not series or not any(row["stage"] in BLOCKING for row in members(queue, series["id"]))


def draft_job(queue, job, drafter):
    series = info(queue, job["id"])
    if series["manifest_path"]:
        manifest_path = Path(series["manifest_path"])
        manifest = read_manifest(manifest_path, series["id"], series["part_count"], series["topic"])
        if manifest["format"] != series["format"]:
            raise ValueError("Saved series format differs from its queue reservation.")
        path = manifest_path.parent / f"part_{series['part']:02d}.json"
        return queue.move(
            job["id"],
            ("drafting",),
            "drafted",
            "reused complete series draft",
            story_path=str(path),
            error=None,
        )
    if series["part"] != 1:
        raise ValueError("Draft Part 1's complete arc before processing a continuation.")
    gender = queue.assign_gender("series", series["id"])
    path = Path(
        drafter(
            series["topic"],
            parts=series["part_count"],
            identity=series["id"],
            gender=gender,
            story_format=series["format"],
            provider=series["tts_provider"],
        )
    ).resolve()
    manifest = read_manifest(path, series["id"], series["part_count"], series["topic"])
    if manifest["protagonist_gender"] != gender:
        raise ValueError("Series did not respect assigned protagonist gender.")
    if manifest["format"] != series["format"]:
        raise ValueError("Series did not respect its assigned format.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with queue.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = _members(db, series["id"])
        if len(rows) != series["part_count"] or any(
            row["stage"] not in ("queued", "drafting") for row in rows
        ):
            raise ValueError("Series membership changed while drafting.")
        db.execute(
            "UPDATE story_series SET title=?,manifest_path=? WHERE id=?",
            (manifest["title"], str(path), series["id"]),
        )
        for row in rows:
            saved = str(path.parent / f"part_{row['series_part']:02d}.json")
            db.execute(
                "UPDATE queue_jobs SET stage='drafted',story_path=?,error=NULL,updated_at=? WHERE id=?",
                (saved, now, row["id"]),
            )
            queue._event(
                db,
                row["id"],
                "drafted",
                "complete series draft/editorial pass saved; awaiting narration",
            )
    return queue.get(job["id"])


def check_story(queue, job, story):
    series = info(queue, job["id"])
    if not series:
        if "series" in story:
            raise ValueError("Queue the complete series before using a serial draft.")
        return
    if not series["manifest_path"]:
        raise ValueError("Series has no admitted complete draft.")
    manifest = read_manifest(
        series["manifest_path"], series["id"], series["part_count"], series["topic"]
    )
    if story != episode_story(manifest, series["part"]):
        raise ValueError("Continuation does not match its admitted series draft.")


def validate_outputs(series, rows):
    """All parts must retain the same script, narrator and actual provider voice."""
    if len(rows) != series["part_count"] or not series["manifest_path"]:
        raise ValueError("Incomplete series membership or draft.")
    manifest = read_manifest(
        series["manifest_path"], series["id"], series["part_count"], series["topic"]
    )
    voices = set()
    for row in rows:
        output = Path(row["output"] or "")
        if not output.is_file():
            raise ValueError("Every series part must be rendered before Part 1 is scheduled.")
        metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        if validate_story(metadata["story"]) != episode_story(manifest, row["series_part"]):
            raise ValueError("Series output does not match its complete draft.")
        if (
            metadata.get("tts_provider") != series["tts_provider"]
            or row["tts_provider"] != series["tts_provider"]
        ):
            raise ValueError("Series narration provider changed.")
        audio = json.loads(
            Path(metadata["narration"]).with_suffix(".json").read_text(encoding="utf-8")
        )
        voice = audio.get("voice")
        if not isinstance(voice, str) or not voice:
            raise ValueError("Series narration is missing its actual voice identity.")
        voices.add(voice)
    if len(voices) != 1:
        raise ValueError("A series must keep the same voice in every part.")


def guard_schedule(db, job_id, publish_at, private_only, preview_slots=None):
    series = db.execute(
        "SELECT s.*,e.part FROM series_episodes e JOIN story_series s ON s.id=e.series_id WHERE e.job_id=?",
        (job_id,),
    ).fetchone()
    if not series:
        return
    rows = _members(db, series["id"])
    if any(row["stage"] not in ("approved", "scheduled", "uploaded_private") for row in rows):
        raise ValueError("Render and approve the entire series before scheduling any part.")
    validate_outputs(series, rows)
    confirmed = "uploaded_private" if private_only else "scheduled"
    for previous in rows[: series["part"] - 1]:
        preview = (
            (preview_slots or {}).get(previous["id"]) if previous["stage"] == "approved" else None
        )
        if not preview and (
            previous["stage"] != confirmed
            or not re.fullmatch(r"[A-Za-z0-9_-]{11}", previous["youtube_id"] or "")
        ):
            raise ValueError("Schedule earlier parts successfully before their continuation.")
        if not private_only:
            earlier = datetime.fromisoformat(
                (preview or previous["scheduled_at"]).replace("Z", "+00:00")
            )
            current = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            if earlier >= current:
                raise ValueError("Series parts must publish in story order.")
    for row in rows:
        if row["youtube_id"] and row["stage"] != confirmed:
            raise ValueError("Do not mix public and private-only uploads within a series.")
