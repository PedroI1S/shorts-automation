import math
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import (
    FONT_PATH,
    SUBTITLE_BOX_BG,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_HIGHLIGHT_COLOR,
    SUBTITLE_PRIMARY_COLOR,
    SUBTITLE_STROKE_COLOR,
    SUBTITLE_STROKE_WIDTH,
    SUBTITLE_WORDS_PER_CHUNK,
    TEMP_DIR,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)


def get_font(size: int = SUBTITLE_FONT_SIZE) -> ImageFont.FreeTypeFont:
    """Loads font with fallback to default PIL font."""
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def draw_label(draw: ImageDraw.ImageDraw, label: str, y: int):
    """Centered dark pill used for part labels and continuation cues."""
    label_font = get_font(44)
    bounds = draw.textbbox((0, 0), label, font=label_font, stroke_width=2)
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    left = (VIDEO_WIDTH - width) // 2
    draw.rounded_rectangle(
        (left - 22, y - 12, left + width + 22, y + height + 20), radius=16, fill=(0, 0, 0, 210)
    )
    draw.text(
        (left, y),
        label,
        font=label_font,
        fill=SUBTITLE_PRIMARY_COLOR,
        stroke_width=2,
        stroke_fill=SUBTITLE_STROKE_COLOR,
    )


def write_concat(entries: list[tuple[Path, float]], concat_file: Path) -> Path:
    """Write an ffconcat script of overlay images with absolute durations."""

    def quote(path):
        return str(path.resolve()).replace("'", "'\\''")

    with concat_file.open("w") as stream:
        stream.write("ffconcat version 1.0\n")
        for path, duration in entries:
            stream.write(f"file '{quote(path)}'\noption framerate 1000\nduration {duration:.6f}\n")
        stream.write(f"file '{quote(entries[-1][0])}'\noption framerate 1000\n")
    return concat_file


