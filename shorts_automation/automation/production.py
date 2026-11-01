"""One bounded production pass. Windows invokes this every 30 minutes.

Automatic jobs are permanently bound to Eastern publishing slots. This module
never auto-retries an uncertain upload, never changes manually enqueued jobs,
and never substitutes a paid service. See docs/PRODUCTION.md.
"""

import argparse
import hashlib
import itertools
import json
import math
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from config import (
    BACKGROUNDS_DIR,
    MAX_DURATION_SECONDS,
    NARRATION_TAIL_SECONDS,
    OUTPUT_DIR,
    SECRETS_DIR,
    STORAGE_DIR,
    TEMP_DIR,
)
from shorts_automation.automation import series_queue
from shorts_automation.automation.orchestrator import (
    JobQueue,
    RunnerBusy,
    _now,
    process_one,
    runner_lock,
)
from shorts_automation.state.source_lock import synchronized
from shorts_automation.state.usage_store import SEGMENT_POLICY, UsageStore, segment_range

CONFIG_PATH = SECRETS_DIR / "production.json"
HEALTH_PATH = STORAGE_DIR / "production_health.json"
SUPERSEDED_STYLE = "Superseded by Minecraft parkour segment workflow"
SUPERSEDED_STORY = "Superseded by approved horror stories and narrator voices"
GAME_TITLE_TERMS = (
    "minecraft",
    "minetest",
    "nodecore",
    "mineclone",
    "luanti",
    "supertuxkart",
    "xonotic",
    "openarena",
    "veloren",
    "supertux",
    "0 a.d.",
)


def load_config(path=CONFIG_PATH):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    ZoneInfo(config["timezone"])
    if config["tts_provider"] != "kokoro":
        raise ValueError("Configured voice provider must be the local kokoro model.")
    for name in ("enabled", "publish_enabled"):
        if type(config[name]) is not bool:
            raise ValueError(f"{name} must be true or false.")
    for name in ("private_upload_enabled", "telegram_notify_enabled"):
        config.setdefault(name, False)
        if type(config[name]) is not bool:
            raise ValueError(f"{name} must be true or false.")
    if config["publish_enabled"] and config["private_upload_enabled"]:
        raise ValueError("Choose public scheduling or private-only uploads, never both.")
    config.setdefault("minimum_scheduled_videos", 3)
    config.setdefault("story_format", "standalone")
    config.setdefault("series_standalones_between", 3)
    config.setdefault("series_min_lead_hours", 4)
    config.setdefault("series_parts", [3, 4])
    config.setdefault("series_formats", ["narrated", "chat"])
    if config["story_format"] not in ("standalone", "mixed", "series"):
        raise ValueError("Choose standalone, mixed or series story format.")
    if (
        not isinstance(config["series_formats"], list)
        or not config["series_formats"]
        or any(f not in ("narrated", "chat") for f in config["series_formats"])
        or len(set(config["series_formats"])) != len(config["series_formats"])
    ):
        raise ValueError("series_formats must contain narrated, chat, or both without duplicates.")
    if (
        not isinstance(config["series_parts"], list)
        or not config["series_parts"]
        or any(type(n) is not int or n not in (3, 4) for n in config["series_parts"])
        or len(set(config["series_parts"])) != len(config["series_parts"])
    ):
        raise ValueError("series_parts must contain 3, 4, or both without duplicates.")
    for name, low, high in (
        ("minimum_scheduled_videos", 1, 12),
        ("series_standalones_between", 1, 12),
        ("series_min_lead_hours", 2, 24),
        ("lookahead_hours", 1, 72),
        ("max_jobs_per_pass", 1, 3),
        ("min_free_disk_gb", 1, 100),
        ("retain_temp_days", 1, 30),
        ("retain_logs_days", 1, 365),
    ):
        if type(config[name]) is not int or not low <= config[name] <= high:
            raise ValueError(f"Invalid {name}.")
    if len(config["slots"]) != 3 or len(set(config["slots"])) != 3:
        raise ValueError("Configure exactly three distinct daily publishing slots.")
    for value in config["slots"]:
        parsed = time.fromisoformat(value)
        if parsed.second or parsed.microsecond or parsed.tzinfo:
            raise ValueError("Publishing slots must be local hours and minutes.")
    if not config["background_queries"] or not all(
        isinstance(q, str) and 1 <= len(q) <= 200 for q in config["background_queries"]
    ):
        raise ValueError("Configure at least one bounded background search query.")
    if not config["background_licenses"] or not set(config["background_licenses"]) <= {
        "CC0",
        "CC BY 3.0",
        "CC BY 4.0",
        "Creator commercial permission",
        "User-authorized creator footage",
    }:
        raise ValueError(
            "Production requires approved Creative Commons or creator-permission metadata."
        )
    if config.get("footage_discovery", "fixed") not in (
        "antigravity",
        "creator_downloads",
        "fixed",
    ):
        raise ValueError("Unknown footage discovery method.")
    return config


