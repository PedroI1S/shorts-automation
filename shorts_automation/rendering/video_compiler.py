import os
import subprocess
from pathlib import Path

from config import FPS, NARRATION_TAIL_SECONDS, OUTPUT_DIR
from shorts_automation.footage.video_quality import VERTICAL_FILTER

RENDER_TIMEOUT_SECONDS = 900  # A stuck FFmpeg must not block a 24/7 queue forever.


def has_audio_stream(file_path: Path) -> bool:
    """Checks if a video file contains an audio stream."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return bool(res.stdout.strip())
    except Exception:
        return False


def compile_short(
    gameplay_path: Path,
    gameplay_start: float,
    narration_path: Path,
    audio_duration: float,
    subtitles_concat_path: Path,
    output_filename: str = "short_output.mp4",
) -> Path:
    """
    Renders the final vertical YouTube Short:
    - Center-crops native pixels, then scales to 1080x1920 with Lanczos
    - Overlays synchronized subtitle cards
    - Mixes narration with background gameplay audio (ducked to 6%)
    - Writes to a temporary file and publishes it atomically, so the final
      filename only ever exists as a complete, successfully rendered MP4
    """
    output_path = OUTPUT_DIR / output_filename
    partial_path = output_path.with_name(output_path.stem + ".partial.mp4")
    target_duration = audio_duration + NARRATION_TAIL_SECONDS  # Slight tail buffer

    print(f"[*] Compiling final short ({target_duration:.1f}s)...")

    gameplay_has_audio = has_audio_stream(gameplay_path)

    # Creator imports already have native-detail portrait frames. Use the same
    # crop-first path for direct originals and manual evaluation clips.
    video_chain = f"[0:v]{VERTICAL_FILTER}[bg];[bg][1:v]overlay=0:0[outv]"

    # Complex Filter Construction
    if gameplay_has_audio:
        # Mix background audio (-24dB ~ 6%) with primary narration audio (100%).
        # normalize=0 stops amix from dividing every input by the input count,
        # which would otherwise halve the narration volume.
        filter_complex = (
            video_chain + ";"
            "[0:a]volume=0.06[abg];"
            "[2:a][abg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[outa]"
        )
        audio_map = ["-map", "[outa]"]
    else:
        filter_complex = video_chain
        audio_map = ["-map", "2:a"]

    cmd = (
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{gameplay_start:.2f}",
            "-t",
            f"{target_duration:.2f}",
            "-i",
            str(gameplay_path),
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(subtitles_concat_path),
            "-i",
            str(narration_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
        ]
        + audio_map
        + [
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-r",
            str(FPS),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{target_duration:.2f}",
            "-movflags",
            "+faststart",
            str(partial_path),
        ]
    )

    print("[*] Executing FFmpeg render...")
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS, check=False
        )
        if res.returncode != 0:
            print("[!] FFmpeg error details:\n", res.stderr)
            raise RuntimeError("FFmpeg video rendering failed.")
        if not partial_path.is_file() or partial_path.stat().st_size == 0:
            raise RuntimeError("FFmpeg reported success but produced no output.")
        os.replace(partial_path, output_path)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"FFmpeg render exceeded {RENDER_TIMEOUT_SECONDS}s and was stopped."
        ) from None
    finally:
        # Never leave a truncated file behind; the final name is untouched on failure.
        partial_path.unlink(missing_ok=True)

    print(f"[✓] Final short exported successfully to: {output_path}")
    return output_path


if __name__ == "__main__":
    print("Video compiler ready.")
