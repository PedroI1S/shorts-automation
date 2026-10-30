"""Import creator-provided, publicly accessible Minecraft parkour recordings.

Only files independently verified by the public evidence broker are eligible.
No YouTube ripping, checkout, logins, paid downloads or Commons fallback.
"""

import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from config import BACKGROUNDS_DIR
from shorts_automation.footage.creator_evidence import inspect_page, read_video
from shorts_automation.footage.gameplay_fetcher import get_video_duration
from shorts_automation.state.source_lock import synchronized
from shorts_automation.state.usage_store import SEGMENT_POLICY, UsageStore

CREATOR_QUERY = "creator_minecraft_parkour"
LICENSE = "Creator commercial permission"
LOCAL_LICENSE = "User-authorized creator footage"
LOCAL_SOURCE_MAX_BYTES = 8 * 1024**3


class SourceExhausted(ValueError):
    """This recording has no unreserved full segment remaining."""


def write_metadata(path, metadata):
    staged = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        staged.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def segmented_metadata(metadata):
    """Upgrade only explicitly measured creator segments, never guess a range."""
    metadata = dict(metadata)
    if not metadata.get("segment_policy") and all(
        k in metadata
        for k in ("youtube_video_id", "segment_start", "segment_duration", "source_duration")
    ):
        metadata.update(schema=2, segment_policy=SEGMENT_POLICY)
    return metadata


def eligible_metadata(metadata, allowed_licenses):
    title = metadata.get("title", "").casefold()
    return (
        "minecraft" in title
        and "parkour" in title
        and metadata.get("query") == CREATOR_QUERY
        and metadata.get("license") in allowed_licenses
        and metadata.get("source_url")
        and metadata.get("author")
        and metadata.get("license_url")
        and metadata.get("permission_excerpt")
        and metadata.get("download_landing_url")
    )


def cached_creator_clip(allowed_licenses):
    store = UsageStore()
    for sidecar in sorted(BACKGROUNDS_DIR.glob("creator_*.source.json")):
        try:
            original = json.loads(sidecar.read_text(encoding="utf-8"))
            metadata = segmented_metadata(original)
            video = sidecar.with_name(sidecar.name.replace(".source.json", ".mp4"))
            if (
                eligible_metadata(metadata, allowed_licenses)
                and metadata.get("segment_policy") == SEGMENT_POLICY
                and video.is_file()
                and not store.source_unavailable(metadata)
                and hashlib.sha256(video.read_bytes()).hexdigest() == metadata.get("sha256")
                and get_video_duration(video) >= 58
            ):
                if metadata != original:
                    write_metadata(sidecar, metadata)
                return video
        except (OSError, ValueError):
            continue
    return None


@synchronized
def import_creator_clip(record, allowed_licenses):
    if LICENSE not in allowed_licenses:
        raise ValueError("Creator permission sources are not enabled in production configuration.")
    if (
        record.get("access_status") != "free_direct"
        or record.get("commercial_use") != "explicitly_allowed"
    ):
        raise ValueError("Source lacks verified free access and explicit reuse permission.")
    video_id = urlsplit(record["video_url"]).query.split("v=", 1)[-1].split("&")[0]
    video = read_video(video_id)
    title = video.get("title", "").casefold()
    if (
        "minecraft" not in title
        or "parkour" not in title
        or float(video.get("duration_seconds") or 0) < 65
    ):
        raise ValueError("Source is not a usable continuous Minecraft parkour recording.")
    excerpt = " ".join(record.get("permission_excerpt", "").casefold().split())
    description = " ".join(video.get("description", "").casefold().split())
    fragments = [part.strip() for part in re.split(r"\.{3}|…", excerpt) if part.strip()]
    cursor = 0
    for fragment in fragments:
        found = description.find(fragment, cursor)
        if found < 0:
            raise ValueError("Permission excerpt does not match the current creator description.")
        cursor = found + len(fragment)
    if not fragments:
        raise ValueError("Permission excerpt does not match the current creator description.")
    from shorts_automation.footage.creator_evidence import description_links

    if record["download_landing_url"] not in description_links(video.get("description", "")):
        raise ValueError("The download page is not linked from the current creator description.")
    metadata = dict(
        schema=2,
        query=CREATOR_QUERY,
        title=video["title"],
        author=video["creator"],
        source_url="https://youtu.be/" + video_id,
        youtube_video_id=video_id,
        license=LICENSE,
        license_url=record["permission_url"],
        permission_excerpt=record["permission_excerpt"],
        credit_text=record.get("credit_text", ""),
        credit_required=record.get("credit_required", True),
        download_landing_url=record["download_landing_url"],
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        publication_cleared=False,
        requires_visual_review=True,
        source_duration=video.get("duration_seconds"),
        source_width=video.get("width"),
        source_height=video.get("height"),
        source_fps=video.get("fps"),
    )
    store = UsageStore()
    start = store.next_segment_start(metadata, float(video["duration_seconds"]))
    if start is None:
        raise SourceExhausted("No unused full segment remains in this creator recording.")
    metadata.update(segment_policy=SEGMENT_POLICY, segment_start=start, segment_duration=60)
    page = inspect_page(record["download_landing_url"])
    if page.get("access_status") != "free_direct" or not page.get("direct_file_url"):
        raise ValueError("Creator download is no longer publicly accessible for free.")
    file_size = int((page.get("file_probe") or {}).get("bytes") or 0)
    if file_size > 3 * 1024**3:
        raise ValueError("Creator original exceeds the 3 GiB source budget.")
    direct = page["direct_file_url"]
    registry = BACKGROUNDS_DIR / "creator_sources"
    registry.mkdir(exist_ok=True)
    # Stable creator records, not expiring signed file URLs, feed later allocations.
    saved = {k: v for k, v in record.items() if k != "direct_file_url"}
    saved["source_duration"] = video["duration_seconds"]
    write_metadata(registry / (video_id + ".json"), saved)
    # Import only a real 60-second segment, with HTTP seeking. Do not download
    # the entire long original or persist its expiring signed URL as identity.
    with tempfile.TemporaryDirectory(prefix="creator_", dir=BACKGROUNDS_DIR) as temporary:
        staged = Path(temporary) / "clip.mp4"
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-rw_timeout",
                "20000000",
                "-user_agent",
                "Mozilla/5.0",
                "-ss",
                str(start),
                "-i",
                direct,
                "-t",
                "60",
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                "scale=-2:'min(1080,ih)'",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(staged),
            ],
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        if result.returncode or get_video_duration(staged) < 59.9:
            raise RuntimeError(
                "Creator-file segment extraction failed; no alternate paid source used."
            )
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        metadata.update(
            sha256=digest,
            segment_start=start,
            segment_duration=60,
            looped=False,
            changes=f"Creator-linked file; extracted 60 seconds from {start:g}s, muted, H.264 normalized at up to 1080p.",
        )
        # Final duplicate check after extraction, before publication to the pool.
        if store.source_unavailable(metadata):
            raise ValueError("Creator footage was reserved while importing.")
        target = (
            BACKGROUNDS_DIR
            / f"creator_{video_id}_{round(start * 1000):09d}_{round((start + 60) * 1000):09d}.mp4"
        )
        staged.replace(target)
        sidecar = target.with_suffix(".source.json")
        write_metadata(sidecar, metadata)
    return target