def create_subtitle_image(
    text: str,
    output_path: Path,
    highlight_first_word: bool = True,
    *,
    highlight_index: int | None = 0,
    part_label: str | None = None,
    continuation: str | None = None,
):
    """Draws a high-impact, transparent subtitle overlay image with outline and dark card."""
    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = get_font(SUBTITLE_FONT_SIZE)
    for label, y in ((part_label, 300), (continuation, 1450)):
        if label:
            draw_label(draw, label, y)

    clean_text = text.upper().strip()
    words = clean_text.split()
    if not words:
        img.save(output_path)
        return

    # Calculate bounding box of full text line
    bbox = draw.textbbox((0, 0), clean_text, font=font, stroke_width=SUBTITLE_STROKE_WIDTH)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Position at lower third (y = 1100)
    y_center = 1150
    x_start = (VIDEO_WIDTH - text_width) // 2

    # Draw semi-transparent dark rounded badge behind text
    padding_x = 35
    padding_y = 20
    box_left = max(20, x_start - padding_x)
    box_top = y_center - (text_height // 2) - padding_y
    box_right = min(VIDEO_WIDTH - 20, x_start + text_width + padding_x)
    box_bottom = y_center + (text_height // 2) + padding_y

    draw.rounded_rectangle(
        [(box_left, box_top), (box_right, box_bottom)], radius=25, fill=SUBTITLE_BOX_BG
    )

    # Draw word by word with highlighting
    current_x = x_start
    for i, word in enumerate(words):
        # Only the currently spoken word is yellow; layout stays fixed.
        color = (
            SUBTITLE_HIGHLIGHT_COLOR
            if (i == highlight_index and highlight_first_word)
            else SUBTITLE_PRIMARY_COLOR
        )

        draw.text(
            (current_x, y_center - (text_height // 2)),
            word,
            font=font,
            fill=color,
            stroke_width=SUBTITLE_STROKE_WIDTH,
            stroke_fill=SUBTITLE_STROKE_COLOR,
        )

        # Advance X position by word width + space
        current_x += draw.textlength(word + " ", font=font)

    img.save(output_path)


def build_caption_cues(word_blocks: list[dict], total_duration: float) -> list[dict]:
    """Group timestamped words without estimating or stretching speech timings."""
    if not math.isfinite(total_duration) or total_duration <= 0:
        raise ValueError("Audio duration must be positive and finite.")
    cues, pending = [], []
    last_end = 0.0
    for block in word_blocks:
        start, end = float(block["start"]), float(block["end"])
        text = block["text"].strip()
        if not text or len(text.split()) != 1:
            raise ValueError("Captions require individual word timestamps.")
        if (
            not all(math.isfinite(t) for t in (start, end))
            or start < last_end - 0.001
            or end < start
        ):
            raise ValueError("Word timestamps must be finite, ordered and nonoverlapping.")
        if start >= total_duration:
            break
        end = min(end, total_duration)
        # An isolated zero-duration token (often an article before a pause)
        # belongs in the next audible phrase, never in a zero-length card.
        timed = [w for w in pending if w["end"] > w["start"]]
        if timed and (
            len(pending) >= SUBTITLE_WORDS_PER_CHUNK or start - pending[-1]["end"] > 0.25
        ):
            cues.append(
                {
                    "start": timed[0]["start"],
                    "end": timed[-1]["end"],
                    "text": " ".join(w["text"] for w in pending),
                }
            )
            pending = []
        pending.append({"start": start, "end": end, "text": text})
        last_end = end
    if pending:
        timed = [w for w in pending if w["end"] > w["start"]]
        if timed:
            cues.append(
                {
                    "start": timed[0]["start"],
                    "end": timed[-1]["end"],
                    "text": " ".join(w["text"] for w in pending),
                }
            )
        elif cues:
            cues[-1]["text"] += " " + " ".join(w["text"] for w in pending)
    if not cues:
        raise ValueError("No valid timestamped words for captions.")
    if any(cue["end"] <= cue["start"] for cue in cues):
        raise ValueError("Provider returned a caption card with no timed speech.")
    return cues


def build_highlight_cues(word_blocks: list[dict], total_duration: float) -> list[dict]:
    """Keep each phrase visible while its active word follows provider timings."""
    phrases = build_caption_cues(word_blocks, total_duration)
    frames, word_cursor = [], 0
    for phrase in phrases:
        count = len(phrase["text"].split())
        words = word_blocks[word_cursor : word_cursor + count]
        word_cursor += count
        boundaries = sorted(
            {phrase["start"], phrase["end"]}
            | {
                min(phrase["end"], max(phrase["start"], float(word[key])))
                for word in words
                for key in ("start", "end")
            }
        )
        for start, end in zip(boundaries, boundaries[1:]):
            if end <= start:
                continue
            midpoint = (start + end) / 2
            active = next(
                (i for i, word in enumerate(words) if word["start"] <= midpoint < word["end"]), None
            )
            frame = {"start": start, "end": end, "text": phrase["text"], "highlight_index": active}
            if (
                frames
                and frames[-1]["text"] == frame["text"]
                and frames[-1]["highlight_index"] == active
                and frames[-1]["end"] == start
            ):
                frames[-1]["end"] = end
            else:
                frames.append(frame)
    return frames


def generate_subtitles_stream(
    sentence_blocks: list[dict], total_audio_duration: float, *, series=None
) -> Path:
    """Create caption images on an absolute timeline from TTS word boundaries."""
    cues = build_highlight_cues(sentence_blocks, total_audio_duration)
    # Each render owns its assets, including when another batch is still running.
    slides_dir = Path(tempfile.mkdtemp(prefix="captions_", dir=TEMP_DIR))
    part_label, continuation = None, None
    if series:
        from shorts_automation.stories.draft_story import validate_series_info

        series = validate_series_info(series)
        part_label = f"PART {series['part']}/{series['total']}"
        if series["part"] < series["total"]:
            continuation = f"NEXT: PART {series['part'] + 1} ON THIS CHANNEL"
    blank_path = slides_dir / "blank.png"
    if part_label:
        create_subtitle_image("", blank_path, part_label=part_label)
    else:
        Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0)).save(blank_path)
    timeline, cursor = [], 0.0
    for cue in cues:
        if cue["start"] > cursor:
            timeline.append((None, cursor, cue["start"]))
        timeline.append((cue, cue["start"], cue["end"]))
        cursor = cue["end"]
    # Clear the last caption for the remaining audio and the compiler's tail.
    timeline.append((None, cursor, total_audio_duration + 0.8))
    entries = []
    cta_start = max(0.0, total_audio_duration - 1.2)
    for cue, start, end in timeline:
        boundaries = [start, end]
        if continuation and start < cta_start < end:
            boundaries.insert(1, cta_start)
        for begin, finish in zip(boundaries, boundaries[1:]):
            footer = continuation if continuation and begin >= cta_start else None
            if cue or footer:
                slide = slides_dir / f"slide_{len(entries):04d}.png"
                options = {"part_label": part_label, "continuation": footer} if series else {}
                create_subtitle_image(
                    cue["text"] if cue else "",
                    slide,
                    highlight_index=cue["highlight_index"] if cue else None,
                    **options,
                )
            else:
                slide = blank_path
            entries.append((slide, finish - begin))
    concat_file = write_concat(entries, slides_dir / "captions.ffconcat")
    print(f"[+] Captions: {len(cues)} highlight states aligned to spoken words.")
    return concat_file


if __name__ == "__main__":
    dummy_blocks = [
        {"start": 0.2, "end": 0.5, "text": "Rule"},
        {"start": 0.5, "end": 0.8, "text": "number"},
        {"start": 0.8, "end": 1.0, "text": "one:"},
    ]
    cf = generate_subtitles_stream(dummy_blocks, 6.0)
    print("Concat script ready at:", cf)
