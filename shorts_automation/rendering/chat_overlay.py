"""Text-thread overlay for chat Shorts.

Each message bubble appears when its sender starts speaking, the spoken word is
marked with the channel's moving yellow highlight, and a typing indicator fills
the pause before the contact answers. Older bubbles scroll off the top of the
card. Frames are full 1080x1920 transparent PNGs on the same ffconcat timeline
as the standard captions, so the compiler is unchanged.
"""

import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import (
    CHAT_BOLD_FONT_PATH,
    CHAT_FONT_PATH,
    NARRATION_TAIL_SECONDS,
    SUBTITLE_HIGHLIGHT_COLOR,
    TEMP_DIR,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from shorts_automation.rendering.subtitle_engine import draw_label, write_concat

CARD_LEFT, CARD_RIGHT, CARD_TOP, CARD_MAX_BOTTOM = 70, 1010, 250, 1330
HEADER_HEIGHT = 170
BODY_PADDING = 28
BUBBLE_FONT_SIZE = 44
BUBBLE_MAX_TEXT_WIDTH = 600
BUBBLE_PAD_X, BUBBLE_PAD_Y, BUBBLE_RADIUS = 30, 18, 36
BUBBLE_GAP, SENDER_SWITCH_GAP = 12, 26
LINE_HEIGHT = int(BUBBLE_FONT_SIZE * 1.28)
ME_FILL, ME_TEXT = (10, 132, 255, 255), (255, 255, 255, 255)
THEM_FILL, THEM_TEXT = (233, 233, 235, 255), (0, 0, 0, 255)
CARD_FILL, HEADER_FILL = (255, 255, 255, 250), (246, 246, 248, 250)
MUTED = (142, 142, 147, 255)
TYPING_MIN_SECONDS = 0.4


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default(size)


def _norm(word):
    return re.sub(r"[^a-z0-9]", "", word.casefold())


def map_spoken_words(display, spoken):
    """Map provider word tokens onto the words drawn in the bubble.

    Providers can split or merge tokens ("3am", hyphens, punctuation), so this
    walks forward matching normalized text and falls back to proportional
    position. It only affects which word is highlighted, never timing.
    """
    if len(display) == len(spoken):
        return list(range(len(display)))
    mapping, cursor = [], 0
    for index, word in enumerate(spoken):
        target = _norm(word)
        found = None
        if mapping and target:
            # A provider split one shown word ("3am" -> "3", "am"): stay on it.
            previous = _norm(display[mapping[-1]])
            if target in previous and not previous.startswith(target):
                found = mapping[-1]
        for candidate in range(cursor, min(len(display), cursor + 3)) if found is None else ():
            shown = _norm(display[candidate])
            if target and shown and (shown.startswith(target) or target.startswith(shown)):
                found = candidate
                break
        if found is None:
            found = min(len(display) - 1, max(cursor, index * len(display) // len(spoken)))
        mapping.append(found)
        cursor = found + 1 if found + 1 < len(display) else found
    return mapping


def _wrap(words, font):
    lines, current = [], []
    for index, word in enumerate(words):
        trial = " ".join(words[i] for i in current + [index])
        if current and font.getlength(trial) > BUBBLE_MAX_TEXT_WIDTH:
            lines.append(current)
            current = [index]
        else:
            current.append(index)
    if current:
        lines.append(current)
    return lines


class ChatCard:
    def __init__(self, story):
        chat = story["chat"]
        self.contact = chat["contact"]
        self.messages = chat["messages"]
        self.font = _font(CHAT_FONT_PATH, BUBBLE_FONT_SIZE)
        self.name_font = _font(CHAT_BOLD_FONT_PATH or CHAT_FONT_PATH, 38)
        self.initial_font = _font(CHAT_BOLD_FONT_PATH or CHAT_FONT_PATH, 44)
        self.words = [m["text"].split() for m in self.messages]
        self.lines = [_wrap(words, self.font) for words in self.words]

    def bubble_size(self, index):
        lines = self.lines[index]
        width = max(
            self.font.getlength(" ".join(self.words[index][i] for i in line)) for line in lines
        )
        return int(width) + 2 * BUBBLE_PAD_X, len(lines) * LINE_HEIGHT + 2 * BUBBLE_PAD_Y

    def _layout(self, visible, typing):
        """Bottom-up placement of the newest bubbles that fit inside the card."""
        items = [("message", i) for i in range(visible)]
        if typing:
            items.append(("typing", None))
        heights, total, chosen = [], 0, []
        body_limit = CARD_MAX_BOTTOM - CARD_TOP - HEADER_HEIGHT - 2 * BODY_PADDING
        for kind, index in reversed(items):
            height = self.bubble_size(index)[1] if kind == "message" else 76
            sender = self.messages[index]["from"] if kind == "message" else self.contact
            gap = 0
            if chosen:
                gap = SENDER_SWITCH_GAP if sender != chosen[0][2] else BUBBLE_GAP
            if chosen and total + gap + height > body_limit:
                break
            total += gap + height
            chosen.insert(0, (kind, index, sender))
            heights.insert(0, (height, gap))
        return chosen, heights, total

    def render(self, path, visible, active=None, typing=False, part_label=None, footer=None):
        image = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if part_label:
            draw_label(draw, part_label, 160)
        chosen, heights, total = self._layout(visible, typing)
        bottom = CARD_TOP + HEADER_HEIGHT + 2 * BODY_PADDING + max(total, 90)
        draw.rounded_rectangle((CARD_LEFT, CARD_TOP, CARD_RIGHT, bottom), 44, fill=CARD_FILL)
        draw.rounded_rectangle(
            (CARD_LEFT, CARD_TOP, CARD_RIGHT, CARD_TOP + HEADER_HEIGHT), 44, fill=HEADER_FILL
        )
        draw.rectangle(
            (CARD_LEFT, CARD_TOP + HEADER_HEIGHT - 44, CARD_RIGHT, CARD_TOP + HEADER_HEIGHT),
            fill=HEADER_FILL,
        )
        draw.line(
            (CARD_LEFT, CARD_TOP + HEADER_HEIGHT, CARD_RIGHT, CARD_TOP + HEADER_HEIGHT),
            fill=(215, 215, 220, 255),
            width=2,
        )
        # Generic back chevron, avatar initial and contact name.
        x, y = CARD_LEFT + 44, CARD_TOP + 62
        draw.line((x + 18, y - 22, x, y, x + 18, y + 22), fill=ME_FILL, width=6, joint="curve")
        center = (VIDEO_WIDTH // 2, CARD_TOP + 62)
        draw.ellipse(
            (center[0] - 42, center[1] - 42, center[0] + 42, center[1] + 42), fill=(160, 166, 178)
        )
        draw.text(
            center, self.contact[0].upper(), font=self.initial_font, fill="white", anchor="mm"
        )
        draw.text(
            (center[0], CARD_TOP + 136),
            self.contact,
            font=self.name_font,
            fill="black",
            anchor="mm",
        )
        top = CARD_TOP + HEADER_HEIGHT + BODY_PADDING
        for (kind, index, sender), (height, gap) in zip(chosen, heights):
            top += gap
            if kind == "typing":
                self._typing(draw, top)
            else:
                highlight = active[1] if active and active[0] == index else None
                self._bubble(draw, index, top, highlight)
            top += height
        if footer:
            draw_label(draw, footer, 1450)
        image.save(path)

    def _bubble(self, draw, index, top, highlight):
        mine = self.messages[index]["from"] == "me"
        width, height = self.bubble_size(index)
        left = CARD_RIGHT - 34 - width if mine else CARD_LEFT + 34
        draw.rounded_rectangle(
            (left, top, left + width, top + height),
            BUBBLE_RADIUS,
            fill=ME_FILL if mine else THEM_FILL,
        )
        words = self.words[index]
        for row, line in enumerate(self.lines[index]):
            x, y = left + BUBBLE_PAD_X, top + BUBBLE_PAD_Y + row * LINE_HEIGHT
            for position in line:
                word = words[position]
                length = self.font.getlength(word)
                color = ME_TEXT if mine else THEM_TEXT
                if position == highlight:
                    draw.rounded_rectangle(
                        (x - 6, y + 2, x + length + 6, y + LINE_HEIGHT - 2),
                        10,
                        fill=SUBTITLE_HIGHLIGHT_COLOR,
                    )
                    color = (0, 0, 0, 255)
                draw.text((x, y + 4), word, font=self.font, fill=color)
                x += length + self.font.getlength(" ")

    def _typing(self, draw, top):
        left = CARD_LEFT + 34
        draw.rounded_rectangle((left, top, left + 130, top + 76), 38, fill=THEM_FILL)
        for dot in range(3):
            cx = left + 38 + dot * 27
            draw.ellipse((cx - 9, top + 29, cx + 9, top + 47), fill=MUTED)


def build_chat_states(story, words, timeline, duration, series=None):
    """Return [(state, start, end)] covering narration plus the compiler tail."""
    messages = story["chat"]["messages"]
    spoken = []  # (start, end, message index, highlighted bubble word)
    for index in range(len(messages)):
        tokens = [w for w in words if w["message"] == index]
        if tokens:
            mapping = map_spoken_words(messages[index]["text"].split(), [w["text"] for w in tokens])
            spoken += [(w["start"], w["end"], index, m) for w, m in zip(tokens, mapping)]
    end = duration + NARRATION_TAIL_SECONDS
    cta_start = None
    if series and series["part"] < series["total"]:
        cta_start = max(0.0, duration - 1.2)
    typing = [
        (timeline[i - 1]["end"], timeline[i]["start"])
        for i in range(1, len(timeline))
        if messages[i]["from"] != "me"
        and messages[i - 1]["from"] == "me"
        and timeline[i]["start"] - timeline[i - 1]["end"] >= TYPING_MIN_SECONDS
    ]
    points = {0.0, end, *(item["start"] for item in timeline)}
    points |= {t for w in words for t in (w["start"], w["end"])}
    points |= {t for span in typing for t in span}
    if cta_start is not None:
        points.add(cta_start)
    points = sorted(p for p in points if 0.0 <= p <= end)
    states = []
    for start, finish in zip(points, points[1:]):
        if finish - start <= 1e-6:
            continue
        middle = (start + finish) / 2
        visible = sum(item["start"] <= middle for item in timeline)
        active = next(((m, w) for a, b, m, w in spoken if a <= middle < b), None)
        state = (
            visible,
            active,
            any(a <= middle < b for a, b in typing),
            cta_start is not None and middle >= cta_start,
        )
        if states and states[-1][0] == state and abs(states[-1][2] - start) < 1e-6:
            states[-1] = (state, states[-1][1], finish)
        else:
            states.append((state, start, finish))
    return states


def generate_chat_stream(story, words, timeline, duration, *, series=None):
    """Render each distinct chat state once and place it on an ffconcat timeline."""
    if not timeline or duration <= 0:
        raise ValueError("Chat overlay needs a positive voiced timeline.")
    part_label = continuation = None
    if series:
        from shorts_automation.stories.draft_story import validate_series_info

        series = validate_series_info(series)
        part_label = f"PART {series['part']}/{series['total']}"
        if series["part"] < series["total"]:
            continuation = f"NEXT: PART {series['part'] + 1} ON THIS CHANNEL"
    card = ChatCard(story)
    directory = Path(tempfile.mkdtemp(prefix="captions_chat_", dir=TEMP_DIR))
    rendered, entries = {}, []
    for state, start, end in build_chat_states(story, words, timeline, duration, series):
        if state not in rendered:
            path = directory / f"chat_{len(rendered):04d}.png"
            visible, active, typing, cta = state
            card.render(
                path,
                visible,
                active,
                typing,
                part_label=part_label,
                footer=continuation if cta else None,
            )
            rendered[state] = path
        entries.append((rendered[state], end - start))
    concat = write_concat(entries, directory / "captions.ffconcat")
    print(f"[+] Chat overlay: {len(rendered)} frames across {len(entries)} timed states.")
    return concat
