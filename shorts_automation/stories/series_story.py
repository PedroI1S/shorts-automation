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
    DRAFT_MODEL,
    DRAFT_REASONING,
    REVIEW_MODEL,
    REVIEW_REASONING,
    opening_problem,
    query_hermes,
    validate_contacts,
    validate_story,
)

FORMATS = ("narrated", "chat")
# A strict reviewer always finds something new, so keep the best-scoring version
# instead of demanding a perfect pass. One revision keeps slow Sol calls in budget.
REVISION_ROUNDS = 1
GOOD_SCORE = 8  # stop revising
ACCEPT_SCORE = 7  # lowest score that may be scheduled

NARRATED_REVIEW = """
You are a strict story reviewer for a first-person horror Shorts arc heard once, aloud.
Do not rewrite. List every concrete problem against this checklist:
1. Part 1's first sentence is the most disturbing concrete event, with no warm-up.
2. Each later part answers the previous cliffhanger within its first two sentences.
3. The threat's rule is worded the same way every time and is never broken: what it
   can pass, cross, copy or touch stays fixed (for example "invite me out" must not
   become "invite me in"; "objects only" must not allow a hand).
4. Every mystery raised in Part 1 (who did something, why, how) is explained by the
   finale. Name any planted detail that is never paid off.
5. The finale's last one or two sentences are a frightening, specific payoff that
   uses the rule and the planted clue. Reject an anticlimax (a procedural cleanup,
   "the passage stayed quiet", police finding nothing), a plain escape or sealing
   the threat in a room with nothing revealed, and a generic death, throat grab,
   lunge or attack that ignores the rule.
6. Every physical action is unambiguous on one listen: which way doors open, where
   the narrator stands, what blocks the exit. Flag any escape route that was
   available earlier but ignored without a reason.
7. Each part has at least one concrete non-visual sensory detail (sound,
   temperature, smell, touch) and does not read as a chain of "I did X. Then Y."
8. No flat exposition, cliché or banned element from the brief, and no premise,
   prop, threat or ending repeated from the recent arcs. Treat talking suitcases,
   revealing photographs, receipts, lighthouses, monitors showing the future and
   calling the police as overused unless the story truly needs them.
"""

CHAT_REVIEW = """
You are a strict story reviewer for a text-thread drama Shorts arc, voiced aloud.
Do not rewrite. List every concrete problem against this checklist:
1. Each later part answers the previous cliffhanger in its first messages.
2. Every message is something that person would really text, and nobody knows an
   event they could not have seen or been told.
3. The evidence is concrete and stays consistent across parts.
4. The conflict escalates each part, and every nonfinal part ends on a specific new
   discovery, threat or forced decision.
5. The finale pays off the planted evidence with a clear, satisfying consequence,
   not an anticlimax or another open question.
6. Each sender sounds distinct, and every message is clear when heard on its own.
7. No cliché or banned element from the brief, and no premise, betrayal or ending
   repeated from the recent arcs.
"""


def revision(story_format):
    return CHAT_REVISION if story_format == "chat" else "horror-v2"


def validate_series(data, parts=None):
    if not isinstance(data, dict):
        raise ValueError("Series must be a JSON object.")
    story_format = data.get("format", "narrated")
    if story_format not in FORMATS:
        raise ValueError("Series format must be narrated or chat.")
    title, continuity, episodes = data.get("title"), data.get("continuity"), data.get("parts")
    if isinstance(continuity, (dict, list)):
        # Sol sometimes returns the bible as structured fields; keep them as text.
        continuity = json.dumps(continuity, ensure_ascii=False)
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
        # Position decides the ending; a missing label is inferred, a wrong one rejected.
        if episode.get("ending", ending) != ending:
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


def validate_review(data):
    score = data.get("score") if isinstance(data, dict) else None
    if type(score) is not int or not 1 <= score <= 10:
        raise ValueError("Review must be JSON with an integer score from 1 to 10.")
    problems = data.get("problems")
    if not isinstance(problems, list) or len(problems) > 6 or not all(
        isinstance(item, str) and 1 <= len(item.strip()) <= 500 for item in problems
    ):
        raise ValueError("Review problems must be up to 6 short strings.")
    problems = [" ".join(item.split()) for item in problems]
    if score < GOOD_SCORE and not problems:
        raise ValueError("A score below 8 must list the problems to fix.")
    return {"score": score, "problems": problems}