def future_slots(config, now):
    """Channel wall times -> UTC, within the planning horizon and 45-minute lead."""
    if now.tzinfo is None:
        raise ValueError("Clock must include a timezone.")
    local = now.astimezone(ZoneInfo(config["timezone"]))
    end = now + timedelta(hours=config["lookahead_hours"])
    for day in range(5):
        for value in sorted(config["slots"]):
            target = datetime.combine(
                local.date() + timedelta(days=day), time.fromisoformat(value), local.tzinfo
            )
            instant = target.astimezone(timezone.utc)
            if now + timedelta(minutes=45) <= instant <= end:
                yield instant.strftime("%Y-%m-%dT%H:%M:%SZ")


SETTINGS = (
    "a night-shift hospital",
    "an empty motel",
    "a remote gas station",
    "an apartment elevator",
    "a small-town library",
    "a highway rest stop",
    "a closed supermarket",
    "a lighthouse",
    "a suburban kitchen",
    "a rural train station",
    "an airport baggage room",
    "a school after dark",
)
OBJECTS = (
    "a voice message",
    "a handwritten note",
    "a security recording",
    "a photograph",
    "a delivery receipt",
    "a missing-person poster",
    "a radio transmission",
    "a spare key",
    "a child drawing",
    "a work schedule",
    "a locked suitcase",
    "a broken clock",
)
ANOMALIES = (
    "predicts what the narrator will do next",
    "contains evidence of a day that never happened",
    "reveals someone has been living nearby unseen",
    "changes whenever nobody watches",
    "appears in two places at the same time",
    "remembers a person everyone else forgot",
    "warns against a seemingly harmless routine",
    "belongs to someone who has not arrived yet",
    "repeats a detail from the narrator childhood",
    "answers a question nobody said aloud",
)


# One learnable rule per threat gives arcs a mechanism to test and pay off,
# and makes premises differ in how the horror works, not only in props.
THREAT_RULES = (
    "it can only move while nobody is looking at it",
    "it copies the voice of whoever the narrator trusts most",
    "it can only enter where it has been invited",
    "it gets closer each time the narrator ignores it",
    "it takes one small thing every time it is seen",
    "it knows anything the narrator writes down or says aloud",
    "it can only reach people who are alone",
    "it repeats the same night with one detail changed",
    "it is hiding among people the narrator already knows",
    "it cannot cross a line the narrator has to keep unbroken",
)


def fresh_topic(slot, existing):
    combinations = list(itertools.product(SETTINGS, OBJECTS, ANOMALIES))
    random.Random(hashlib.sha256(slot.encode()).digest()).shuffle(combinations)
    rules = random.Random(hashlib.sha256(("rule:" + slot).encode()).digest())
    for setting, obj, anomaly in combinations:
        premise = (
            f"In {setting}, {obj} {anomaly}. The threat follows one rule: "
            f"{rules.choice(THREAT_RULES)}. Invent a fresh first-person narrator, one clear "
            "threat and a frightening payoff consistent with the setup and that rule."
        )
        if premise.casefold() not in existing:
            return premise
    raise RuntimeError("Original premise pool exhausted; expand the settings/object/anomaly lists.")


# Drama premises for chat arcs. Relationships stay gender-neutral: the drafter
# assigns contact genders that the configured distinct voices can cover.
RELATIONSHIPS = (
    "my partner of three years",
    "the person I am engaged to",
    "my best friend since high school",
    "my roommate",
    "my older sibling",
    "my manager",
    "my partner's best friend",
    "my business partner",
    "my future in-law",
    "my ex who still has a key",
    "a stranger who texts the wrong number",
    "my next-door neighbor",
)
DISCOVERIES = (
    "a message clearly meant for someone else",
    "a shared location that does not match their story",
    "a receipt for an expensive gift I never received",
    "a second phone hidden in a coat pocket",
    "an anniversary dinner booked under someone else's name",
    "a mutual friend who slips up over text",
    "a voice note sent by accident",
    "a group chat I was never meant to see",
    "a hotel confirmation forwarded to the wrong inbox",
    "a lie about working late that a coworker exposes",
)
PAYOFFS = (
    "I already knew and calmly let them dig deeper",
    "the person helping me has a secret of their own",
    "I expose everything at the worst possible moment for them",
    "the evidence turns out to point at someone unexpected",
    "my quiet plan costs them exactly what they cared about most",
    "the wrong-number stranger becomes the key witness",
    "they try to flip the blame and it backfires",
    "the other person they were seeing teams up with me",
)


def fresh_chat_topic(slot, existing):
    combinations = list(itertools.product(RELATIONSHIPS, DISCOVERIES, PAYOFFS))
    random.Random(hashlib.sha256(("chat:" + slot).encode()).digest()).shuffle(combinations)
    for relationship, discovery, payoff in combinations:
        premise = (
            f"Texting with {relationship}, it starts with {discovery}. Direction for the payoff: "
            f"{payoff}. Invent a fresh first-person protagonist, a concrete betrayal and a "
            "satisfying, legal revenge."
        )
        if premise.casefold() not in existing:
            return premise
    raise RuntimeError("Drama premise pool exhausted; expand the relationship/discovery lists.")


