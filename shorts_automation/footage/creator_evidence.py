"""Bounded public-web evidence broker for AGY. No shell, logins or checkout.

AGY chooses searches/ranks findings; Python reads public YouTube metadata and
creator-linked pages. This avoids granting a research agent a general terminal.
"""

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests
from yt_dlp import YoutubeDL

REFERENCE = "u7kdVe8q5zs"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ShortsFootageResearch/1.0)"}
PAGE_HOSTS = (
    "mediafire.com",
    "ko-fi.com",
    "drive.google.com",
    "docs.google.com",
    "dropbox.com",
    "t.ly",
    "bit.ly",
    "pixeldrain.com",
    "mega.nz",
    "gumroad.com",
)


class QuietLog:
    def debug(self, *args):
        pass

    def warning(self, *args):
        pass

    def error(self, *args):
        pass


def options(**extra):
    return dict(
        quiet=True,
        no_warnings=True,
        logger=QuietLog(),
        socket_timeout=20,
        retries=1,
        extractor_retries=1,
        cachedir=False,
        **extra,
    )


def search_videos(query, count=4):
    if not isinstance(query, str) or not 1 <= len(query) <= 200 or not 1 <= count <= 6:
        raise ValueError("Invalid bounded search.")
    with YoutubeDL(options(extract_flat=True)) as ydl:
        data = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
    return [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "duration_seconds": e.get("duration"),
            "creator": e.get("channel"),
        }
        for e in data.get("entries", [])
        if e
    ]


