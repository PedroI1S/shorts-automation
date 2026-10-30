import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import DEFAULT_VOICE
from shorts_automation.stories import tts_engine as tts


class VoiceSelectionTests(unittest.TestCase):
    def test_female_protagonist_uses_configured_voice_through_synthesis(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tts, "SECRETS_DIR", Path(tmp)),
            patch.dict("os.environ", {}, clear=True),
        ):
            (Path(tmp) / "fish.local.json").write_text(
                json.dumps({"female_voice_id": "female-ref"})
            )
            selected = tts.select_story_voice({"protagonist_gender": "female"}, "fish")
            with patch.object(tts, "generate_fish", return_value=(None, 1, [])) as generate:
                tts.generate_speech("test", selected, "fish")
                generate.assert_called_once_with("test", voice_override="female-ref")

    def test_missing_female_voice_fails_instead_of_using_male(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tts, "SECRETS_DIR", Path(tmp)),
            patch.dict("os.environ", {}, clear=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "Female protagonist requires"):
                tts.select_story_voice({"narrator_gender": "female"}, "fish")

    def test_male_legacy_and_incidental_female_keep_existing_voice(self):
        for story in ({"protagonist_gender": "male"}, {}, {"script": "My wife saw a woman."}):
            self.assertEqual(tts.select_story_voice(story, "fish"), DEFAULT_VOICE)

    def test_edge_female_and_elevenlabs_override(self):
        self.assertEqual(
            tts.select_story_voice({"protagonist_gender": "female"}, "edge"), "en-US-JennyNeural"
        )
        with patch.dict("os.environ", {"ELEVENLABS_FEMALE_VOICE_ID": "female-eleven"}):
            selected = tts.select_story_voice({"protagonist_gender": "female"}, "elevenlabs")
            with patch.object(tts, "generate_elevenlabs", return_value=(None, 1, [])) as generate:
                tts.generate_speech("test", selected, "elevenlabs")
                generate.assert_called_once_with("test", voice_override="female-eleven")
