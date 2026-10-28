from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pipeline
from usage_store import UsageStore, AlreadyUsed


class PipelineUsageTests(unittest.TestCase):
    def test_duplicate_story_stops_before_tts(self):
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp)/'db.sqlite3')
            script = 'unique ' * 130
            store.begin(script)
            story = Path(temp)/'draft.json'
            story.write_text(json.dumps({'title':'The Voice Behind The Door','script':script}))
            with patch('usage_store.UsageStore', return_value=store), \
                 patch.object(pipeline, 'generate_speech') as speech, redirect_stdout(io.StringIO()):
                with self.assertRaises(AlreadyUsed):
                    pipeline.run_pipeline(story_file=story)
                speech.assert_not_called()

    def test_tts_failure_releases_story_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp)/'db.sqlite3')
            script = 'another ' * 130
            story = Path(temp)/'draft.json'
            story.write_text(json.dumps({'title':'The Voice Behind The Door','script':script}))
            with patch('usage_store.UsageStore', return_value=store), \
                 patch.object(pipeline, 'generate_speech', side_effect=RuntimeError('offline')), \
                 redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    pipeline.run_pipeline(story_file=story)
            store.begin(script)  # Retry remains possible after an ordinary failure.