def read_video(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Not a YouTube video ID.")
    with YoutubeDL(options(skip_download=True, ignore_no_formats_error=True)) as ydl:
        data = ydl.extract_info("https://www.youtube.com/watch?v=" + video_id, download=False)
    return {
        "id": video_id,
        "video_url": "https://www.youtube.com/watch?v=" + video_id,
        "title": data.get("title"),
        "creator": data.get("uploader"),
        "duration_seconds": data.get("duration"),
        "width": data.get("width"),
        "height": data.get("height"),
        "fps": data.get("fps"),
        "platform_license": data.get("license"),
        "description": data.get("description", "")[:8000],
        "visual_checked": False,
    }


def description_links(description):
    # Creators sometimes write https_:// to avoid automatic link handling.
    text = description.replace("https_://", "https://").replace("http_://", "http://")
    links = re.findall(r'https?://[^\s<>\[\]"\)]+', text)
    links += [
        "https://" + s
        for s in re.findall(r'(?<![/\w])(?:www\.)?mediafire\.com/[^\s<>\[\]"\)]+', text)
    ]
    return list(dict.fromkeys(u.rstrip(".,;") for u in links))


def safe_public_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only public HTTPS links are allowed.")
    if re.search(r"/(?:checkout|cart|purchase|buy)(?:/|\?|$)", parsed.path, re.I):
        raise ValueError("Checkout actions are outside read-only research.")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Local/private network destinations are not allowed.")
    return parsed


def public_get(url, max_redirects=4):
    for _ in range(max_redirects + 1):
        safe_public_url(url)
        response = requests.get(
            url, headers=HEADERS, timeout=(10, 20), stream=True, allow_redirects=False
        )
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("Redirect omitted its destination.")
            url = urljoin(url, location)
            continue
        return response
    raise ValueError("Too many redirects.")


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def inspect_page(url):
    record = {
        "landing_url": url,
        "access_status": "unknown",
        "direct_file_url": None,
        "verified_price": None,
        "file_probe": None,
    }
    try:
        with public_get(url) as response:
            record.update(http_status=response.status_code, final_url=response.url)
            mime = response.headers.get("Content-Type", "").lower()
            if response.status_code != 200:
                record["notes"] = (
                    f"Public request returned HTTP {response.status_code}; no bypass attempted."
                )
                return record
            if mime.startswith("video/"):
                record.update(
                    access_status="free_direct",
                    direct_file_url=response.url,
                    verified_price="0",
                    file_probe={
                        "http_status": 200,
                        "content_type": mime,
                        "bytes": response.headers.get("Content-Length"),
                    },
                )
                return record
            body = bytearray()
            for chunk in response.iter_content(16384):
                body.extend(chunk)
                if len(body) >= 512 * 1024:
                    break
            html = bytes(body[: 512 * 1024]).decode(response.encoding or "utf-8", errors="replace")
        parsed = PageText()
        parsed.feed(html)
        record["page_text"] = " ".join(parsed.parts)[:4500]
        # Drive's public file viewer is HTML, not the file itself. Probe only
        # the canonical download endpoint for this exact creator-linked file ID;
        # login/confirmation HTML is not treated as a successful download.
        final = urlsplit(record.get("final_url", url))
        drive_file = re.fullmatch(r"/file/d/([A-Za-z0-9_-]+)/view/?", final.path)
        if final.hostname == "drive.google.com" and drive_file:
            direct = "https://drive.google.com/uc?export=download&id=" + drive_file.group(1)
            with public_get(direct) as file:
                mime = file.headers.get("Content-Type", "").lower()
                record["file_probe"] = {
                    "http_status": file.status_code,
                    "content_type": mime,
                    "bytes": file.headers.get("Content-Length"),
                }
                if file.status_code == 200 and mime.startswith("video/"):
                    record.update(
                        access_status="free_direct", direct_file_url=file.url, verified_price="0"
                    )
        # Resolve the actual creator-linked MediaFire button, not an ad or
        # a guessed URL. A subsequent public GET verifies video-byte headers.
        if urlsplit(record.get("final_url", url)).hostname in (
            "mediafire.com",
            "www.mediafire.com",
        ):
            match = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*id="downloadButton"', html, re.I)
            if not match:
                match = re.search(r'<a\b[^>]*id="downloadButton"[^>]*href="([^"]+)"', html, re.I)
            if match:
                direct = unescape(match.group(1))
                with public_get(direct) as file:
                    record["file_probe"] = {
                        "http_status": file.status_code,
                        "content_type": file.headers.get("Content-Type", ""),
                        "bytes": file.headers.get("Content-Length"),
                    }
                    if file.status_code == 200 and file.headers.get("Content-Type", "").startswith(
                        "video/"
                    ):
                        record.update(
                            access_status="free_direct",
                            direct_file_url=file.url,
                            verified_price="0",
                        )
        return record
    except Exception as error:
        record["notes"] = "Public page inspection failed: " + type(error).__name__
        return record


def collect_evidence(searches, max_videos=10, exclude_video_ids=()):
    results, errors = [], []
    for query in searches[:3]:
        try:
            results.extend(search_videos(query, 4))
        except Exception as error:
            errors.append({"search": query, "error": type(error).__name__})
    ids = [REFERENCE]
    # Prefer longer recordings; retain some shorter clips for honest comparison.
    for candidate in sorted(results, key=lambda e: (float(e.get("duration_seconds") or 0) < 300,)):
        if (
            candidate.get("id")
            and candidate["id"] not in ids
            and candidate["id"] not in exclude_video_ids
        ):
            ids.append(candidate["id"])

    def read_safely(video_id):
        try:
            return read_video(video_id)
        except Exception as error:
            return {"id": video_id, "error": type(error).__name__}

    with ThreadPoolExecutor(max_workers=2) as pool:
        videos = list(pool.map(read_safely, ids[:max_videos]))
    pages, checked = [], set()
    for video in videos:
        for url in description_links(video.get("description", "")):
            host = urlsplit(url).hostname or ""
            if not any(host == h or host.endswith("." + h) for h in PAGE_HOSTS):
                continue
            if url in checked or len(checked) >= 12:
                continue
            checked.add(url)
            record = inspect_page(url)
            record["linked_from_video"] = video.get("video_url")
            pages.append(record)
    return {
        "searches": searches,
        "search_results": results,
        "excluded_video_ids": list(exclude_video_ids),
        "videos": videos,
        "download_pages": pages,
        "errors": errors,
        "limitations": [
            "Metadata and public download headers inspected; no visual playback verified in this packet.",
            "No checkout, login, purchase, upload or full video download performed.",
        ],
    }
