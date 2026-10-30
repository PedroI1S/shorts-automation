import argparse
import datetime
import json
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import BASE_DIR, SECRETS_DIR
from shorts_automation.state.source_lock import source_lock

TOKEN_LOCK = BASE_DIR / "storage" / "youtube-token.lock"

# YouTube Upload Scope
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "token.json"
PUBLISH_TIMEZONE = "America/New_York"

# Three daily publishing slots in the channel timezone, including DST changes.
DEFAULT_SCHEDULE_SLOTS = [
    (7, 0),
    (12, 0),
    (19, 0),
]


def get_authenticated_service(
    token_path=TOKEN_FILE, client_secrets_path=CLIENT_SECRETS_FILE, interactive=False
):
    # Serialize credential reads/refresh writes with verified token promotion.
    with source_lock(TOKEN_LOCK):
        return _get_authenticated_service(token_path, client_secrets_path, interactive)


def _get_authenticated_service(
    token_path=TOKEN_FILE, client_secrets_path=CLIENT_SECRETS_FILE, interactive=False
):
    """Authenticates the user and returns the YouTube API service resource."""
    token_path = Path(token_path)
    client_secrets_path = Path(client_secrets_path)
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path))

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not interactive:
                raise ValueError(
                    "YouTube login required. Run python -m shorts_automation.publishing.youtube_uploader --authenticate interactively first."
                )
            if not client_secrets_path.exists():
                print(f"\n[!] Missing client secrets file: {client_secrets_path}")
                print("To upload automatically via the YouTube API:")
                print("1. Go to https://console.cloud.google.com/")
                print("2. Create a project and enable 'YouTube Data API v3'.")
                print("3. Under Google Auth Platform, create a Desktop App client.")
                print(f"4. Download the JSON and save it as: {client_secrets_path}\n")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    transport = httplib2.Http(timeout=60)
    # Google uses 308 as "Resume Incomplete", not an HTTP redirect.
    # Match googleapiclient.http.build_http while preserving the request timeout.
    transport.redirect_codes = transport.redirect_codes - {308}
    return build("youtube", "v3", http=AuthorizedHttp(creds, http=transport))


def normalize_publish_time(value, now=None):
    """Validate an explicit future instant and return canonical UTC for comparisons."""
    try:
        instant = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Publish time must be an ISO timestamp with a timezone.") from None
    if instant.tzinfo is None:
        raise ValueError("Publish time must include a timezone (Z or UTC offset).")
    instant = instant.astimezone(datetime.timezone.utc).replace(microsecond=0)
    if instant <= (now or datetime.datetime.now(datetime.timezone.utc)):
        raise ValueError("Publish time must be in the future.")
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _scheduled_instant(value):
    instant = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Booked publish time must include a timezone.")
    return instant.astimezone(datetime.timezone.utc)


def get_next_publishing_slot(
    existing_scheduled=None, min_lead_minutes=45, slots=None, from_time=None
):
    """
    Finds the earliest upcoming publishing slot that is at least `min_lead_minutes` in the future
    and not in `existing_scheduled`, using the configured channel timezone.
    """
    slots = sorted(set(slots or DEFAULT_SCHEDULE_SLOTS))
    if min_lead_minutes <= 0:
        raise ValueError("Scheduling lead time must be positive.")
    now = from_time or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("from_time must include a timezone.")
    now_local = now.astimezone(ZoneInfo(PUBLISH_TIMEZONE))
    earliest = now.astimezone(datetime.timezone.utc) + datetime.timedelta(minutes=min_lead_minutes)
    existing = {_scheduled_instant(value) for value in (existing_scheduled or [])}

    for day_offset in range(60):
        target_date = (now_local + datetime.timedelta(days=day_offset)).date()
        for h, m in slots:
            slot_local = datetime.datetime.combine(
                target_date, datetime.time(h, m), tzinfo=now_local.tzinfo
            )
            if slot_local >= earliest:
                utc_dt = slot_local.astimezone(datetime.timezone.utc)
                utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                if utc_dt not in existing:
                    return {
                        "local_dt": slot_local,
                        "utc_iso": utc_iso,
                        "display": slot_local.strftime("%Y-%m-%d %I:%M %p %Z"),
                    }

    raise RuntimeError("Could not find an available scheduling slot within the next 60 days.")


def build_short_metadata(video_path: Path):
    """Extracts title, description, tags, and license credits from video and sidecars."""
    video_path = Path(video_path)
    meta_path = video_path.with_suffix(".metadata.json")
    credits_path = video_path.with_suffix(".credits.txt")

    title = "Story Time #shorts"
    creator_credit = ""
    description_lines = []
    tags = ["shorts", "story", "thriller", "horror", "storytime", "mystery"]

    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            story = data.get("story", {})
            creator_credit = (data.get("background_source", {}).get("credit_text") or "").strip()
            if story.get("title"):
                title = f"{story['title']} #shorts #story"
            if story.get("script"):
                description_lines.append(f"{story['script'][:140]}...\n")
        except (OSError, ValueError):
            pass

    description_lines.append("#shorts #storytime #mystery #ruleshorror #thriller\n")
    description_lines.append("Original fictional story with AI-generated narration.\n")

    credits_text = ""
    if credits_path.is_file():
        try:
            credits_text = "\n".join(
                line
                for line in credits_path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("Local evaluation.")
            ).strip()
        except OSError:
            pass
    # Older renders can have source credit instructions only in their metadata.
    if creator_credit and creator_credit not in credits_text:
        credits_text = "\n".join(filter(None, (credits_text, creator_credit)))
    if credits_text:
        description_lines.append(f"--- Attribution ---\n{credits_text}")

    return {
        "title": title[:100],
        "description": "\n".join(description_lines).strip(),
        "tags": tags,
    }


