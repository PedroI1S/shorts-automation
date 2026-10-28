import argparse
import sys
import re
import json
from uuid import uuid4
from pathlib import Path

from config import DEFAULT_VOICE, OUTPUT_DIR, MAX_DURATION_SECONDS, NARRATION_TAIL_SECONDS
from draft_story import validate_story
from content_hunter import generate_story
from tts_engine import generate_speech, estimate_duration
from gameplay_fetcher import get_background_clip, get_video_duration
from subtitle_engine import generate_subtitles_stream
from video_compiler import compile_short
from usage_store import render_job

def sanitize_filename(title: str) -> str:
    """Cleans a string for safe use in file names."""
    clean = re.sub(r'[^a-zA-Z0-9_\- ]', '', title)
    return clean.strip().replace(' ', '_')[:40]

def run_pipeline(
    topic: str = "",
    subreddit: str = "shortscarystories",
    voice: str = DEFAULT_VOICE,
    gameplay_query: str = None,
    tts_provider: str = "edge",
    story_file: Path | None = None,
    background_file: Path | None = None,
) -> Path:
    print("=" * 60)
    print("  YOUTUBE SHORTS LOCAL EVALUATION PIPELINE  ")
    print("=" * 60)

    # 1. STORY & HOOK GENERATION
    print("\n[STEP 1/5] Hunting & adapting viral story...")
    story = (validate_story(json.loads(Path(story_file).read_text(encoding="utf-8")))
             if story_file else generate_story(topic=topic, subreddit=subreddit))
    background_duration = None
    if background_file:
        background_file = Path(background_file).resolve(strict=True)
        background_duration = get_video_duration(background_file)
        if background_duration <= 0:
            raise ValueError("The supplied background is unreadable or has no duration.")
    title = story.get("title", "Untitled Short")
    script = story.get("script", "")
    print(f"📖 Title: {title}")
    print(f"📝 Script preview: \"{script[:100]}...\"")

    # Reject over-long scripts before reserving the story or spending TTS quota.
    estimated = estimate_duration(script, tts_provider)
    if estimated + NARRATION_TAIL_SECONDS > MAX_DURATION_SECONDS:
        raise ValueError(
            f"Script is {len(script.split())} words; estimated {estimated:.1f}s narration with "
            f"{tts_provider} exceeds the {MAX_DURATION_SECONDS}s limit. Shorten the draft; no TTS call made.")

    with render_job(script) as (store, job_id):
        # 2. VOICE SYNTHESIS & TIMINGS
        print("\n[STEP 2/5] Generating voiceover & word timestamps...")
        audio_path, duration, sentence_blocks = generate_speech(script, voice=voice, provider=tts_provider)
        if duration + 0.8 > MAX_DURATION_SECONDS:
            raise ValueError("Narration exceeds the video duration limit. Shorten the draft; no automatic regeneration performed.")
        print(f"🎙️ Voiceover ready: {duration:.1f}s across {len(sentence_blocks)} words")

        # 3. GAMEPLAY FOOTAGE SOURCING
        print("\n[STEP 3/5] Sourcing background gameplay with recorded license metadata...")
        if background_file:
            if background_duration < duration + 0.8:
                raise ValueError("Supplied background must cover narration plus its 0.8-second tail.")
            bg_video, bg_start = background_file, 0.0
        else:
            bg_video, bg_start = get_background_clip(target_duration=duration, search_query=gameplay_query, job_id=job_id)
        print(f"🎮 Background: {bg_video.name} (starting at {bg_start:.1f}s)")

        if background_file:
            source_metadata = bg_video.with_suffix('.source.json')
            store.reserve_source(job_id, json.loads(source_metadata.read_text(encoding='utf-8')) if source_metadata.exists() else {}, bg_video)

        # 4. SUBTITLE STREAM GENERATION
        print("\n[STEP 4/5] Building kinetic high-retention subtitles...")
        subtitles_concat = generate_subtitles_stream(sentence_blocks, total_audio_duration=duration)

        # 5. FINAL VIDEO ASSEMBLY
        print("\n[STEP 5/5] Compiling final vertical video...")
        clean_title = sanitize_filename(title)
        output_filename = f"{clean_title}_{uuid4().hex[:12]}.mp4"
        store.plan_output(job_id, OUTPUT_DIR / output_filename)
        final_video = compile_short(
            gameplay_path=bg_video,
            gameplay_start=bg_start,
            narration_path=audio_path,
            audio_duration=duration,
            subtitles_concat_path=subtitles_concat,
            output_filename=output_filename
        )
        store.complete(job_id, final_video)
        source_sidecar = bg_video.with_suffix('.source.json')
        background_source = (json.loads(source_sidecar.read_text(encoding='utf-8'))
                             if source_sidecar.exists() else {'source': 'supplied local file', 'publication_cleared': False})
        final_video.with_suffix('.metadata.json').write_text(json.dumps({
            'job_id': job_id, 'story': story, 'narration': str(audio_path), 'narration_duration': duration,
            'tts_provider': tts_provider, 'background_source': background_source,
            'background_start': bg_start, 'publication_cleared': False,
        }, indent=2, ensure_ascii=False), encoding='utf-8')
        if source_sidecar.exists():
            final_video.with_suffix('.credits.txt').write_text(
                f"Gameplay: {background_source.get('title', '')}\n"
                f"Creator: {background_source.get('author', '')}\n"
                f"Source: {background_source.get('source_url', '')}\n"
                f"License: {background_source.get('license', '')} {background_source.get('license_url', '')}\n"
                f"Changes: {background_source.get('changes', '')}; cropped to vertical and captioned.\n"
                "Local evaluation. Listed license metadata is not publication clearance.\n",
                encoding='utf-8')

        # OUTPUT REPORT
        file_size_mb = final_video.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 60)
        print("  LOCAL EVALUATION RENDER COMPLETE  ")
        print("=" * 60)
        print(f"📁 Video File: {final_video}")
        print(f"⏱️ Duration:   {duration:.1f} seconds")
        print(f"📦 File Size:  {file_size_mb:.2f} MB")
        print("\n💡 Suggested YouTube Metadata:")
        print(f"   Title:       {title} #shorts #story")
        print(f"   Description: {script[:120]}...\n   #shorts #storytime #mystery #rules")
        print("=" * 60 + "\n")

        return final_video

def main():
    parser = argparse.ArgumentParser(description="Fully automated YouTube Shorts video creator.")
    parser.add_argument("--topic", type=str, default="", help="Custom story prompt or premise.")
    parser.add_argument("--reddit", type=str, default="shortscarystories", help="Subreddit to scrape premises from.")
    parser.add_argument("--voice", type=str, default=DEFAULT_VOICE, help="Edge-TTS voice name.")
    parser.add_argument("--tts-provider", choices=["edge", "fish", "elevenlabs"], default="edge", help="Explicit voice provider; local evaluation only.")
    parser.add_argument("--story-file", type=Path, help="Validated draft JSON; skips story generation and Reddit.")
    parser.add_argument("--background-file", type=Path, help="Owned/licensed local footage; skips downloads.")
    parser.add_argument("--gameplay", type=str, default=None, help="Custom search query for background gameplay.")
    
    args = parser.parse_args()
    try:
        run_pipeline(
            topic=args.topic,
            subreddit=args.reddit,
            voice=args.voice,
            gameplay_query=args.gameplay,
            tts_provider=args.tts_provider,
            story_file=args.story_file,
            background_file=args.background_file,
        )
    except KeyboardInterrupt:
        print("\n[!] Pipeline interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
