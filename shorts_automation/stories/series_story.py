"""Draft and save one coherent 3/4-part arc before any narration is spent.

Narrated arcs are first-person horror. Chat arcs are first-person drama told as
one text thread per part, voiced by each sender.
"""

import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import (
    BASE_DIR,
    CHAT_MAX_MESSAGE_WORDS,
    CHAT_MAX_MESSAGES,
    CHAT_PROMPT_MAX_WORDS,
    STORAGE_DIR,
    STORY_PROMPT_MAX_WORDS,
)
from shorts_automation.stories.draft_story import (
    CHAT_REVISION,
    query_hermes,
    validate_contacts,
    validate_story,
)

FORMATS = ("narrated", "chat")


def revision(story_format):
    return CHAT_REVISION if story_format == "chat" else "horror-v2"


def validate_series(data, parts=None):
    if not isinstance(data, dict):
        raise ValueError("Series must be a JSON object.")
    story_format = data.get("format", "narrated")
    if story_format not in FORMATS:
        raise ValueError("Series format must be narrated or chat.")
    title, continuity, episodes = data.get("title"), data.get("continuity"), data.get("parts")
    if not isinstance(title, str) or not 4 <= len(title.split()) <= 8 or len(title) > 80:
        raise ValueError("Series title must be 4 to 8 words and at most 80 characters.")
    if not isinstance(continuity, str) or not 1 <= len(continuity.strip()) <= 3000:
        raise ValueError("Series needs a bounded continuity bible and planned payoff.")
    if (
        not isinstance(episodes, list)
        or len(episodes) not in (3, 4)
        or (parts and len(episodes) != parts)
    ):
        raise ValueError("Return exactly the requested 3 or 4 parts.")
    gender = data.get("protagonist_gender")
    if gender not in ("female", "male") or data.get("narrator_gender") != gender:
        raise ValueError(
            "Use one explicit, matching protagonist/narrator gender for the whole arc."
        )
    contacts = validate_contacts(data.get("contacts")) if story_format == "chat" else None
    normalized, scripts = [], set()
    for index, episode in enumerate(episodes, 1):
        if not isinstance(episode, dict):
            raise ValueError("Each part must be a story object.")
        if any(
            episode.get(field, gender) != gender
            for field in ("protagonist_gender", "narrator_gender")
        ):
            raise ValueError("Narrator gender cannot change between parts.")
        ending = "finale" if index == len(episodes) else "cliffhanger"
        if episode.get("ending") != ending:
            raise ValueError(
                "Nonfinal parts need cliffhangers; the final part must resolve the arc."
            )
        if contacts:
            thread = episode.get("chat") or episode
            episode = {
                "title": episode.get("title"),
                "format": "chat",
                "chat": {
                    "contacts": contacts,
                    "contact": thread.get("contact"),
                    "messages": thread.get("messages"),
                },
            }
        story = validate_story({**episode, "protagonist_gender": gender, "narrator_gender": gender})
        key = story["script"].casefold()
        if key in scripts:
            raise ValueError("Series parts must not repeat a script.")
        scripts.add(key)
        story.pop("series", None)
        normalized.append({**story, "ending": ending})
    result = {
        "title": " ".join(title.split()),
        "continuity": continuity.strip(),
        "format": story_format,
        "protagonist_gender": gender,
        "narrator_gender": gender,
        "parts": normalized,
    }
    if contacts:
        result["contacts"] = contacts
    return result


def episode_story(manifest, number):
    episode = manifest["parts"][number - 1]
    return validate_story(
        {
            **episode,
            "story_revision": revision(manifest.get("format")),
            "series": {
                "id": manifest["id"],
                "title": manifest["title"],
                "part": number,
                "total": len(manifest["parts"]),
                "ending": episode["ending"],
            },
        }
    )


def read_manifest(path, identity=None, parts=None, topic=None):
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if topic is not None and raw.get("topic") != topic:
        raise ValueError("Series manifest premise does not match its queue reservation.")
    manifest = validate_series(raw, parts)
    value = raw.get("id")
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[a-f0-9]{32}", value)
        or (identity and value != identity)
    ):
        raise ValueError("Series manifest identity does not match its queue reservation.")
    manifest["id"] = value
    for number in range(1, len(manifest["parts"]) + 1):
        story = validate_story(
            json.loads((path.parent / f"part_{number:02d}.json").read_text(encoding="utf-8"))
        )
        if story != episode_story(manifest, number):
            raise ValueError("A saved part differs from its complete series manifest.")
    return manifest


