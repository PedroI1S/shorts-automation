"""Stage and explicitly promote a verified YouTube credential; never upload."""

import argparse
import os
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from shorts_automation.publishing.youtube_uploader import (
    CLIENT_SECRETS_FILE,
    TOKEN_FILE,
    TOKEN_LOCK,
)
from shorts_automation.state.source_lock import source_lock

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
CANDIDATE = TOKEN_FILE.with_name("token-candidate.json")


def verify_candidate(candidate):
    creds = Credentials.from_authorized_user_file(str(candidate), SCOPES)
    if not creds.refresh_token:
        return False
    creds.refresh(Request())
    response = requests.post(
        "https://oauth2.googleapis.com/tokeninfo", data={"access_token": creds.token}, timeout=20
    )
    response.raise_for_status()
    return set(SCOPES).issubset(set(response.json().get("scope", "").split()))


def promote(candidate, active):
    candidate, active = Path(candidate), Path(active)
    with source_lock(TOKEN_LOCK):
        if not verify_candidate(candidate):
            raise ValueError("Candidate lacks required scopes or refresh token")
        os.replace(candidate, active)


def stage():
    if CANDIDATE.exists():
        raise FileExistsError(
            "Candidate already exists; inspect or remove it yourself before retrying"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    if not creds.refresh_token:
        raise ValueError("Google did not issue a refresh token")
    with CANDIDATE.open("x", encoding="utf-8") as f:
        f.write(creds.to_json())
    if not verify_candidate(CANDIDATE):
        raise ValueError("Candidate is missing a required scope")
    fresh = Credentials.from_authorized_user_file(str(CANDIDATE), SCOPES)
    fresh.refresh(Request())
    result = (
        build("youtube", "v3", credentials=fresh)
        .channels()
        .list(part="snippet", mine=True)
        .execute()
    )
    for channel in result.get("items", []):
        print("Channel:", channel["id"], channel["snippet"]["title"])
    print("Candidate verified. Confirm this is the intended channel before promotion.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["stage", "promote"])
    args = parser.parse_args()
    try:
        if args.action == "stage":
            stage()
        else:
            promote(CANDIDATE, TOKEN_FILE)
            print("Verified candidate promoted.")
    except Exception:
        print(
            "Authorization or verification failed. Existing token was not replaced; candidate may remain. Check local setup and retry."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