@synchronized
def import_local_creator_clip(original, allowed_licenses):
    """Extract an explicitly user-authorized local original, without network access."""
    original = Path(original)
    if LOCAL_LICENSE not in allowed_licenses:
        raise ValueError("User-authorized creator footage is not enabled.")
    source = json.loads(original.with_suffix(".source.json").read_text(encoding="utf-8"))
    if original.stat().st_size > LOCAL_SOURCE_MAX_BYTES:
        raise ValueError("Local creator original exceeds the 8 GiB source budget.")
    if original.stat().st_size != source["download_bytes"]:
        raise ValueError("Local original size differs from provenance.")
    if source.get("youtube_video_id") != "Io2-_UUlUOg":
        raise ValueError("This local original has not been authorized by the user.")
    metadata = dict(
        schema=2,
        query=CREATOR_QUERY,
        title=source["title"],
        author=source["author"],
        source_url=source["source_url"],
        youtube_video_id=source["youtube_video_id"],
        download_landing_url=source["download_landing_url"],
        license=LOCAL_LICENSE,
        license_url=source["source_url"],
        permission_excerpt=source["permission_excerpt"],
        monetization_permission=source["monetization_permission"],
        user_authorized_monetized_reels=True,
        user_authorization_note="User authorized use in monetized reels and download; creator monetization permission is unverified.",
        credit_text=source.get("credit_statement", ""),
        credit_required=False,
        source_duration=source["ffprobe_duration_seconds"],
        original_provenance_sha256=source["sha256"],
        publication_cleared=False,
        requires_visual_review=True,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    store = UsageStore()
    start = store.next_segment_start(metadata, float(metadata["source_duration"]))
    if start is None:
        raise SourceExhausted("No unused full segment remains in this creator recording.")
    metadata.update(segment_policy=SEGMENT_POLICY, segment_start=start, segment_duration=60)
    with tempfile.TemporaryDirectory(prefix="creator_", dir=BACKGROUNDS_DIR) as temporary:
        staged = Path(temporary) / "clip.mp4"
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(start),
                "-i",
                str(original),
                "-t",
                "60",
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                "scale=-2:'min(1080,ih)'",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(staged),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if result.returncode or get_video_duration(staged) < 59.9:
            raise RuntimeError("Local creator segment extraction failed.")
        metadata.update(
            sha256=hashlib.sha256(staged.read_bytes()).hexdigest(),
            looped=False,
            changes=f"Local creator file; extracted 60 seconds from {start:g}s, muted and normalized.",
        )
        if store.source_unavailable(metadata):
            raise ValueError("Creator footage was reserved while importing.")
        target = (
            BACKGROUNDS_DIR
            / f"creator_{source['youtube_video_id']}_{round(start * 1000):09d}_{round((start + 60) * 1000):09d}.mp4"
        )
        staged.replace(target)
        write_metadata(target.with_suffix(".source.json"), metadata)
    return target


def known_creator_records():
    records = {}
    for sidecar in sorted(BACKGROUNDS_DIR.glob("creator_*.source.json")):
        try:
            source = json.loads(sidecar.read_text(encoding="utf-8"))
            identity = source.get("youtube_video_id")
            if not identity or not eligible_metadata(source, {LICENSE}):
                continue
            records[identity] = {
                "video_url": "https://www.youtube.com/watch?v=" + identity,
                "download_landing_url": source["download_landing_url"],
                "permission_url": source["license_url"],
                "permission_excerpt": source["permission_excerpt"],
                "commercial_use": "explicitly_allowed",
                "access_status": "free_direct",
                "credit_required": source.get("credit_required", True),
                "credit_text": source.get("credit_text", ""),
                "source_duration": source.get("source_duration"),
            }
        except (OSError, ValueError, KeyError):
            continue
    for path in sorted((BACKGROUNDS_DIR / "creator_sources").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            identity = urlsplit(record["video_url"]).query.split("v=", 1)[-1].split("&")[0]
            records[identity] = record
        except (OSError, ValueError, KeyError):
            continue
    return records


@synchronized
def replenish_low_supply(config, store):
    """Research a backup when the configured local original has at most two slots.

    Called under the production runner lock. Never removes local media.
    """
    original = Path(config["authorized_local_creator_source"])
    source = json.loads(original.with_suffix(".source.json").read_text(encoding="utf-8"))
    total = float(source["ffprobe_duration_seconds"])
    if not original.is_file() or not source.get("youtube_video_id") or not 65 <= total <= 86400:
        raise ValueError("Cannot measure the configured local footage supply.")
    remaining = 0
    for start in range(5, int(total - 60) + 1, 60):
        metadata = dict(
            source,
            segment_policy=SEGMENT_POLICY,
            segment_start=start,
            segment_duration=60,
            source_duration=total,
        )
        if not store.source_unavailable(metadata):
            remaining += 1
    result = {"remaining_local_segments": remaining}
    if remaining > 2:
        return dict(result, status="sufficient")
    # A previously prepared, still-available verified backup avoids repeated searches.
    for sidecar in BACKGROUNDS_DIR.glob("creator_*.source.json"):
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        video = sidecar.with_name(sidecar.name.replace(".source.json", ".mp4"))
        if (
            metadata.get("youtube_video_id") != source["youtube_video_id"]
            and LICENSE in config["background_licenses"]
            and eligible_metadata(metadata, {LICENSE})
            and video.is_file()
            and metadata.get("segment_policy") == SEGMENT_POLICY
            and hashlib.sha256(video.read_bytes()).hexdigest() == metadata.get("sha256")
            and get_video_duration(video) >= 58
            and not store.source_unavailable(metadata, video)
        ):
            return dict(result, status="backup_available")
    from shorts_automation.footage.agy_footage_research import research

    _, catalog = research(
        count=4, model=config["antigravity_model"], exclude_video_ids=[source["youtube_video_id"]]
    )
    errors = []
    for record in catalog["ready"][:3]:
        try:
            imported = import_creator_clip(record, set(config["background_licenses"]))
            return dict(result, status="replenished", imported=str(imported))
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            errors.append(type(error).__name__)
    raise RuntimeError("No verified backup imported; candidate errors: " + ", ".join(errors))


@synchronized
def get_creator_background(config, catalog_path=None):
    allowed = set(config["background_licenses"])
    cached = cached_creator_clip(allowed)
    if cached:
        return cached
    if not catalog_path and config.get("authorized_local_creator_source"):
        try:
            return import_local_creator_clip(config["authorized_local_creator_source"], allowed)
        except SourceExhausted:
            pass
    errors, exhausted = [], []
    if not catalog_path:
        store = UsageStore()
        for identity, record in known_creator_records().items():
            origin = {
                "youtube_video_id": identity,
                "source_url": "https://youtu.be/" + identity,
                "download_landing_url": record["download_landing_url"],
            }
            total = float(record.get("source_duration") or 0)
            if total and store.next_segment_start(origin, total) is None:
                exhausted.append(identity)
                continue
            try:
                return import_creator_clip(record, allowed)
            except SourceExhausted:
                exhausted.append(identity)
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                errors.append(type(error).__name__)
            if len(errors) >= 3:
                break
    if catalog_path:
        data = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    else:
        from shorts_automation.footage.agy_footage_research import research

        path, data = research(
            count=4, model=config["antigravity_model"], exclude_video_ids=exhausted
        )
        print("[source] Creator evidence catalog:", path.name)
    for record in data["ready"][:3]:
        try:
            return import_creator_clip(record, allowed)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            errors.append(type(error).__name__)
    raise RuntimeError(
        "No independently verified creator file could be imported (" + ", ".join(errors) + ")."
    )


if __name__ == "__main__":
    import argparse

    from shorts_automation.automation.production import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, help="Import from a previously verified AGY catalog."
    )
    args = parser.parse_args()
    print(get_creator_background(load_config(), args.catalog))
