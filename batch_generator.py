import argparse
import datetime
import json
import random
from pathlib import Path

from config import OUTPUT_DIR, DEFAULT_VOICE, GAMEPLAY_QUERIES
from pipeline import run_pipeline

# Voice rotation pool for variety
VOICE_POOL = [
    "en-US-ChristopherNeural",  # Deep cinematic male
    "en-US-JennyNeural",        # Engaging expressive female
    "en-US-GuyNeural",          # Casual realistic male
    "en-GB-RyanNeural",         # British crisp narrator
    "en-US-EricNeural",         # Energetic male
]

# Subreddit rotation pool
SUBREDDIT_POOL = [
    "shortscarystories",
    "WritingPrompts",
    "ruleshorror",
    "TwoSentenceHorror",
]

# 3 Daily Prime-Time Publishing Slots (Local 24h format)
SCHEDULE_SLOTS = [
    (9, 0),   # 09:00 AM (Morning)
    (14, 0),  # 02:00 PM (Afternoon break)
    (19, 0),  # 07:00 PM (Evening peak)
]

def generate_daily_batch(count: int = 3, target_date: datetime.date = None) -> Path:
    """
    Generates a batch of distinct, unique Shorts with rotated voices,
    gameplay slices, and scheduled upload slots.
    """
    if target_date is None:
        target_date = datetime.date.today()

    date_str = target_date.strftime("%Y-%m-%d")
    batch_dir = OUTPUT_DIR / date_str
    batch_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 65)
    print(f"  🎬 STARTING DAILY BATCH: {count} SHORTS FOR {date_str} 🎬")
    print("=" * 65)

    manifest = {
        "date": date_str,
        "videos": []
    }

    for i in range(count):
        print(f"\n>>> GENERATING VIDEO {i+1} OF {count} <<<")

        # Pick voice and sub from rotation
        voice = VOICE_POOL[i % len(VOICE_POOL)]
        sub = SUBREDDIT_POOL[i % len(SUBREDDIT_POOL)]
        gameplay = random.choice(GAMEPLAY_QUERIES)

        # Calculate scheduled time
        slot_hour, slot_min = SCHEDULE_SLOTS[i % len(SCHEDULE_SLOTS)]
        schedule_dt = datetime.datetime.combine(
            target_date,
            datetime.time(slot_hour, slot_min)
        )
        # ISO 8601 string for YouTube Data API
        schedule_iso = schedule_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Run pipeline
        video_path = run_pipeline(
            subreddit=sub,
            voice=voice,
            gameplay_query=gameplay
        )

        # Move / copy to the daily batch folder
        batch_video_file = batch_dir / f"slot_{i+1:02d}_{video_path.name}"
        video_path.rename(batch_video_file)

        # Store metadata for YouTube Uploader
        video_meta = {
            "slot": i + 1,
            "scheduled_time": schedule_iso,
            "display_time": schedule_dt.strftime("%I:%M %p"),
            "file_path": str(batch_video_file.resolve()),
            "title": f"{video_path.stem.replace('_', ' ')} #shorts #story",
            "description": f"Daily story micro-thriller.\n\n#shorts #storytime #mystery #ruleshorror",
            "tags": ["shorts", "storytime", "minecraft", "creepypasta", "rules", "fiction"],
            "voice_used": voice,
            "subreddit_source": sub
        }
        manifest["videos"].append(video_meta)

    # Save daily manifest JSON
    manifest_path = batch_dir / "upload_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Print summary card
    print("\n" + "=" * 65)
    print("  🎉 DAILY BATCH GENERATION COMPLETED 🎉")
    print("=" * 65)
    print(f"📁 Daily Batch Folder: {batch_dir}")
    print(f"📋 Upload Manifest:    {manifest_path}")
    print("\n📅 Scheduled Schedule:")
    for v in manifest["videos"]:
        print(f"   • Slot {v['slot']} ({v['display_time']}): {Path(v['file_path']).name}")
    print("=" * 65 + "\n")

    return batch_dir

def main():
    parser = argparse.ArgumentParser(description="Generate daily batches of YouTube Shorts.")
    parser.add_argument("--count", type=int, default=3, help="Number of videos to generate (default: 3).")
    parser.add_argument("--tomorrow", action="store_true", help="Schedule for tomorrow instead of today.")
    args = parser.parse_args()

    target_date = datetime.date.today()
    if args.tomorrow:
        target_date += datetime.timedelta(days=1)

    generate_daily_batch(count=args.count, target_date=target_date)

if __name__ == "__main__":
    main()