def upload_video(
    youtube,
    file_path: str,
    title: str,
    description: str,
    tags: list[str] = None,
    scheduled_time: str = None,
    privacy_status: str = "private",
    dry_run: bool = False,
):
    """
    Uploads a vertical Short to YouTube.
    If scheduled_time is provided, privacy MUST be 'private' with future 'publishAt'.
    Defaults to 'private' to prevent accidental immediate public release.
    """
    file_path = Path(file_path).resolve(strict=not dry_run)
    if scheduled_time:
        scheduled_time = normalize_publish_time(scheduled_time)
    tags = tags or ["shorts", "story", "thriller"]

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "selfDeclaredMadeForKids": False,
        },
    }

    if scheduled_time:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = scheduled_time
    else:
        body["status"]["privacyStatus"] = privacy_status

    if dry_run:
        print("\n[DRY RUN] Would upload Short to YouTube:")
        print(f"  • File:        {file_path.name}")
        print(f"  • Title:       {body['snippet']['title']}")
        print(f"  • Status:      {body['status']['privacyStatus']}")
        print(f"  • PublishAt:   {scheduled_time or 'Immediate'}")
        return {"id": "DRY_RUN_ID", "url": "https://youtube.com/shorts/DRY_RUN_ID", "dry_run": True}

    if not youtube:
        raise ValueError("YouTube service is not authenticated.")

    print(f"\n[*] Uploading {file_path.name} to YouTube...")
    media = MediaFileUpload(
        str(file_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4"
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    deadline = time.monotonic() + 900
    while response is None:
        if time.monotonic() > deadline:
            raise TimeoutError(
                "Resumable upload exceeded 15 minutes; inspect channel before retrying."
            )
        status, response = request.next_chunk(num_retries=3)
        if status:
            print(f"[*] Uploaded {int(status.progress() * 100)}%...")

    video_id = response.get("id")
    if not isinstance(video_id, str) or not video_id.strip():
        raise RuntimeError("YouTube returned no video ID; inspect the channel before retrying.")
    video_url = f"https://youtube.com/shorts/{video_id}"
    receipt = file_path.with_suffix(".upload-receipt.json")
    staged_receipt = receipt.with_suffix(".partial.json")
    staged_receipt.write_text(
        json.dumps(
            {"id": video_id, "requested_status": body["status"], "response": response}, indent=2
        ),
        encoding="utf-8",
    )
    staged_receipt.replace(receipt)
    print(f"[✓] Upload complete! Video URL: {video_url}")
    return {"id": video_id, "url": video_url, "response": response}


def process_manifest(manifest_path: Path, dry_run: bool = False):
    """Processes an upload_manifest.json created by legacy.batch_generator."""
    if not manifest_path.exists():
        print(f"[!] Manifest not found: {manifest_path}")
        return

    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    youtube = None
    if not dry_run:
        youtube = get_authenticated_service()
        if not youtube:
            print("[!] YouTube authentication failed. Aborting upload.")
            return

    print(f"[*] Processing {len(data.get('videos', []))} videos from manifest...")
    for item in data.get("videos", []):
        upload_video(
            youtube=youtube,
            file_path=item["file_path"],
            title=item["title"],
            description=item["description"],
            tags=item.get("tags", []),
            scheduled_time=item.get("scheduled_time"),
            dry_run=dry_run,
        )


def main():
    parser = argparse.ArgumentParser(description="Upload and schedule YouTube Shorts.")
    parser.add_argument("--manifest", type=str, help="Path to upload_manifest.json.")
    parser.add_argument("--file", type=str, help="Single MP4 file path to upload.")
    parser.add_argument("--title", type=str, default=None, help="Video title override.")
    parser.add_argument(
        "--publish-at", type=str, default=None, help="UTC ISO timestamp or 'auto' for next slot."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate upload without sending API requests."
    )
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help="Explicit interactive YouTube OAuth setup; does not upload.",
    )
    args = parser.parse_args()

    if args.authenticate:
        if get_authenticated_service(interactive=True):
            print("YouTube authentication ready. No upload performed.")
    elif args.manifest:
        process_manifest(Path(args.manifest), dry_run=args.dry_run)
    elif args.file:
        file_path = Path(args.file)
        meta = build_short_metadata(file_path)
        title = args.title or meta["title"]
        scheduled_time = None
        if args.publish_at == "auto":
            slot = get_next_publishing_slot()
            scheduled_time = slot["utc_iso"]
            print(f"[*] Assigned next publishing slot: {slot['display']} (UTC: {scheduled_time})")
        elif args.publish_at:
            scheduled_time = args.publish_at

        yt = None if args.dry_run else get_authenticated_service()
        upload_video(
            yt,
            str(file_path),
            title=title,
            description=meta["description"],
            tags=meta["tags"],
            scheduled_time=scheduled_time,
            dry_run=args.dry_run,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
