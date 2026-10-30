"""Measure usable vertical detail before preparing creator footage."""

import json
import subprocess
from urllib.parse import urlsplit

from config import VIDEO_HEIGHT, VIDEO_WIDTH

PREPARATION_POLICY = "native-vertical-crop-v1"

# Crop native pixels before scaling. Portrait intermediates avoid storing and
# decoding unnecessary 4K landscape pixels on the production PC.
VERTICAL_FILTER = (
    f"crop=w='trunc(min(iw,ih*{VIDEO_WIDTH}/{VIDEO_HEIGHT})/2)*2':"
    f"h='trunc(min(ih,iw*{VIDEO_HEIGHT}/{VIDEO_WIDTH})/2)*2',"
    f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:flags=lanczos,setsar=1"
)


def require_vertical_detail(path):
    """Probe the actual file, refusing footage that needs vertical enlargement."""
    network_options = (
        ["-rw_timeout", "20000000", "-user_agent", "Mozilla/5.0"]
        if urlsplit(str(path)).scheme in {"http", "https"}
        else []
    )
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            *network_options,
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,sample_aspect_ratio",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    # Do not echo stderr or the source URL: public download links can be signed.
    if result.returncode:
        raise ValueError("Could not measure creator footage resolution.")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        if width <= 0 or height <= 0:
            raise ValueError
        if stream.get("sample_aspect_ratio") not in (None, "N/A", "0:1", "1:1"):
            raise ValueError
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError("Creator footage needs measurable square-pixel dimensions.") from None
    crop_width = int(min(width, height * VIDEO_WIDTH / VIDEO_HEIGHT)) // 2 * 2
    crop_height = int(min(height, width * VIDEO_HEIGHT / VIDEO_WIDTH)) // 2 * 2
    if crop_width < VIDEO_WIDTH or crop_height < VIDEO_HEIGHT:
        raise ValueError(
            f"Creator footage {width}x{height} leaves only {crop_width}x{crop_height} "
            f"after vertical cropping; {VIDEO_WIDTH}x{VIDEO_HEIGHT} native detail is required. "
            "Use a higher-resolution original; no upscaled source accepted."
        )
    return {
        "source_width": width,
        "source_height": height,
        "vertical_crop_width": crop_width,
        "vertical_crop_height": crop_height,
    }


def has_vertical_detail(path):
    try:
        require_vertical_detail(path)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
