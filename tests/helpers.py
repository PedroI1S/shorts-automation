"""Local-only fakes shared by queue and production tests."""

import json
from pathlib import Path
from uuid import uuid4


class Harness:
    """Fake drafter/renderer that record calls and write realistic files."""

    def __init__(self, root):
        self.root = Path(root)
        self.drafts, self.renders = [], []
        self.draft_error = self.render_error = None
        self.words = 130

    def drafter(self, topic, *, gender="male"):
        self.drafts.append(topic)
        if self.draft_error:
            raise self.draft_error
        path = self.root / f"story_{uuid4().hex}.json"
        # Unique text per draft so story fingerprints never collide by accident.
        script = " ".join([uuid4().hex[:6]] + ["word"] * (self.words - 1))
        path.write_text(json.dumps({"title": "The Voice Behind The Door", "script": script, "protagonist_gender": gender, "narrator_gender": gender}))
        return path

    def renderer(self, story_file, **kwargs):
        self.renders.append((story_file, kwargs))
        if self.render_error:
            raise self.render_error
        output = self.root / f"video_{uuid4().hex}.mp4"
        output.write_bytes(b"video")
        output.with_suffix(".metadata.json").write_text(json.dumps({"job_id": "render-123"}))
        return output
