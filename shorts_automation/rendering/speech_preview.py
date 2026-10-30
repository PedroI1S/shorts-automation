"""Make a local voice/caption sample without story generation, downloads or uploads."""

import argparse
import subprocess
from pathlib import Path

from config import DEFAULT_VOICE, FPS, OUTPUT_DIR, VIDEO_HEIGHT, VIDEO_WIDTH
from shorts_automation.rendering.subtitle_engine import generate_subtitles_stream
from shorts_automation.stories.tts_engine import generate_speech

SAMPLE = (
    "I heard my phone ring from the kitchen. But it was already in my hand. "
    "The screen lit up with a message from my own number. "
    "Don't answer the other phone."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["edge", "elevenlabs", "fish"], default="edge")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--text", default=SAMPLE)
    parser.add_argument(
        "--audio-metadata",
        type=Path,
        help="Reuse saved narration and timestamps without API calls.",
    )
    parser.add_argument("--output-name", help="Optional MP4 filename in storage/output.")
    parser.add_argument(
        "--series-part", type=int, help="Preview a series label without drafting a story."
    )
    parser.add_argument("--series-total", type=int, choices=(3, 4), default=3)
    args = parser.parse_args()
    series = None
    if args.series_part is not None:
        if not 1 <= args.series_part <= args.series_total:
            parser.error("--series-part must be within the series.")
        series = {
            "id": "0" * 32,
            "title": "Serial Caption Preview On Channel",
            "part": args.series_part,
            "total": args.series_total,
            "ending": "finale" if args.series_part == args.series_total else "cliffhanger",
        }
    if len(args.text) > 1200:
        parser.error("Preview limited to 1,200 characters to conserve free quota.")
    if args.audio_metadata:
        import json

        from shorts_automation.stories.tts_engine import audio_duration

        metadata = json.loads(args.audio_metadata.read_text())
        audio = args.audio_metadata.with_suffix(".mp3")
        duration, words = audio_duration(audio), metadata["words"]
        args.provider = metadata["provider"]
    else:
        audio, duration, words = generate_speech(args.text, args.voice, args.provider)
    captions = generate_subtitles_stream(words, duration, **({"series": series} if series else {}))
    if args.output_name and (
        Path(args.output_name).name != args.output_name or not args.output_name.endswith(".mp4")
    ):
        parser.error("--output-name must be an MP4 filename without directories.")
    output = OUTPUT_DIR / (args.output_name or f"preview_{audio.stem}.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x18202c:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={FPS}",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(captions),
            "-i",
            str(audio),
            "-filter_complex",
            "[0:v][1:v]overlay=0:0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(FPS),
            "-c:a",
            "aac",
            "-t",
            str(duration + 0.8),
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
    )
    print(f"Local evaluation sample: {output}")
    if args.provider == "elevenlabs":
        print("ElevenLabs free-plan audio: noncommercial evaluation only.")


if __name__ == "__main__":
    main()
