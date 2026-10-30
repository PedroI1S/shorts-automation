import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shorts_automation.rendering import subtitle_engine as subtitles
from shorts_automation.stories import tts_engine as tts


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
        events = [
            {
                "chunk_seq": 0,
                "chunk_audio_offset_sec": 0,
                "alignment": {
                    "segments": [
                        {"text": "with", "start": 0, "end": 0.2},
                        {"text": "a", "start": 0.2, "end": 0.2},
                        {"text": "message", "start": 0.2, "end": 0.6},
                    ]
                },
            }
        ]
        words = tts.fish_alignment_to_words(events)
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

    def test_fish_snapshots_replace_instead_of_duplicate(self):
        events = [
            {
                "chunk_seq": 0,
                "chunk_audio_offset_sec": 0,
                "alignment": {"segments": [{"text": "Hello", "start": 0, "end": 0.4}]},
            },
            {
                "chunk_seq": 0,
                "chunk_audio_offset_sec": 0,
                "alignment": {
                    "segments": [
                        {"text": "Hello", "start": 0, "end": 0.4},
                        {"text": "there", "start": 0.3, "end": 0.7},
                    ]
                },
            },
            {
                "chunk_seq": 1,
                "chunk_audio_offset_sec": 1.0,
                "alignment": {"segments": [{"text": "friend", "start": 0.1, "end": 0.5}]},
            },
        ]
        self.assertEqual(
            tts.fish_alignment_to_words(events),
            [
                {"text": "Hello", "start": 0, "end": 0.3},
                {"text": "there", "start": 0.3, "end": 0.7},
                {"text": "friend", "start": 1.1, "end": 1.5},
            ],
        )

    def test_fish_sse_handles_comments_multiline_and_done(self):
        lines = [
            b": keepalive",
            b"event: message",
            b'data: {"chunk_seq":',
            b"data: 1}",
            b"",
            b"data: [DONE]",
            b"",
        ]
        self.assertEqual(list(tts.read_sse_events(lines)), [{"chunk_seq": 1}])

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

    def test_character_alignment_preserves_word_boundaries(self):
        alignment = {
            "characters": list("Hi all"),
            "character_start_times_seconds": [0, 0.1, 0.2, 0.4, 0.5, 0.6],
            "character_end_times_seconds": [0.1, 0.2, 0.3, 0.5, 0.6, 0.7],
        }
        self.assertEqual(
            tts.alignment_to_words(alignment),
            [{"text": "Hi", "start": 0, "end": 0.2}, {"text": "all", "start": 0.4, "end": 0.7}],
        )

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

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test", "ELEVENLABS_VOICE_ID": "test"})
    def test_paid_account_cannot_generate_audio(self):
        with (
            patch.object(
                tts.requests, "get", return_value=Mock(ok=True, json=lambda: {"tier": "starter"})
            ),
            patch.object(tts.requests, "post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "paid usage is disabled"):
                tts.generate_elevenlabs("Hello")
            post.assert_not_called()

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test", "ELEVENLABS_VOICE_ID": "test"})
    def test_exhausted_free_quota_cannot_generate_audio(self):
        account = {"tier": "free", "character_limit": 10, "character_count": 10}
        with (
            patch.object(tts.requests, "get", return_value=Mock(ok=True, json=lambda: account)),
            patch.object(tts.requests, "post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "free quota"):
                tts.generate_elevenlabs("Hello")
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
