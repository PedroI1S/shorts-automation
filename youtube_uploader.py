import argparse
import json
import os
import sys
from pathlib import Path

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

def get_authenticated_service():
    """Authenticates the user and returns the YouTube API service resource."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                print(f"\n[!] Missing client secrets file: {CLIENT_SECRETS_FILE}")
                print("To upload automatically via the YouTube API:")
                print("1. Go to https://console.cloud.google.com/")
                print("2. Create a project and enable 'YouTube Data API v3'.")
                print("3. Create an 'OAuth 2.0 Client ID' (Desktop App).")
                print(f"4. Download the JSON and save it as: {CLIENT_SECRETS_FILE}\n")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)

def upload_video(
    youtube,
    file_path: str,
    title: str,
    description: str,
    tags: list[str] = None,
    scheduled_time: str = None,
    privacy_status: str = "public",
    dry_run: bool = False
):
    """Uploads a video to YouTube with optional scheduled release."""
    if tags is None:
        tags = ["shorts", "story", "thriller"]

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "selfDeclaredMadeForKids": False,
        }
    }

    # If scheduled_time is specified, privacy MUST be 'private' until publishAt triggers
    if scheduled_time:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = scheduled_time
    else:
        body["status"]["privacyStatus"] = privacy_status

    if dry_run:
        print("\n[DRY RUN] Would upload:")
        print(f"  • File:      {file_path}")
        print(f"  • Title:     {body['snippet']['title']}")
        print(f"  • Status:    {body['status']['privacyStatus']}")
        print(f"  • Scheduled: {scheduled_time or 'Immediate'}")
        return {"id": "DRY_RUN_ID"}

    print(f"\n[*] Uploading {Path(file_path).name} to YouTube...")
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[*] Uploaded {int(status.progress() * 100)}%...")

    video_id = response.get("id")
    print(f"[✓] Upload complete! Video URL: https://youtube.com/shorts/{video_id}")
    return response

def process_manifest(manifest_path: Path, dry_run: bool = False):
    """Processes an upload_manifest.json created by batch_generator.py."""
    if not manifest_path.exists():
        print(f"[!] Manifest not found: {manifest_path}")
        return

    with open(manifest_path) as f:
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
            dry_run=dry_run
        )

def main():
    parser = argparse.ArgumentParser(description="Upload and schedule YouTube Shorts.")
    parser.add_argument("--manifest", type=str, help="Path to upload_manifest.json.")
    parser.add_argument("--file", type=str, help="Single MP4 file path to upload.")
    parser.add_argument("--title", type=str, default="Story Time #shorts", help="Video title.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate upload without sending API requests.")
    args = parser.parse_args()

    if args.manifest:
        process_manifest(Path(args.manifest), dry_run=args.dry_run)
    elif args.file:
        if args.dry_run:
            upload_video(None, args.file, args.title, "Test description #shorts", dry_run=True)
        else:
            yt = get_authenticated_service()
            if yt:
                upload_video(yt, args.file, args.title, "Story #shorts", dry_run=False)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