def initialize(queue):
    with queue.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS production_slots (
                publish_at TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE REFERENCES queue_jobs(id),
                created_at TEXT NOT NULL);
        """)


def plan(queue, config, now):
    """Create each slot and its job atomically, including after crashes/restarts."""
    initialize(queue)
    with queue.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing_topics = {r[0].casefold() for r in db.execute("SELECT topic FROM queue_jobs")}
        # Respect slots already booked by explicit/manual scheduling too.
        from shorts_automation.publishing.youtube_uploader import _scheduled_instant

        booked = {
            _scheduled_instant(r[0])
            for r in db.execute(
                "SELECT scheduled_at FROM queue_jobs WHERE scheduled_at IS NOT NULL"
            )
        }
        for slot in future_slots(config, now):
            previous = db.execute(
                "SELECT q.id,q.stage,q.review_note FROM production_slots p "
                "JOIN queue_jobs q ON q.id=p.job_id WHERE p.publish_at=?",
                (slot,),
            ).fetchone()
            replace = (
                previous
                and previous["stage"] == "rejected"
                and previous["review_note"] in (SUPERSEDED_STYLE, SUPERSEDED_STORY)
            )
            if previous and not replace:
                continue
            if _scheduled_instant(slot) in booked:
                continue
            topic, job = fresh_topic(slot, existing_topics), uuid4().hex
            db.execute(
                "INSERT INTO queue_jobs (id,topic,tts_provider,stage,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (job, topic, config["tts_provider"], "queued", _now(), _now()),
            )
            if replace:
                db.execute(
                    "UPDATE production_slots SET job_id=?,created_at=? WHERE publish_at=?",
                    (job, _now(), slot),
                )
            else:
                db.execute("INSERT INTO production_slots VALUES (?,?,?)", (slot, job, _now()))
            detail = f"automatic production for {slot}" + (
                f"; replaces {previous['id']} after format change" if replace else ""
            )
            queue._event(db, job, "queued", detail)
            existing_topics.add(topic.casefold())
    return owned_jobs(queue)


def owned_jobs(queue):
    initialize(queue)
    with queue.connect() as db:
        return db.execute(
            "SELECT q.*, p.publish_at FROM production_slots p JOIN queue_jobs q ON q.id=p.job_id "
            "ORDER BY p.publish_at"
        ).fetchall()


def holds_releases(queue, series, slots, now):
    """Whether a blocked arc still keeps later jobs waiting behind it.

    Only an open arc can still release in order. Past arcs and arcs with a failed or
    rejected part never can, so they must not stall every later release.
    """
    rows = series_queue.members(queue, series["id"])
    if any(row["stage"] in ("failed", "rejected") for row in rows):
        return False
    if not any(
        datetime.fromisoformat(slots[row["id"]].replace("Z", "+00:00")) > now
        for row in rows
        if row["id"] in slots
    ):
        return False
    return any(row["stage"] in series_queue.BLOCKING for row in rows)


def next_series_format(queue, config):
    """Alternate arc formats in configured order, continuing from the latest arc."""
    if config.get("story_format") != "series":
        return "narrated"
    formats = config.get("series_formats", ["narrated", "chat"])
    with queue.connect() as db:
        last = db.execute(
            "SELECT format FROM story_series ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    if not last or last[0] not in formats:
        return formats[0]
    return formats[(formats.index(last[0]) + 1) % len(formats)]


def link_arc(queue, config, now, rows, first):
    """Bind the arc to consecutive untouched slots starting at `first`, if they exist."""
    with queue.connect() as db:
        count = db.execute("SELECT COUNT(*) FROM story_series").fetchone()[0]
    lengths = config.get("series_parts", [3, 4])
    preferred = lengths[count % len(lengths)]
    slots = list(future_slots(config, now))
    if first["publish_at"] not in slots:
        return None
    start = slots.index(first["publish_at"])
    by_slot = {row["publish_at"]: row for row in rows}
    for total in dict.fromkeys((preferred, *lengths)):
        window = slots[start : start + total]
        if len(window) != total:
            continue
        jobs = [by_slot.get(slot) for slot in window]
        if any(
            not job
            or job["stage"] != "queued"
            or job["story_path"]
            or job["tts_provider"] != first["tts_provider"]
            or series_queue.info(queue, job["id"])
            for job in jobs
        ):
            continue
        story_format, topic = next_series_format(queue, config), None
        if story_format == "chat":
            with queue.connect() as db:
                existing = {
                    r[0].casefold()
                    for r in db.execute(
                        "SELECT topic FROM queue_jobs UNION SELECT topic FROM story_series"
                    )
                }
            topic = fresh_chat_topic(first["publish_at"], existing)
        return series_queue.link(queue, [job["id"] for job in jobs], story_format, topic)
    return None


def assign_series_only(queue, config, now):
    """Every automatic release belongs to an arc; formats alternate between arcs.

    Already drafted standalone jobs keep their slots. Slots too close to prepare a
    complete arc are skipped rather than filled with a standalone.
    """
    rows = owned_jobs(queue)
    slots = {row["id"]: row["publish_at"] for row in rows}
    for row in rows:
        series = series_queue.info(queue, row["id"])
        if series and holds_releases(queue, series, slots, now):
            return None
    lead = now + timedelta(hours=config.get("series_min_lead_hours", 4))
    for row in rows:
        if row["stage"] not in ("queued", "drafted") or not series_queue.can_process(
            queue, row["id"]
        ):
            continue
        existing = series_queue.info(queue, row["id"])
        if existing:
            return existing["id"]
        if row["stage"] != "queued" or row["story_path"]:
            continue
        if datetime.fromisoformat(row["publish_at"].replace("Z", "+00:00")) < lead:
            continue
        identity = link_arc(queue, config, now, rows, row)
        if identity:
            return identity
    return None


def assign_series(queue, config, now):
    """Mix one coherent arc into untouched consecutive slots after standalone releases."""
    if config.get("story_format") == "series":
        return assign_series_only(queue, config, now)
    if config.get("story_format") != "mixed" or not config["publish_enabled"]:
        return None
    buffer = scheduled_buffer(queue, config, now)
    if buffer:
        if buffer["future_scheduled"] < buffer["minimum"]:
            return None
        if buffer["next_release"] and datetime.fromisoformat(
            buffer["next_release"]
        ) < now + timedelta(hours=config.get("series_min_lead_hours", 4)):
            return None
    rows = owned_jobs(queue)
    slots = {row["id"]: row["publish_at"] for row in rows}
    for row in rows:
        series = series_queue.info(queue, row["id"])
        if series and holds_releases(queue, series, slots, now):
            return None
    candidates = [
        row
        for row in rows
        if row["stage"] in ("queued", "drafted") and series_queue.can_process(queue, row["id"])
    ]
    if not candidates:
        return None
    first = candidates[0]
    existing = series_queue.info(queue, first["id"])
    if existing:
        return existing["id"]
    if first["stage"] != "queued" or first["story_path"]:
        return None
    first_instant = datetime.fromisoformat(first["publish_at"].replace("Z", "+00:00"))
    if first_instant < now + timedelta(hours=config.get("series_min_lead_hours", 4)):
        return None
    standalones = 0
    for previous in reversed([row for row in rows if row["publish_at"] < first["publish_at"]]):
        if series_queue.info(queue, previous["id"]):
            break
        if (
            previous["stage"] == "scheduled"
            and previous["youtube_id"]
            and previous["scheduled_at"]
            and datetime.fromisoformat(previous["scheduled_at"].replace("Z", "+00:00"))
            < first_instant
        ):
            standalones += 1
        else:
            break
    if standalones < config.get("series_standalones_between", 3):
        return None
    return link_arc(queue, config, now, rows, first)


def current_footage_format(job):
    metadata = json.loads(
        Path(job["output"]).with_suffix(".metadata.json").read_text(encoding="utf-8")
    )
    source = metadata.get("background_source", {})
    title = source.get("title", "").casefold()
    return (
        "minecraft" in title
        and "parkour" in title
        and source.get("segment_policy") == SEGMENT_POLICY
        and segment_range(source) is not None
    )


def current_story_format(job, config):
    if config.get("story_revision") != "horror-v2":
        return True
    metadata = json.loads(
        Path(job["output"]).with_suffix(".metadata.json").read_text(encoding="utf-8")
    )
    story = metadata.get("story", {})
    if story.get("format") == "chat":
        from shorts_automation.stories.draft_story import CHAT_REVISION, validate_story
        from shorts_automation.stories.tts_engine import chat_voice_identity

        audio = json.loads(
            Path(metadata["narration"]).with_suffix(".json").read_text(encoding="utf-8")
        )
        try:
            expected = chat_voice_identity(validate_story(story), metadata["tts_provider"])
        except RuntimeError as error:
            # A voice settings problem needs inspection, not automatic retirement.
            raise ValueError(str(error)) from error
        return story.get("story_revision") == CHAT_REVISION and audio.get("voice") == expected
    if story.get("story_revision") != "horror-v2" or story.get("protagonist_gender") not in (
        "female",
        "male",
    ):
        return False
    if story.get("narrator_gender") != story["protagonist_gender"]:
        return False
    if story["protagonist_gender"] == "female":
        from shorts_automation.stories.tts_engine import select_story_voice

        audio = json.loads(
            Path(metadata["narration"]).with_suffix(".json").read_text(encoding="utf-8")
        )
        return audio.get("voice") == select_story_voice(story, metadata["tts_provider"])
    return True


def retire_outdated_previews(queue, config):
    """Retain old media/history, but do not let it fill the new-format backlog."""
    retired = []
    if config.get("footage_discovery") != "creator_downloads":
        return retired
    for job in owned_jobs(queue):
        if job["stage"] != "rendered":
            continue
        try:
            footage_current = current_footage_format(job)
            current = footage_current and current_story_format(job, config)
        except (OSError, ValueError, TypeError):
            queue.move(
                job["id"],
                ("rendered",),
                "needs_attention",
                "Prepared output metadata cannot be inspected",
                error="Missing or unreadable media metadata.",
            )
            continue
        if not current:
            queue.review(
                job["id"], "rejected", SUPERSEDED_STORY if footage_current else SUPERSEDED_STYLE
            )
            retired.append(job["id"][:8])
    return retired


def cached_background(config):
    """Consume valid stock replenished by AGY regardless of its search-query wording."""
    from shorts_automation.footage.gameplay_fetcher import cached_clips

    queries = set()
    for sidecar in sorted(BACKGROUNDS_DIR.glob("commons_*.source.json")):
        try:
            source = json.loads(sidecar.read_text(encoding="utf-8"))
            if (
                source.get("query")
                and source.get("license") in config["background_licenses"]
                and any(term in source.get("title", "").casefold() for term in GAME_TITLE_TERMS)
            ):
                queries.add(source["query"])
        except (OSError, ValueError):
            continue
    for query in sorted(queries):
        for path in cached_clips(query, 58, allowed_licenses=set(config["background_licenses"])):
            return path
    return None


@synchronized
def render_automatic(config, query_offset=0, **kwargs):
    """Find eligible footage before consuming TTS quota; no unrelated fallback."""
    from shorts_automation.footage.gameplay_fetcher import get_background_clip
    from shorts_automation.rendering.pipeline import run_pipeline

    if config.get("footage_discovery") == "creator_downloads":
        from shorts_automation.footage.creator_footage import get_creator_background

        footage = get_creator_background(config)
        return run_pipeline(**{**kwargs, "background_file": footage})
    footage = cached_background(config)
    if footage:
        return run_pipeline(**{**kwargs, "background_file": footage})
    seed = Path(kwargs["story_file"]).stem
    queries = list(config["background_queries"])
    if config.get("footage_discovery") == "antigravity":
        from legacy.replenish_clips import DEFAULT_AGY_MODEL, ask_agy_for_queries

        queries = ask_agy_for_queries(
            model=config.get("antigravity_model", DEFAULT_AGY_MODEL),
            count=4,
            prompt_hint="Actual gameplay from Minetest, NodeCore, MineClone, Luanti, SuperTuxKart or Xonotic; "
            "prefer CC0 or CC BY material. Queries must identify games, not generic atmospheric footage.",
        )
    else:
        primary, alternatives = queries[0], queries[1:]
        random.Random(seed).shuffle(alternatives)
        queries = [primary, *alternatives]
    query_offset %= len(queries)
    queries = queries[query_offset:] + queries[:query_offset]
    for query in queries[:2]:
        try:
            footage, _ = get_background_clip(
                57.2, query, allowed_licenses=set(config["background_licenses"])
            )
            source = json.loads(footage.with_suffix(".source.json").read_text(encoding="utf-8"))
            if not any(term in source.get("title", "").casefold() for term in GAME_TITLE_TERMS):
                raise ValueError("Search returned footage outside the configured gameplay format.")
        except Exception as error:
            print(f"[source] {query}: {type(error).__name__}; trying next configured query")
            continue
        return run_pipeline(**{**kwargs, "background_file": footage})
    raise RuntimeError("No eligible background in bounded source search; saved draft retained.")


def validate_output(job, allowed_licenses):
    """Reject unreadable, mistimed or incomplete output before automated approval."""
    output = Path(job["output"]).resolve(strict=True)
    if output.parent != OUTPUT_DIR.resolve():
        raise ValueError("Automatic output must be in the configured output directory.")
    metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    from shorts_automation.stories.draft_story import validate_story

    validate_story(metadata["story"])
    if metadata.get("tts_provider") != job["tts_provider"]:
        raise ValueError("Output voice provider does not match the job.")
    source = metadata["background_source"]
    if not any(term in source.get("title", "").casefold() for term in GAME_TITLE_TERMS):
        raise ValueError("Output source is outside the configured gameplay format.")
    if source.get("license") not in allowed_licenses or not all(
        source.get(k) for k in ("source_url", "author", "license_url")
    ):
        raise ValueError("Output lacks eligible source attribution.")
    if not output.with_suffix(".credits.txt").is_file():
        raise ValueError("Missing source credit sidecar.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    data = json.loads(probe.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
    duration = float(data["format"]["duration"])
    if (
        (video["width"], video["height"]) != (1080, 1920)
        or not math.isfinite(duration)
        or not 0 < duration <= MAX_DURATION_SECONDS + 0.15
    ):
        raise ValueError("Output dimensions or duration are outside production limits.")
    narration_duration = float(metadata["narration_duration"])
    if (
        not math.isfinite(narration_duration)
        or narration_duration <= 0
        or abs(duration - (narration_duration + NARRATION_TAIL_SECONDS)) > 0.2
    ):
        raise ValueError("Output duration does not match narration.")
    if not audio.get("codec_name"):
        raise ValueError("No valid output audio.")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
        capture_output=True,
        check=True,
        timeout=120,
    )
    return metadata


def cleanup(config, now):
    """Remove only old generated caption directories and logs, never videos/credentials."""
    removed = 0
    for parent, pattern, days in (
        (TEMP_DIR, "captions_*", config["retain_temp_days"]),
        (STORAGE_DIR / "logs", "production_*.log", config["retain_logs_days"]),
    ):
        root = parent.resolve()
        for path in parent.glob(pattern):
            if path.is_symlink() or path.resolve().parent != root:
                continue
            if path.stat().st_mtime >= (now - timedelta(days=days)).timestamp():
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed += 1
            except OSError:
                # Windows may keep an old preview directory open. Cleanup must
                # not invalidate a completed production/upload pass.
                print("[cleanup] Skipped a locked generated file/directory.")
    return removed


def write_health(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".tmp")
    staged.write_text(json.dumps(data, indent=2), encoding="utf-8")
    staged.replace(path)


def scheduled_buffer(queue, config, now):
    """Count confirmed future public uploads, including explicitly scheduled manual work."""
    minimum = config.get("minimum_scheduled_videos", 0)
    if not config["publish_enabled"] or not minimum:
        return None
    releases = {}
    for job in queue.list("scheduled"):
        video_id = job["youtube_id"]
        if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue
        if not job["scheduled_at"]:
            continue
        instant = datetime.fromisoformat(job["scheduled_at"].replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("Scheduled release must include a timezone.")
        if instant > now:
            releases[video_id] = min(instant, releases.get(video_id, instant))
    count, target = len(releases), minimum + 1
    return {
        "minimum": minimum,
        "target": target,
        "future_scheduled": count,
        "deficit": max(0, minimum - count),
        "status": "below_minimum"
        if count < minimum
        else "replenishing"
        if count < target
        else "ok",
        "next_release": min(releases.values()).astimezone(timezone.utc).isoformat()
        if releases
        else None,
        "checked_at": now.isoformat(),
    }


def cycle(
    config,
    queue=None,
    usage=None,
    drafter=None,
    renderer=None,
    validator=None,
    service_factory=None,
    now=None,
    lock_path=None,
    health_path=HEALTH_PATH,
    notification_sender=None,
    series_drafter=None,
):
    supplied_now = now

    def clock():
        return supplied_now if supplied_now is not None else datetime.now(timezone.utc)

    now = clock()
    queue = queue or JobQueue()
    usage = usage or UsageStore(queue.path)
    from shorts_automation.publishing.youtube_uploader import get_authenticated_service
    from shorts_automation.stories.draft_story import draft

    drafter = drafter or draft

    def default_renderer(**kwargs):
        # A failed source search must try different queries on the next pass,
        # while retaining the draft and cached narration.
        with queue.connect() as db:
            row = db.execute(
                "SELECT attempts FROM queue_jobs WHERE story_path=?", (str(kwargs["story_file"]),)
            ).fetchone()
        return render_automatic(config, query_offset=2 * (row[0] if row else 0), **kwargs)

    renderer = renderer or default_renderer
    validator = validator or validate_output
    service_factory = service_factory or get_authenticated_service
    health = {
        "at": now.isoformat(),
        "status": "ok",
        "processed": [],
        "published": [],
        "problems": [],
        "historical_failed_jobs": 0,
    }
    youtube = None
    upload_attempted = set()

    def may_prepare(identity):
        """Series-only production never drafts a new standalone story."""
        if config.get("story_format") != "series" or series_queue.info(queue, identity):
            return True
        return queue.get(identity)["stage"] == "drafted"

    def advance_series(series):
        nonlocal youtube
        rows = series_queue.members(queue, series["id"])
        pending = [row for row in rows if row["stage"] in ("rendered", "approved")]
        if not pending or any(
            row["stage"] not in ("rendered", "approved", "scheduled", "uploaded_private")
            for row in rows
        ):
            return
        if any(row["id"] in upload_attempted for row in pending):
            return
        buffer = scheduled_buffer(queue, config, clock())
        started = any(row["youtube_id"] for row in rows)
        if buffer and buffer["future_scheduled"] >= buffer["target"] and not started:
            return
        try:
            series_queue.validate_outputs(series, rows)
            for row in pending:
                validator(row, set(config["background_licenses"]))
                if config.get("footage_discovery") == "creator_downloads" and not (
                    current_footage_format(row) and current_story_format(row, config)
                ):
                    raise ValueError("Outdated series format")
        except Exception:
            row = pending[0]
            queue.move(
                row["id"],
                (row["stage"],),
                "needs_attention",
                "Complete series media/continuity/voice validation failed",
                error="Inspect the full arc before publication.",
            )
            health["problems"].append(series["id"][:8] + ": series validation failed")
            return
        if not uploads_enabled:
            return
        for row in pending:
            if row["stage"] == "rendered":
                queue.review(row["id"], "approved", "Complete series media and voice checks passed")
        # Finish this prepared arc even if its uploads temporarily exceed the
        # four-video target. Do not spend on another arc while the reserve is full.
        for row in pending:
            assigned = next(
                job["publish_at"] for job in owned_jobs(queue) if job["id"] == row["id"]
            )
            private_only = config.get("private_upload_enabled", False)
            if private_only and datetime.fromisoformat(assigned.replace("Z", "+00:00")) > clock():
                return
            upload_attempted.add(row["id"])
            try:
                youtube = youtube or service_factory()
                options = {"private_only": True} if private_only else {"publish_at": assigned}
                uploaded = queue.schedule_job(row["id"], youtube, **options)
                health["published"].append(uploaded["id"][:8])
            except Exception as error:
                health["problems"].append(
                    series["id"][:8] + ": series upload stopped (" + type(error).__name__ + ")"
                )
                return

    def advance_ready():
        nonlocal youtube
        visited_series = set()
        jobs = owned_jobs(queue)
        slots = {row["id"]: row["publish_at"] for row in jobs}
        for job in jobs:
            series = series_queue.info(queue, job["id"])
            if series and holds_releases(queue, series, slots, clock()):
                break
            if series and any(
                row["stage"] in series_queue.BLOCKING
                for row in series_queue.members(queue, series["id"])
            ):
                # A past or failed arc can no longer release; its parts stay unpublished.
                continue
            if series:
                if series["id"] not in visited_series:
                    advance_series(series)
                    visited_series.add(series["id"])
                if any(
                    row["stage"] not in ("scheduled", "uploaded_private")
                    for row in series_queue.members(queue, series["id"])
                ):
                    break
                continue
            if job["stage"] not in ("rendered", "approved") or job["id"] in upload_attempted:
                continue
            buffer = scheduled_buffer(queue, config, clock())
            if buffer and buffer["future_scheduled"] >= buffer["target"]:
                continue
            if (
                config.get("footage_discovery") == "creator_downloads"
                and job["stage"] == "approved"
            ):
                try:
                    if not (current_footage_format(job) and current_story_format(job, config)):
                        raise ValueError("Outdated footage format")
                except (OSError, ValueError, TypeError):
                    queue.move(
                        job["id"],
                        ("approved",),
                        "needs_attention",
                        "Approved output no longer matches requested footage format",
                        error="Review the footage format before publishing.",
                    )
                    health["problems"].append(job["id"][:8] + ": outdated approved format")
                    continue
            if job["stage"] == "rendered":
                try:
                    validator(job, set(config["background_licenses"]))
                except Exception:
                    queue.move(
                        job["id"],
                        ("rendered",),
                        "needs_attention",
                        "Automatic media validation failed; inspect locally",
                        error="Output validation failed.",
                    )
                    health["problems"].append(job["id"][:8] + ": output validation failed")
                    continue
                if uploads_enabled:
                    job = dict(
                        queue.review(
                            job["id"], "approved", "Automatic production media checks passed"
                        )
                    ) | {"publish_at": job["publish_at"]}
            if job["stage"] == "approved" and uploads_enabled:
                private_only = config.get("private_upload_enabled", False)
                if (
                    private_only
                    and datetime.fromisoformat(job["publish_at"].replace("Z", "+00:00")) > clock()
                ):
                    continue
                upload_attempted.add(job["id"])
                try:
                    youtube = youtube or service_factory()
                    options = (
                        {"private_only": True}
                        if private_only
                        else {"publish_at": job["publish_at"]}
                    )
                    row = queue.schedule_job(job["id"], youtube, **options)
                    health["published"].append(row["id"][:8])
                except Exception as error:
                    health["problems"].append(
                        job["id"][:8] + ": upload/auth failed (" + type(error).__name__ + ")"
                    )

    lock_options = {"path": lock_path} if lock_path else {}
    with runner_lock(**lock_options):
        try:
            if not config["enabled"]:
                health["status"] = "paused"
                return health
            if shutil.disk_usage(STORAGE_DIR).free < config["min_free_disk_gb"] * 1024**3:
                raise RuntimeError(
                    "Free disk below production limit; no generation or upload attempted."
                )
            usage.import_outputs()
            queue.recover_interrupted(usage)
            health["retired_old_format"] = retire_outdated_previews(queue, config)
            uploads_enabled = config["publish_enabled"] or config.get(
                "private_upload_enabled", False
            )
            rows = owned_jobs(queue)
            backlog_full = not uploads_enabled and sum(
                job["stage"] == "rendered" for job in rows
            ) >= len(config["slots"])
            if not backlog_full:
                rows = plan(queue, config, now)
            cutoff = now + timedelta(minutes=45)
            include = []
            for job in rows:
                slot = datetime.fromisoformat(job["publish_at"].replace("Z", "+00:00"))
                expired = slot < (
                    now - timedelta(hours=2) if config.get("private_upload_enabled") else cutoff
                )
                if job["stage"] == "failed" and expired:
                    # A missed slot cannot be recovered by restarting the worker.
                    # Keep its queue history without failing every later pass.
                    health["historical_failed_jobs"] += 1
                elif job["stage"] in ("uploading", "upload_uncertain", "needs_attention", "failed"):
                    health["problems"].append(f"{job['id'][:8]}: {job['stage']}")
                if (
                    not backlog_full
                    and expired
                    and job["stage"] in ("queued", "drafted", "rendered", "approved")
                ):
                    queue.move(
                        job["id"],
                        (job["stage"],),
                        "failed",
                        "Publishing slot missed; no immediate-public catch-up",
                        error="Missed publishing slot. New future slots will be planned normally.",
                    )
                    health["historical_failed_jobs"] += 1
                    health["problems"].append(f"{job['id'][:8]}: missed publishing slot")
                elif job["stage"] in ("queued", "drafted"):
                    include.append(job["id"])
            if backlog_full:
                health["publishing"] = (
                    "paused; three prepared videos retained, no further generation quota used"
                )
                health["cleaned"] = cleanup(config, now)
                if health["problems"]:
                    health["status"] = "needs_attention"
                return health
            advance_ready()
            buffer = scheduled_buffer(queue, config, clock())
            needs_generation = not buffer or buffer["future_scheduled"] < buffer["target"]
            if needs_generation:
                assigned_series = assign_series(queue, config, clock())
                if assigned_series:
                    health["series_preparation"] = assigned_series[:8]
            if not needs_generation:
                health["preparation"] = "scheduled reserve full; generation and research skipped"
            if (
                needs_generation
                and config.get("footage_discovery") == "creator_downloads"
                and config.get("authorized_local_creator_source")
            ):
                from shorts_automation.footage.creator_footage import replenish_low_supply

                try:
                    health["footage_supply"] = replenish_low_supply(config, usage)
                except Exception as error:
                    health["problems"].append(
                        "footage replenishment: " + type(error).__name__ + ": " + str(error)[:160]
                    )
            processed = []
            for _ in range(config["max_jobs_per_pass"]):
                buffer = scheduled_buffer(queue, config, clock())
                if buffer and buffer["future_scheduled"] >= buffer["target"]:
                    break
                job = process_one(
                    queue,
                    usage,
                    drafter,
                    renderer,
                    exclude=processed,
                    include=[
                        identity
                        for identity in include
                        if identity not in processed
                        and series_queue.can_process(queue, identity)
                        and may_prepare(identity)
                    ][:1],
                    series_drafter=series_drafter,
                )
                if job is None:
                    break
                processed.append(job["id"])
                health["processed"].append(job["id"][:8] + ": " + job["stage"])
                if job["error"]:
                    health["problems"].append(job["id"][:8] + ": " + job["stage"])
                advance_ready()
            health["cleaned"] = cleanup(config, now)
            if config.get("telegram_notify_enabled"):
                from shorts_automation.publishing.telegram_notifier import flush_notifications

                health["notified"], pending = flush_notifications(queue, notification_sender)
                health["problems"].extend(pending)
            if config.get("private_upload_enabled"):
                health["publishing"] = "private uploads only at Eastern slots; no public publishAt"
            elif not config["publish_enabled"]:
                health["publishing"] = "disabled; rendered videos await activation"
            if health["problems"]:
                health["status"] = "needs_attention"
            return health
        except Exception as error:
            health.update(status="error", error=type(error).__name__ + ": " + str(error)[:200])
            raise
        finally:
            buffer = scheduled_buffer(queue, config, clock())
            if buffer:
                health["scheduled_buffer"] = buffer
                if config["enabled"] and buffer["deficit"]:
                    health["problems"].append(
                        f"Only {buffer['future_scheduled']} future public videos scheduled; minimum {buffer['minimum']}."
                    )
                    if health["status"] == "ok":
                        health["status"] = "needs_attention"
            write_health(health_path, health)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "status", "plan"])
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "status":
        print(
            json.dumps(
                {
                    "config": config,
                    "health": json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
                    if HEALTH_PATH.is_file()
                    else None,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "plan":
        print("\n".join(future_slots(config, datetime.now(timezone.utc))))
        return 0
    try:
        result = cycle(config)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in ("ok", "paused") else 1
    except RunnerBusy:
        print("Production/renderer already running; skipping this invocation.")
        return 0
    except Exception as error:
        print(
            "Production stopped:",
            type(error).__name__,
            "; inspect storage/production_health.json locally.",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