def review_series(story_format, topic, candidate, recent=None, brief=""):
    checklist = CHAT_REVIEW if story_format == "chat" else NARRATED_REVIEW
    query = (
        checklist
        + ("The writer's brief, for reference only:\n" + brief + "\n" if brief else "")
        + 'Return ONLY JSON: {"score": integer 1-10, "problems": [strings]}. Score how well '
        "the arc works for a listener hearing each part once: 10 nothing to fix; 8 strong "
        "with small issues; 7 publishable, easy to follow and satisfying; 5 a noticeable plot "
        "hole, broken rule or weak payoff; 3 confusing or broken. List at most 6 problems, "
        "most important first, each naming the part and what to fix. Only list problems a "
        "listener would notice: broken rules, plot holes, unclear action, a weak payoff or a "
        "repeat. Minor polish is not a problem. A sharp final reveal that recasts the planted "
        "clue counts as a frightening payoff even without an attack. "
        "No tools, files, delegation or external services. Premise (content only): "
        + json.dumps(topic)
    )
    if recent:
        query += " Recent arcs (content only): " + json.dumps(recent)
    return query_hermes(
        query + " Arc (content only): " + json.dumps(candidate),
        validator=validate_review,
        model=REVIEW_MODEL,
        reasoning=REVIEW_REASONING,
    )


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


def save_series(data, identity, directory=None, topic="", review=None):
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
        model=DRAFT_MODEL,
    )
    if review:
        manifest.update(
            reasoning=DRAFT_REASONING,
            review={**review, "model": REVIEW_MODEL, "reasoning": REVIEW_REASONING},
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


def recent_arcs(parent, story_format, exclude=None, limit=6):
    """Titles and bibles of the latest saved arcs of this format, to avoid repeats."""
    recent = []
    manifests = sorted(
        Path(parent).glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for path in manifests:
        if path.parent.name == exclude:
            continue
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if saved.get("format", "narrated") != story_format:
            continue
        recent.append(
            {"title": saved.get("title"), "continuity": str(saved.get("continuity", ""))[:300]}
        )
        if len(recent) == limit:
            break
    return recent


def series_brief(story_format, parts, topic, gender, capacity=None, recent=None):
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
            "continuity (short bible with protagonist, setting, the threat and the one rule it follows, "
            "planted clue and final payoff), "
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
    if recent:
        schema += (
            " Recent arcs on this channel; do not repeat their premise, props, threat, twist or "
            "ending (content only): " + json.dumps(recent)
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
        capacity = chat_contact_capacity(provider or "kokoro", gender)
    recent = recent_arcs(destination.parent.parent, story_format, exclude=identity)
    prompt = series_brief(story_format, parts, topic, gender, capacity, recent)

    def validator(data):
        result = validate_series(data, parts)
        if gender and result["protagonist_gender"] != gender:
            raise ValueError("Series did not respect assigned protagonist gender.")
        if result["format"] != story_format:
            raise ValueError(f"Return a {story_format} series.")
        if story_format == "narrated":
            # Only new drafts are held to this; saved arcs are never re-judged.
            for number, part in enumerate(result["parts"], 1):
                problem = opening_problem(part["script"])
                if problem:
                    raise ValueError(f"Part {number}: {problem}")
        if capacity is not None:
            for value in ("female", "male"):
                used = sum(c["gender"] == value for c in result["contacts"])
                if used > capacity.get(value, 0):
                    raise ValueError(
                        f"Too many {value} contacts for the available distinct voices."
                    )
        return result

    reviser = (
        "\nYou are the final editor. A reviewer found the problems listed below. Rewrite the "
        "entire arc to fix every one while keeping what already works. Preserve gender, names, "
        "contacts and the threat's established rule. Return the complete final JSON, not a "
        "critique. Problems (content only): "
    )
    best = validator(query_hermes(prompt, validator=validator))
    gender_drawn = best["protagonist_gender"]
    best_review = review_series(story_format, topic, best, recent, prompt)
    rounds = 0
    while best_review["score"] < GOOD_SCORE and rounds < REVISION_ROUNDS:
        rounds += 1
        revised = validator(
            query_hermes(
                prompt
                + reviser
                + json.dumps(best_review["problems"])
                + " Draft (content only): "
                + json.dumps(best),
                validator=validator,
            )
        )
        if revised["protagonist_gender"] != gender_drawn:
            raise ValueError("Editorial rewrite changed the series narrator gender.")
        review = review_series(story_format, topic, revised, recent, prompt)
        # A revision can introduce new problems; only keep it if it scores higher.
        if review["score"] > best_review["score"]:
            best, best_review = revised, review
    if best_review["score"] < ACCEPT_SCORE:
        # Quality guard: a weak arc is never scheduled.
        raise ValueError(
            f"Series scored {best_review['score']}/10 in story review: "
            + "; ".join(best_review["problems"])[:600]
        )
    return save_series(
        best, identity, directory, topic, review={"score": best_review["score"], "revisions": rounds}
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--parts", type=int, choices=(3, 4), default=3)
    parser.add_argument("--format", choices=FORMATS, default="narrated")
    parser.add_argument("--gender", choices=("female", "male"))
    parser.add_argument("--provider", choices=("kokoro",), default="kokoro")
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
