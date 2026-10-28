import argparse
import datetime
import json
import os
from pathlib import Path
import sys

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import BASE_DIR

# YouTube Upload Scope
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = BASE_DIR / "client_secret.json"
TOKEN_FILE = BASE_DIR / "token.json"

# Daily Prime-Time Publishing Slots (Local time 24h format)
# 09:00 AM (Morning), 02:00 PM (Afternoon break), 07:00 PM (Evening peak)
DEFAULT_SCHEDULE_SLOTS = [
    (9, 0),
    (14, 0),
    (19, 0),
]


def get_authenticated_service(token_path=TOKEN_FILE, client_secrets_path=CLIENT_SECRETS_FILE):
    """Authenticates the user and returns the YouTube API service resource."""
    token_path = Path(token_path)
    client_secrets_path = Path(client_secrets_path)
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
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

    return build("youtube", "v3", credentials=creds)


def get_next_publishing_slot(existing_scheduled=None, min_lead_minutes=45, slots=None, from_time=None):
    """
    Finds the earliest upcoming publishing slot that is at least `min_lead_minutes` in the future
    and not in `existing_scheduled`. Converts local machine time accurately to UTC ISO 8601 string.
    """
    slots = slots or DEFAULT_SCHEDULE_SLOTS
    now_local = (from_time or datetime.datetime.now()).astimezone()
    earliest = now_local + datetime.timedelta(minutes=min_lead_minutes)
    existing = set(existing_scheduled or [])

    for day_offset in range(60):
        target_date = (now_local + datetime.timedelta(days=day_offset)).date()
        for h, m in slots:
            slot_local = datetime.datetime.combine(target_date, datetime.time(h, m), tzinfo=now_local.tzinfo)
            if slot_local >= earliest:
                utc_dt = slot_local.astimezone(datetime.timezone.utc)
                utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                if utc_iso not in existing:
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
    description_lines = []
    tags = ["shorts", "story", "thriller", "horror", "storytime", "mystery"]

    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            story = data.get("story", {})
            if story.get("title"):
                title = f"{story['title']} #shorts #story"
            if story.get("script"):
                description_lines.append(f"{story['script'][:140]}...\n")
        except (OSError, ValueError):
            pass

    description_lines.append("#shorts #storytime #mystery #ruleshorror #thriller\n")

    if credits_path.is_file():
        try:
            credits_text = credits_path.read_text(encoding="utf-8").strip()
            if credits_text:
                description_lines.append(f"--- Attribution ---\n{credits_text}")
        except OSError:
            pass

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
    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[*] Uploaded {int(status.progress() * 100)}%...")

    video_id = response.get("id")
    video_url = f"https://youtube.com/shorts/{video_id}"
    print(f"[✓] Upload complete! Video URL: {video_url}")
    return {"id": video_id, "url": video_url, "response": response}


def process_manifest(manifest_path: Path, dry_run: bool = False):
    """Processes an upload_manifest.json created by batch_generator.py."""
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
    parser.add_argument("--publish-at", type=str, default=None, help="UTC ISO timestamp or 'auto' for next slot.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate upload without sending API requests.")
    args = parser.parse_args()

    if args.manifest:
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
