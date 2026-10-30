"""Offline serial-story fixtures; no model, speech, source or upload requests."""

import json
from pathlib import Path
from uuid import uuid4

from shorts_automation.automation import series_queue
from shorts_automation.automation.orchestrator import process_one
from shorts_automation.stories.draft_story import validate_story
from shorts_automation.stories.series_story import save_series


def arc(parts=3, gender="female", token="fixture"):
    return {
        "title": "The Voice Beneath My Floor",
        "continuity": "Mara hears her missing sister beneath the apartment floor. The voice can only repeat recorded speech. Her failed escape exposes the recorder; the finale pays off its reversed tape.",
        "protagonist_gender": gender,
        "narrator_gender": gender,
        "parts": [
            {
                "title": "The Recording Beneath My Floor",
                "script": f"I checked recording {token} number {number}. The voice repeated my last words, but the tape had not started moving. I pulled the plug and heard the next sentence from beneath my feet.",
                "ending": "finale" if number == parts else "cliffhanger",
            }
            for number in range(1, parts + 1)
        ],
    }


class SeriesHarness:
    def __init__(self, root):
        self.root = Path(root)
        self.drafts, self.renders = [], []
        self.render_error = None
        self.fail_part = None

    def drafter(self, topic):
        path = self.root / f"standalone_{uuid4().hex}.json"
        path.write_text(
            json.dumps(
                {
                    "title": "The Knocking Behind My Door",
                    "script": f"I heard {uuid4().hex} knocking. It came from inside my locked suitcase.",
                }
            )
        )
        return path

    def series_drafter(self, topic, *, parts, identity):
        self.drafts.append((topic, parts, identity))
        return save_series(arc(parts, token=identity), identity, self.root / "series", topic)

    def renderer(self, story_file, **kwargs):
        story = validate_story(json.loads(Path(story_file).read_text()))
        self.renders.append(story)
        if self.render_error and story.get("series", {}).get("part") == self.fail_part:
            raise self.render_error
        identity = uuid4().hex
        audio = self.root / f"audio_{identity}.mp3"
        audio.write_bytes(b"audio fixture")
        audio.with_suffix(".json").write_text(json.dumps({"voice": "same-configured-voice"}))
        output = self.root / f"output_{identity}.mp4"
        output.write_bytes(b"render fixture")
        output.with_suffix(".metadata.json").write_text(
            json.dumps(
                {
                    "job_id": identity,
                    "story": story,
                    "narration": str(audio),
                    "tts_provider": kwargs["tts_provider"],
                }
            )
        )
        return output


def queued_series(queue, parts=3):
    jobs = [queue.enqueue(f"Premise {uuid4().hex}", "fish") for _ in range(parts)]
    return series_queue.link(queue, jobs), jobs


def render_series(queue, usage, harness, parts=3):
    identity, jobs = queued_series(queue, parts)
    for job in jobs:
        process_one(
            queue,
            usage,
            harness.drafter,
            harness.renderer,
            include=[job],
            series_drafter=harness.series_drafter,
        )
    return identity, jobs
