import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import DEFAULT_VOICE, KOKORO_VOICES
from shorts_automation.stories import tts_engine as tts
from shorts_automation.stories.kokoro_worker import tokens_to_words

REAL_RUN = subprocess.run


def token(text, start, end, whitespace=" "):
    return SimpleNamespace(text=text, start_ts=start, end_ts=end, whitespace=whitespace)


class KokoroTokenTests(unittest.TestCase):
    def test_punctuation_joins_words_and_chunk_offset_is_absolute(self):
        tokens = [
            token("Don't", 0.1, 0.3),
            token("open", 0.3, 0.5, ""),
            token(",", 0.5, 0.55),
            token('"', None, None, ""),
            token("please", 0.6, 0.9, ""),
            token(".", 0.9, 1.0, ""),
        ]
        self.assertEqual(
            tokens_to_words(tokens, 2.0, 1.2),
            [
                {"text": "Don't", "start": 2.1, "end": 2.3},
                {"text": "open,", "start": 2.3, "end": 2.5},
                {"text": '"please.', "start": 2.6, "end": 2.9},
            ],
        )

    def test_missing_timestamps_are_bounded_by_neighbours(self):
        tokens = [token("one", 0.0, 0.2), token("2026", None, None), token("three", 0.6, 0.8)]
        words = tokens_to_words(tokens, 0, 1.0)
        self.assertEqual(words[1], {"text": "2026", "start": 0.2, "end": 0.6})
        tokens = [token("last", 0.1, None)]
        self.assertEqual(tokens_to_words(tokens, 0, 0.5)[0]["end"], 0.5)


class KokoroSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.worker_calls = []
        for patcher in (
            patch.object(tts, "AUDIO_DIR", root),
            patch.object(tts, "TEMP_DIR", root),
            patch.object(tts, "KOKORO_PYTHON", Path(sys.executable)),
            patch.object(tts.subprocess, "run", side_effect=self.fake_run),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def fake_run(self, command, **kwargs):
        if command[0] != sys.executable:
            return REAL_RUN(command, **kwargs)  # ffmpeg/ffprobe stay real
        self.assertEqual(command[1:3], ["-I", str(tts.WORKER)])
        request = json.loads(Path(command[3]).read_text(encoding="utf-8"))
        self.worker_calls.append(request)
        items = []
        for item in request["items"]:
            REAL_RUN(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=0.5",
                    item["wav"],
                ],
                check=True,
            )
            words = [
                {"text": w, "start": i * 0.1, "end": (i + 1) * 0.1}
                for i, w in enumerate(item["text"].split())
            ]
            items.append({"wav": item["wav"], "duration": 0.5, "words": words})
        Path(request["result"]).write_text(json.dumps({"items": items}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_batch_runs_worker_once_and_later_calls_reuse_cache(self):
        with redirect_stdout(io.StringIO()):
            tts.synthesize_kokoro([("Hello there.", "am_fenrir"), ("Who is it?", "af_heart")])
            path, duration, words = tts.generate_speech("Hello  there.", "am_fenrir")
        self.assertEqual(len(self.worker_calls), 1)
        self.assertEqual(len(self.worker_calls[0]["items"]), 2)
        self.assertEqual(self.worker_calls[0]["repo"], "hexgrad/Kokoro-82M")
        self.assertEqual([w["text"] for w in words], ["Hello", "there."])
        self.assertGreater(duration, 0.4)
        saved = json.loads(path.with_suffix(".json").read_text())
        self.assertEqual((saved["provider"], saved["voice"]), ("kokoro", "am_fenrir"))

    def test_empty_timestamps_are_refused(self):
        def no_words(command, **kwargs):
            result = self.fake_run(command, **kwargs)
            if command[0] == sys.executable:
                path = Path(self.worker_calls[-1]["result"])
                data = json.loads(path.read_text())
                data["items"][0]["words"] = []
                path.write_text(json.dumps(data))
            return result

        with patch.object(tts.subprocess, "run", side_effect=no_words):
            with self.assertRaisesRegex(RuntimeError, "no word timestamps"):
                tts.synthesize_kokoro([("Hello.", "am_fenrir")])

    def test_missing_environment_and_unknown_voices_stop_before_worker(self):
        with patch.object(tts, "KOKORO_PYTHON", Path(self.tmp.name) / "missing.exe"):
            with self.assertRaisesRegex(RuntimeError, "setup_windows.ps1"):
                tts.synthesize_kokoro([("Hello.", "am_fenrir")])
        for voice in ("en-US-ChristopherNeural", "zf_xiaoxiao", ""):
            with self.assertRaises(ValueError):
                tts.synthesize_kokoro([("Hello.", voice)])
        with self.assertRaisesRegex(ValueError, "Unknown speech provider"):
            tts.generate_speech("Hello.", "am_fenrir", "fish")
        self.assertEqual(self.worker_calls, [])


class KokoroVoiceSelectionTests(unittest.TestCase):
    def test_story_gender_picks_the_first_voice_of_each_pool(self):
        female = {"protagonist_gender": "female"}
        self.assertEqual(tts.select_story_voice(female, "kokoro"), KOKORO_VOICES["female"][0])
        self.assertEqual(
            tts.select_story_voice({"narrator_gender": "female"}, "kokoro"), "af_heart"
        )
        for story in ({"protagonist_gender": "male"}, {}, {"script": "My wife saw a woman."}):
            self.assertEqual(tts.select_story_voice(story, "kokoro"), DEFAULT_VOICE)
        self.assertEqual(DEFAULT_VOICE, KOKORO_VOICES["male"][0])

    def test_voice_pools_are_distinct_english_kokoro_voices(self):
        voices = [v for pool in KOKORO_VOICES.values() for v in pool]
        self.assertEqual(len(voices), len(set(voices)))
        for gender, pool in KOKORO_VOICES.items():
            for voice in pool:
                self.assertEqual(tts.resolve_voice(voice, "kokoro"), voice)
                self.assertEqual(voice[1], gender[0])


if __name__ == "__main__":
    unittest.main()
