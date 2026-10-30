import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from shorts_automation.rendering import pipeline, video_compiler
from shorts_automation.state.usage_store import UsageStore
from shorts_automation.stories.tts_engine import estimate_duration


def write_story(directory, words):
    path = Path(directory) / "draft.json"
    path.write_text(
        json.dumps({"title": "The Voice Behind The Door", "script": " ".join(["word"] * words)})
    )
    return path


class PreTtsDurationTests(unittest.TestCase):
    def test_overlong_script_rejected_before_tts_and_reservation(self):
        # 144 words passes draft validation (<= 146) but at Edge's rate (2.5 w/s) is 58.4s with tail.
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp) / "db.sqlite3")
            story = write_story(temp, 144)
            with (
                patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                patch.object(pipeline, "generate_speech") as speech,
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(ValueError, "no TTS call made"):
                    pipeline.run_pipeline(story_file=story, tts_provider="edge")
                speech.assert_not_called()
            store.begin(" ".join(["word"] * 144))  # Story was never reserved.

    def test_known_good_fish_length_reaches_tts(self):
        # 146 words rendered at 56.29s on the real Fish voice; it must not be rejected.
        with tempfile.TemporaryDirectory() as temp:
            store = UsageStore(Path(temp) / "db.sqlite3")
            story = write_story(temp, 146)
            with (
                patch("shorts_automation.state.usage_store.UsageStore", return_value=store),
                patch.object(
                    pipeline, "generate_speech", side_effect=RuntimeError("stop here")
                ) as speech,
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(RuntimeError, "stop here"):
                    pipeline.run_pipeline(story_file=story, tts_provider="fish")
                speech.assert_called_once()

    def test_estimate_counts_prepared_words_and_rejects_unknown_provider(self):
        self.assertAlmostEqual(estimate_duration("one  two\n three", "edge"), 3 / 2.5)
        with self.assertRaises(ValueError):
            estimate_duration("hello", "mystery")


def fake_ffmpeg(returncode=0, write=True):
    """Stand-in for subprocess.run that writes the output path FFmpeg was given."""

    def run(cmd, **kwargs):
        if write:
            Path(cmd[-1]).write_bytes(b"partial-or-complete video bytes")
        return MagicMock(returncode=returncode, stderr="simulated failure")

    return run


class NarrationMixTests(unittest.TestCase):
    def test_background_audio_mix_does_not_attenuate_narration(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(video_compiler, "OUTPUT_DIR", Path(temp)),
            patch.object(video_compiler, "has_audio_stream", return_value=True),
            patch.object(video_compiler.subprocess, "run", side_effect=fake_ffmpeg()) as run,
            redirect_stdout(io.StringIO()),
        ):
            video_compiler.compile_short(
                Path("bg.mp4"), 0, Path("n.mp3"), 10, Path("c.ffconcat"), "x.mp4"
            )
        cmd = run.call_args.args[0]
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("amix=", graph)
        self.assertIn("normalize=0", graph)


class AtomicOutputTests(unittest.TestCase):
    def compile(self, temp, run):
        with (
            patch.object(video_compiler, "OUTPUT_DIR", Path(temp)),
            patch.object(video_compiler, "has_audio_stream", return_value=False),
            patch.object(video_compiler.subprocess, "run", side_effect=run),
            redirect_stdout(io.StringIO()),
        ):
            return video_compiler.compile_short(
                Path("bg.mp4"), 0, Path("n.mp3"), 10, Path("c.ffconcat"), "x.mp4"
            )

    def test_failed_render_leaves_no_final_or_partial_file(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "rendering failed"):
                self.compile(temp, fake_ffmpeg(returncode=1))
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_timeout_leaves_no_file(self):
        def hang(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"truncated")
            raise video_compiler.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "exceeded"):
                self.compile(temp, hang)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_success_with_empty_output_is_rejected(self):
        def empty(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"")
            return MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "no output"):
                self.compile(temp, empty)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_success_publishes_only_final_name(self):
        with tempfile.TemporaryDirectory() as temp:
            out = self.compile(temp, fake_ffmpeg())
            self.assertEqual([p.name for p in Path(temp).iterdir()], ["x.mp4"])
            self.assertEqual(out, Path(temp) / "x.mp4")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg not installed")
class RealRenderAspectTests(unittest.TestCase):
    """Renders real 1s clips; sources narrower than 9:16 used to fail the crop."""

    def render(self, temp, size):
        t = Path(temp)
        ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        subprocess.run(
            ff
            + [
                "-f",
                "lavfi",
                "-i",
                f"testsrc=size={size}:rate=30:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(t / "bg.mp4"),
            ],
            check=True,
        )
        subprocess.run(ff + ["-f", "lavfi", "-i", "sine=duration=1", str(t / "n.wav")], check=True)
        subprocess.run(
            ff
            + [
                "-f",
                "lavfi",
                "-i",
                "color=c=black@0.0:size=1080x1920,format=rgba",
                "-frames:v",
                "1",
                str(t / "blank.png"),
            ],
            check=True,
        )
        blank = (t / "blank.png").as_posix()
        (t / "c.ffconcat").write_text(
            f"ffconcat version 1.0\nfile '{blank}'\nduration 2\nfile '{blank}'\n"
        )
        with patch.object(video_compiler, "OUTPUT_DIR", t), redirect_stdout(io.StringIO()):
            out = video_compiler.compile_short(
                t / "bg.mp4", 0, t / "n.wav", 1.0, t / "c.ffconcat", "out.mp4"
            )
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return probe.stdout.strip()

    def test_narrow_portrait_source(self):  # 0.375 aspect, narrower than 9:16
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.render(temp, "600x1600"), "1080,1920")

    def test_widescreen_source(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.render(temp, "1280x720"), "1080,1920")


if __name__ == "__main__":
    unittest.main()
