"""Automatic Commons sourcing for local evaluation; provenance is not rights clearance."""

import argparse
import hashlib
import json
import math
import random
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

import requests

from config import BACKGROUNDS_DIR
from shorts_automation.state.source_lock import synchronized
from shorts_automation.state.usage_store import AlreadyUsed, UsageStore, source_keys

DEFAULT_QUERY = "Labyrinth Minetest"
MAX_BYTES = 100 * 1024 * 1024
LICENSES = {"CC0", "CC BY 3.0", "CC BY 4.0", "CC BY-SA 3.0", "CC BY-SA 4.0"}
HEADERS = {"User-Agent": "ShortsLocalEvaluation/1.0 (local prototype)"}


def get_video_duration(file_path):
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        d = json.loads(r.stdout)
        s, t = d["streams"][0], float(d["format"]["duration"])
        return t if s["width"] >= 640 and s["height"] >= 360 and math.isfinite(t) and t > 0 else 0.0
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return 0.0


def candidate_from_page(page, query):
    i = (page.get("imageinfo") or [{}])[0]
    metadata = i.get("extmetadata", {})

    def field(key):
        return unescape(re.sub("<[^>]+>", "", str(metadata.get(key, {}).get("value", "")))).strip()

    url = i.get("url", "")
    if (
        urlsplit(url).scheme != "https"
        or urlsplit(url).hostname != "upload.wikimedia.org"
        or field("LicenseShortName") not in LICENSES
        or not 0 < i.get("size", 0) <= MAX_BYTES
        or not field("Artist")
        or not field("LicenseUrl")
        or not i.get("descriptionurl")
    ):
        return None
    return dict(
        schema=1,
        query=query,
        pageid=page["pageid"],
        title=page["title"],
        author=field("Artist"),
        source_url=i["descriptionurl"],
        download_url=url,
        license=field("LicenseShortName"),
        license_url=field("LicenseUrl"),
        declared_bytes=i["size"],
        license_snapshot=metadata,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        requires_visual_review=True,
        publication_cleared=False,
        share_alike="BY-SA" in field("LicenseShortName"),
    )


def search_candidates(query):
    r = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query + " filetype:video",
            "gsrnamespace": 6,
            "gsrlimit": 20,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
        },
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError("Commons rejected the search.")
    pages = sorted(
        data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 999)
    )
    return [c for p in pages if (c := candidate_from_page(p, query))]


def cached_clips(query, required, allowed_licenses=None):
    for sidecar in sorted(BACKGROUNDS_DIR.glob("commons_*.source.json")):
        try:
            d = json.loads(sidecar.read_text(encoding="utf-8"))
            p = sidecar.with_name(sidecar.name.replace(".source.json", ".mp4"))
            if (
                d.get("schema") == 1
                and d.get("query") == query
                and d.get("license") in (allowed_licenses or LICENSES)
                and not UsageStore().unavailable(source_keys(d))
                and p.is_file()
                and hashlib.sha256(p.read_bytes()).hexdigest() == d.get("sha256")
                and get_video_duration(p) >= required
            ):
                yield p
        except (OSError, ValueError):
            continue


@synchronized
def download_gameplay_clip(query=None, required_duration=60, allowed_licenses=None):
    query = query or DEFAULT_QUERY
    store = UsageStore()
    candidates = [
        c
        for c in search_candidates(query)
        if not store.unavailable(source_keys(c)) and c["license"] in (allowed_licenses or LICENSES)
    ]
    for c in candidates[:3]:
        try:
            with tempfile.TemporaryDirectory(prefix="source_", dir=BACKGROUNDS_DIR) as temp:
                raw, staged = Path(temp) / "raw.video", Path(temp) / "video.mp4"
                total, started = 0, time.monotonic()
                with (
                    requests.get(
                        c["download_url"],
                        headers=HEADERS,
                        stream=True,
                        timeout=(15, 30),
                        allow_redirects=False,
                    ) as r,
                    raw.open("wb") as f,
                ):
                    if r.status_code != 200:
                        raise RuntimeError("Download did not return HTTP 200.")
                    for chunk in r.iter_content(256 * 1024):
                        total += len(chunk)
                        if total > MAX_BYTES or time.monotonic() - started > 120:
                            raise RuntimeError("Download exceeded size/time budget.")
                        f.write(chunk)
                source_duration = get_video_duration(raw)
                if total != c["declared_bytes"] or source_duration < max(15, required_duration / 4):
                    raise RuntimeError(
                        "Incomplete, unreadable, low-resolution or under-15-second source."
                    )
                loop = source_duration < required_duration
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        *(["-stream_loop", "-1"] if loop else []),
                        "-i",
                        str(raw),
                        "-t",
                        str(required_duration),
                        "-map",
                        "0:v:0",
                        "-an",
                        "-vf",
                        "scale=-2:720",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "fast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        str(staged),
                    ],
                    check=True,
                    timeout=180,
                )
                if get_video_duration(staged) < required_duration:
                    raise RuntimeError("Normalized footage is too short.")
                c.update(
                    sha256=hashlib.sha256(staged.read_bytes()).hexdigest(),
                    original_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                    source_duration=source_duration,
                    looped=loop,
                    changes="Muted, trimmed or looped (see looped field), scaled to 720p; final render may crop and overlay captions.",
                )
                if store.unavailable(source_keys(c)):
                    raise AlreadyUsed("Downloaded footage matches a used source.")
                key = hashlib.sha256((query + str(c["pageid"])).encode()).hexdigest()[:16]
                output = BACKGROUNDS_DIR / f"commons_{key}.mp4"
                metadata = Path(temp) / "source.json"
                metadata.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
                staged.replace(output)
                metadata.replace(output.with_suffix(".source.json"))
                print("[source] Downloaded:", c["title"])
                return output
        except (
            requests.RequestException,
            OSError,
            ValueError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as e:
            print("[source] Rejected:", c["title"], type(e).__name__, str(e)[:180])
    raise RuntimeError(
        "No usable licensed result within three download attempts. No unrelated fallback used."
    )


@synchronized
def get_background_clip(target_duration, search_query=None, job_id=None, allowed_licenses=None):
    if not math.isfinite(target_duration) or not 0 < target_duration <= 58:
        raise ValueError("Narration duration must be positive and at most 58 seconds.")
    query = (search_query or DEFAULT_QUERY).strip()
    if not query or len(query) > 200:
        raise ValueError("Query must contain 1 to 200 characters.")
    required = target_duration + 0.8
    options = {"allowed_licenses": allowed_licenses} if allowed_licenses else {}
    cached = list(cached_clips(query, required, **options))
    p = (
        random.choice(cached)
        if cached
        else download_gameplay_clip(query, max(60, required), **options)
    )
    duration = get_video_duration(p)
    if duration < required:
        raise RuntimeError("Selected background cannot cover narration and tail.")
    if job_id:
        UsageStore().reserve_source(
            job_id, json.loads(p.with_suffix(".source.json").read_text(encoding="utf-8")), p
        )
    return p, random.uniform(0, max(0, duration - required))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--duration", type=float, default=56.3)
    args = parser.parse_args()
    print(get_background_clip(args.duration, args.query))