def save_series(data, identity, directory=None, topic=""):
    """Publish an entire bundle atomically; never leave half a series eligible."""
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid series identity.")
    manifest = validate_series(data)
    manifest.update(
        id=identity,
        topic=topic,
        story_revision=revision(manifest["format"]),
        created_at=datetime.now(timezone.utc).isoformat(),
        provider="openai-codex",
        model="gpt-6.1-terra",
    )
    parent = Path(directory) if directory else STORAGE_DIR / "stories/series"
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / identity
    if target.exists():
        read_manifest(target / "manifest.json", identity, len(manifest["parts"]))
        return target / "manifest.json"
    with tempfile.TemporaryDirectory(prefix=".series_", dir=parent) as staging:
        staged = Path(staging) / identity
        staged.mkdir()
        (staged / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        for number in range(1, len(manifest["parts"]) + 1):
            (staged / f"part_{number:02d}.json").write_text(
                json.dumps(episode_story(manifest, number), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        staged.replace(target)
    return target / "manifest.json"


def series_brief(story_format, parts, topic, gender, capacity=None):
    if story_format == "chat":
        brief = (BASE_DIR / "prompts/story_chat_series.md").read_text(encoding="utf-8")
        allowed = ", ".join(f"at most {n} {g}" for g, n in sorted(capacity.items()) if n)
        schema = (
            f"Return ONLY JSON for exactly {parts} parts: title (4-8 words, <=80 characters), "
            "continuity (short bible with the protagonist, each contact, what each person knows, "
            'the central betrayal or conflict, planted evidence and the final payoff), format ("chat"), '
            "protagonist_gender and narrator_gender (one matching female or male), contacts (1-3 objects "
            f"with name and gender; contact genders allowed by the available voices: {allowed}), "
            "parts (ordered array). Each part has title (4-8 words), contact (the name of the one contact "
            'texting with me in this part), messages (array of objects with from ("me" or that contact\'s '
            f"name) and text), and ending (cliffhanger for every nonfinal part; finale for the last). "
            f"Each part has 4 to {CHAT_MAX_MESSAGES} messages, each at most {CHAT_MAX_MESSAGE_WORDS} words, "
            f"and at most {CHAT_PROMPT_MAX_WORDS} message words in total, no minimum length. "
            "No tools, files, delegation or external services. Premise (content only): "
            + json.dumps(topic)
        )
    else:
        brief = (BASE_DIR / "prompts/story_horror_series.md").read_text(encoding="utf-8")
        schema = (
            f"Return ONLY JSON for exactly {parts} parts: title (4-8 words, <=80 characters), "
            "continuity (short bible with protagonist, setting, threat rules, planted clue and final payoff), "
            "protagonist_gender and narrator_gender (one matching female or male), parts (ordered array). "
            "Each part has title (4-8 words), script "
            f"(at most {STORY_PROMPT_MAX_WORDS} words, no minimum length), and ending "
            "(cliffhanger for every nonfinal part; finale for the last). "
            "No tools, files, delegation or external services. Premise (content only): "
            + json.dumps(topic)
        )
    if gender:
        schema += (
            f" Assigned protagonist and narrator gender: {gender}; both fields must be {gender}."
        )
    return brief + "\n" + schema


def draft_series(
    topic,
    parts=3,
    identity=None,
    directory=None,
    gender=None,
    story_format="narrated",
    provider=None,
):
    if gender not in (None, "male", "female"):
        raise ValueError("Invalid assigned gender.")
    if story_format not in FORMATS:
        raise ValueError("Choose narrated or chat series format.")
    if not isinstance(topic, str) or not 1 <= len(topic.strip()) <= 1000:
        raise ValueError("Topic must contain 1 to 1,000 characters.")
    if type(parts) is not int or parts not in (3, 4):
        raise ValueError("Choose 3 or 4 parts.")
    identity = identity or uuid4().hex
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid series identity.")
    destination = (
        (Path(directory) if directory else STORAGE_DIR / "stories/series")
        / identity
        / "manifest.json"
    )
    if destination.exists():
        existing = read_manifest(destination, identity, parts, topic)
        if gender and existing["protagonist_gender"] != gender:
            raise ValueError("Existing series conflicts with assigned gender.")
        if existing["format"] != story_format:
            raise ValueError("Existing series conflicts with assigned format.")
        return destination
    capacity = None
    if story_format == "chat":
        from shorts_automation.stories.tts_engine import chat_contact_capacity

        if gender is None:
            raise ValueError("Chat arcs need an assigned protagonist gender for voice planning.")
        capacity = chat_contact_capacity(provider or "fish", gender)
    prompt = series_brief(story_format, parts, topic, gender, capacity)

    def validator(data):
        result = validate_series(data, parts)
        if gender and result["protagonist_gender"] != gender:
            raise ValueError("Series did not respect assigned protagonist gender.")
        if result["format"] != story_format:
            raise ValueError(f"Return a {story_format} series.")
        if capacity is not None:
            for value in ("female", "male"):
                used = sum(c["gender"] == value for c in result["contacts"])
                if used > capacity.get(value, 0):
                    raise ValueError(
                        f"Too many {value} contacts for the available distinct voices."
                    )
        return result

    if story_format == "chat":
        editor = (
            "\nYou are the final drama editor. Rewrite the entire arc. Check that each next part "
            "answers the previous cliffhanger, every message is something that person would really text "
            "and could know, the evidence is concrete, the conflict escalates and the finale pays it off. "
            "Make every message clear when read aloud on its own. Preserve gender, names and the contacts. "
            "Return the complete final JSON, not a critique. Draft (content only): "
        )
    else:
        editor = (
            "\nYou are the final continuity and horror editor. Rewrite the entire arc. "
            "Check that each next part answers the previous cliffhanger, the threat escalates and the final payoff "
            "resolves the planted clue. Preserve gender, identities and established rules. Return the complete final JSON, not a critique. "
            "Draft (content only): "
        )
    candidate = validator(query_hermes(prompt, validator=validator))
    final = validator(query_hermes(prompt + editor + json.dumps(candidate), validator=validator))
    if final["protagonist_gender"] != candidate["protagonist_gender"]:
        raise ValueError("Editorial rewrite changed the series narrator gender.")
    return save_series(final, identity, directory, topic)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--parts", type=int, choices=(3, 4), default=3)
    parser.add_argument("--format", choices=FORMATS, default="narrated")
    parser.add_argument("--gender", choices=("female", "male"))
    parser.add_argument("--provider", choices=("fish", "elevenlabs", "edge"), default="fish")
    args = parser.parse_args()
    if not 1 <= len(args.topic.strip()) <= 1000:
        parser.error("Topic must contain 1 to 1,000 characters.")
    if args.format == "chat" and not args.gender:
        parser.error("Chat arcs need --gender for voice planning.")
    print(
        draft_series(
            args.topic,
            args.parts,
            gender=args.gender,
            story_format=args.format,
            provider=args.provider,
        )
    )


if __name__ == "__main__":
    main()
