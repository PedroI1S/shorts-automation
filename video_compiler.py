import subprocess
from pathlib import Path
from config import (
    VIDEO_WIDTH, VIDEO_HEIGHT, FPS, OUTPUT_DIR
)

def has_audio_stream(file_path: Path) -> bool:
    """Checks if a video file contains an audio stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        return bool(res.stdout.strip())
    except Exception:
        return False

def compile_short(
    gameplay_path: Path,
    gameplay_start: float,
    narration_path: Path,
    audio_duration: float,
    subtitles_concat_path: Path,
    output_filename: str = "short_output.mp4"
) -> Path:
    """
    Renders the final vertical YouTube Short:
    - Crops 16:9 gameplay to 9:16 (1080x1920) centered
    - Overlays synchronized subtitle cards
    - Mixes narration with background gameplay audio (ducked to 5%)
    - Outputs ready-to-upload MP4
    """
    output_path = OUTPUT_DIR / output_filename
    target_duration = audio_duration + 0.8  # Slight tail buffer

    print(f"[*] Compiling final short ({target_duration:.1f}s)...")

    gameplay_has_audio = has_audio_stream(gameplay_path)

    # Complex Filter Construction
    if gameplay_has_audio:
        # Scale to fit 1920 height, center-crop to 1080 width, overlay subtitles
        # Mix background audio (-26dB ~ 5%) with primary narration audio (100%)
        filter_complex = (
            f"[0:v]scale=-1:{VIDEO_HEIGHT},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}[bg];"
            f"[bg][1:v]overlay=0:0[outv];"
            f"[0:a]volume=0.06[abg];"
            f"[2:a][abg]amix=inputs=2:duration=first:dropout_transition=2[outa]"
        )
        audio_map = ["-map", "[outa]"]
    else:
        filter_complex = (
            f"[0:v]scale=-1:{VIDEO_HEIGHT},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}[bg];"
            f"[bg][1:v]overlay=0:0[outv]"
        )
        audio_map = ["-map", "2:a"]

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{gameplay_start:.2f}",
        "-t", f"{target_duration:.2f}",
        "-i", str(gameplay_path),
        "-f", "concat", "-safe", "0",
        "-i", str(subtitles_concat_path),
        "-i", str(narration_path),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
    ] + audio_map + [
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{target_duration:.2f}",
        str(output_path)
    ]

    print(f"[*] Executing FFmpeg render...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("[!] FFmpeg error details:\n", res.stderr)
        raise RuntimeError("FFmpeg video rendering failed.")

    print(f"[✓] Final short exported successfully to: {output_path}")
    return output_path

if __name__ == "__main__":
    print("Video compiler ready.")
