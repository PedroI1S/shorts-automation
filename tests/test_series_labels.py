import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.publishing.youtube_uploader import build_short_metadata
from shorts_automation.rendering import subtitle_engine as captions


class SeriesLabelTests(unittest.TestCase):
    def info(self, part=1, total=3):
        return {
            "id": "1" * 32,
            "title": "The Voice Beneath My Floor",
            "part": part,
            "total": total,
            "ending": "finale" if part == total else "cliffhanger",
        }

    def test_continuation_cue_uses_existing_final_two_seconds_without_stretching_speech(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(captions, "TEMP_DIR", Path(tmp)),
            patch.object(
                captions, "create_subtitle_image", wraps=captions.create_subtitle_image
            ) as create,
        ):
            path = captions.generate_subtitles_stream(
                [
                    {"text": "I", "start": 0.0, "end": 1.0},
                    {"text": "heard", "start": 1.0, "end": 2.0},
                    {"text": "her", "start": 2.0, "end": 3.0},
                ],
                3.0,
                series=self.info(),
            )
            footer_files = {
                call.args[1].name
                for call in create.call_args_list
                if call.kwargs.get("continuation")
            }
            current, total, footer_duration = None, 0.0, 0.0
            for line in path.read_text().splitlines():
                if line.startswith("file "):
                    current = Path(line[6:-1]).name
                elif line.startswith("duration "):
                    duration = float(line.split()[1])
                    total += duration
                    if current in footer_files:
                        footer_duration += duration
            self.assertAlmostEqual(total, 3.8)
            self.assertAlmostEqual(footer_duration, 2.0)
            self.assertTrue(
                all(call.kwargs.get("part_label") == "PART 1/3" for call in create.call_args_list)
            )

    def test_final_part_has_no_nonexistent_continuation(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(captions, "TEMP_DIR", Path(tmp)),
            patch.object(
                captions, "create_subtitle_image", wraps=captions.create_subtitle_image
            ) as create,
        ):
            captions.generate_subtitles_stream(
                [{"text": "Gone", "start": 0.0, "end": 0.3}], 0.3, series=self.info(4, 4)
            )
            self.assertFalse(any(call.kwargs.get("continuation") for call in create.call_args_list))
            self.assertTrue(
                all(call.kwargs.get("part_label") == "PART 4/4" for call in create.call_args_list)
            )

    def test_upload_titles_are_searchable_numbered_and_keep_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "video.mp4"
            for number in (1, 2, 3):
                video.with_suffix(".metadata.json").write_text(
                    json.dumps(
                        {
                            "story": {
                                "title": "The Recording Beneath My Floor",
                                "script": "I heard her voice.",
                                "series": self.info(number),
                            },
                            "background_source": {"credit_text": "Creator credit instruction"},
                        }
                    )
                )
                meta = build_short_metadata(video)
                self.assertTrue(
                    meta["title"].startswith(f"Part {number}/3: The Voice Beneath My Floor")
                )
                self.assertIn("Creator credit instruction", meta["description"])
                if number < 3:
                    self.assertIn(f"Next: Part {number + 1}", meta["description"])
                    self.assertNotIn("already", meta["description"])
                else:
                    self.assertNotIn("Next:", meta["description"])

    def test_long_series_name_cannot_truncate_the_part_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "video.mp4"
            info = self.info()
            info["title"] = "Something " * 7 + "Nightmare"
            video.with_suffix(".metadata.json").write_text(json.dumps({"story": {"series": info}}))
            title = build_short_metadata(video)["title"]
            self.assertTrue(title.startswith("Part 1/3:"))
            self.assertLessEqual(len(title), 100)
