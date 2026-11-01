import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shorts_automation.rendering import subtitle_engine as subtitles
from shorts_automation.stories.kokoro_worker import tokens_to_words


class SpeechTimingTests(unittest.TestCase):
    def test_highlight_follows_each_word_and_clears_during_gap(self):
        words = [
            {"text": "I", "start": 0.1, "end": 0.2},
            {"text": "heard", "start": 0.2, "end": 0.5},
            {"text": "you", "start": 0.6, "end": 0.9},
        ]
        frames = subtitles.build_highlight_cues(words, 1)
        self.assertEqual(
            [(f["start"], f["end"], f["highlight_index"]) for f in frames],
            [(0.1, 0.2, 0), (0.2, 0.5, 1), (0.5, 0.6, None), (0.6, 0.9, 2)],
        )
        self.assertTrue(all(f["text"] == "I heard you" for f in frames))

    def test_zero_duration_word_does_not_delay_next_highlight(self):
        words = [
            {"text": "with", "start": 0, "end": 0.2},
            {"text": "a", "start": 0.2, "end": 0.2},
            {"text": "message", "start": 0.2, "end": 0.6},
        ]
        frames = subtitles.build_highlight_cues(words, 1)
        self.assertEqual([f["highlight_index"] for f in frames], [0, 2])
        self.assertEqual(frames[-1]["text"], "with a message")

    def test_zero_duration_article_is_preserved_in_card(self):
        tokens = [
            SimpleNamespace(text="with", start_ts=0, end_ts=0.2, whitespace=" "),
            SimpleNamespace(text="a", start_ts=0.2, end_ts=0.2, whitespace=" "),
            SimpleNamespace(text="message", start_ts=0.2, end_ts=0.6, whitespace=""),
        ]
        words = tokens_to_words(tokens, 0, 1)
        self.assertEqual(
            subtitles.build_caption_cues(words, 1),
            [{"text": "with a message", "start": 0, "end": 0.6}],
        )

    def test_isolated_zero_duration_article_before_pause_joins_next_phrase(self):
        words = [
            {"text": "in", "start": 0, "end": 0.2},
            {"text": "my", "start": 0.2, "end": 0.3},
            {"text": "room", "start": 0.3, "end": 0.5},
            {"text": "The", "start": 0.5, "end": 0.5},
            {"text": "motel", "start": 1.3, "end": 1.8},
            {"text": "closed", "start": 1.8, "end": 2.1},
        ]
        cues = subtitles.build_caption_cues(words, 3)
        self.assertEqual(cues[-1], {"text": "The motel closed", "start": 1.3, "end": 2.1})
        highlights = subtitles.build_highlight_cues(words, 3)
        self.assertEqual([f["highlight_index"] for f in highlights[-2:]], [1, 2])
        self.assertEqual(highlights[-2]["start"], 1.3)

    def test_only_untimed_words_rejected_but_trailing_token_kept(self):
        with self.assertRaises(ValueError):
            subtitles.build_caption_cues([{"text": "The", "start": 0, "end": 0}], 2)
        words = [
            {"text": "I", "start": 0, "end": 0.2},
            {"text": "heard", "start": 0.2, "end": 0.4},
            {"text": "it", "start": 0.4, "end": 0.6},
            {"text": "again", "start": 0.6, "end": 0.6},
        ]
        cues = subtitles.build_caption_cues(words, 1)
        self.assertEqual(cues[-1], {"text": "I heard it again", "start": 0, "end": 0.6})

    def test_short_words_do_not_stretch_timeline(self):
        words = [
            {"text": "hello", "start": 0.0, "end": 0.1},
            {"text": "world", "start": 0.1, "end": 0.2},
        ]
        self.assertEqual(
            subtitles.build_caption_cues(words, 0.2),
            [{"text": "hello world", "start": 0.0, "end": 0.2}],
        )

    def test_long_pause_splits_cards(self):
        words = [
            {"text": "Wait", "start": 0.1, "end": 0.3},
            {"text": "what", "start": 1.0, "end": 1.2},
        ]
        self.assertEqual(len(subtitles.build_caption_cues(words, 1.5)), 2)

    def test_sentence_estimates_are_rejected(self):
        with self.assertRaises(ValueError):
            subtitles.build_caption_cues([{"text": "two words", "start": 0, "end": 1}], 2)

    def test_concat_duration_has_no_accumulated_padding(self):
        with tempfile.TemporaryDirectory(prefix="timing-test-") as tmp:
            with patch.object(subtitles, "TEMP_DIR", Path(tmp)):
                path = subtitles.generate_subtitles_stream(
                    [
                        {"text": "Hi", "start": 0.12, "end": 0.22},
                        {"text": "again", "start": 0.75, "end": 0.85},
                    ],
                    1.0,
                )
                durations = [
                    float(line.split()[1])
                    for line in path.read_text().splitlines()
                    if line.startswith("duration ")
                ]
                self.assertAlmostEqual(sum(durations), 1.8, places=6)
                self.assertIn("option framerate 1000", path.read_text())


if __name__ == "__main__":
    unittest.main()
