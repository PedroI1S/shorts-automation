from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pipeline
import video_compiler
from tts_engine import estimate_duration
from usage_store import UsageStore


def write_story(directory, words):
    path = Path(directory) / 'draft.json'
    path.write_text(json.dumps({'title': 'The Voice Behind The Door', 'script': ' '.join(['word'] * words)}))
    return path


class PreTtsDurationTests(unittest.TestCase):
    def test_overlong_fish_script_rejected_before_tts_and_reservation(self):
        # 150 words passes draft validation but at Fish's measured pace is ~58.7s with tail.
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp) / 'db.sqlite3')
            story = write_story(temp, 150)
            with patch('usage_store.UsageStore', return_value=store), \
                 patch.object(pipeline, 'generate_speech') as speech, redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'no TTS call made'):
                    pipeline.run_pipeline(story_file=story, tts_provider='fish')
                speech.assert_not_called()
            store.begin(' '.join(['word'] * 150))  # Story was never reserved.

    def test_known_good_fish_length_reaches_tts(self):
        # 146 words rendered at 56.29s on the real Fish voice; it must not be rejected.
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp) / 'db.sqlite3')
            story = write_story(temp, 146)
            with patch('usage_store.UsageStore', return_value=store), \
                 patch.object(pipeline, 'generate_speech', side_effect=RuntimeError('stop here')) as speech, \
                 redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'stop here'):
                    pipeline.run_pipeline(story_file=story, tts_provider='fish')
                speech.assert_called_once()

    def test_estimate_counts_prepared_words_and_rejects_unknown_provider(self):
        self.assertAlmostEqual(estimate_duration('one  two\n three', 'edge'), 3 / 2.5)
        with self.assertRaises(ValueError):
            estimate_duration('hello', 'mystery')


class NarrationMixTests(unittest.TestCase):
    def test_background_audio_mix_does_not_attenuate_narration(self):
        with patch.object(video_compiler, 'has_audio_stream', return_value=True), \
             patch.object(video_compiler.subprocess, 'run', return_value=MagicMock(returncode=0)) as run, \
             redirect_stdout(io.StringIO()):
            video_compiler.compile_short(Path('bg.mp4'), 0, Path('n.mp3'), 10, Path('c.ffconcat'), 'x.mp4')
        cmd = run.call_args.args[0]
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('amix=', graph)
        self.assertIn('normalize=0', graph)


if __name__ == '__main__':
    unittest.main()
