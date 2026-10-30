import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from legacy.replenish_clips import ask_agy_for_queries, replenish


class ReplenishClipsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_ask_agy_parses_json_cleanly(self):
        fake_stdout = json.dumps(["dark labyrinth", "voxel cave", "underground motion"])
        fake_res = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        with (
            patch("shutil.which", return_value="C:\\dummy\\agy.exe"),
            patch("subprocess.run", return_value=fake_res) as run_mock,
        ):
            queries = ask_agy_for_queries(model="gemini-3.8-flash-low", count=3)
            self.assertEqual(len(queries), 3)
            self.assertIn("dark labyrinth", queries)
            cmd = run_mock.call_args[0][0]
            self.assertIn("--model", cmd)
            self.assertIn("gemini-3.8-flash-low", cmd)
            self.assertIn("--print", cmd)

    def test_ask_agy_strips_markdown_fences(self):
        fake_stdout = '```json\n["maze 1", "cave 2"]\n```'
        fake_res = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        with (
            patch("shutil.which", return_value="C:\\dummy\\agy.exe"),
            patch("subprocess.run", return_value=fake_res),
        ):
            queries = ask_agy_for_queries()
            self.assertEqual(queries, ["maze 1", "cave 2"])

    def test_ask_agy_handles_error_gracefully(self):
        fake_res = MagicMock(returncode=1, stdout="", stderr="CLI error")
        with (
            patch("shutil.which", return_value="C:\\dummy\\agy.exe"),
            patch("subprocess.run", return_value=fake_res),
        ):
            with self.assertRaisesRegex(RuntimeError, "AGY Flash invocation failed"):
                ask_agy_for_queries()

    def test_standard_install_resolves_when_parent_path_is_stale(self):
        executable = self.root / "agy" / "bin" / "agy.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"CLI path fixture")
        result = MagicMock(returncode=0, stdout='["Minetest cave"]', stderr="")
        with (
            patch.dict("os.environ", {"LOCALAPPDATA": str(self.root), "AGY_EXECUTABLE": ""}),
            patch("shutil.which", return_value=None),
            patch("subprocess.run", return_value=result) as run,
        ):
            self.assertEqual(ask_agy_for_queries(), ["Minetest cave"])
        self.assertEqual(run.call_args.args[0][0], str(executable))

    def test_replenish_no_op_when_target_met(self):
        with (
            patch(
                "legacy.replenish_clips.count_unreserved_clips",
                return_value=[Path("clip1.mp4"), Path("clip2.mp4")],
            ),
            patch("legacy.replenish_clips.download_gameplay_clip") as download_mock,
            redirect_stdout(io.StringIO()),
        ):
            res = replenish(target=2)
            self.assertEqual(len(res), 2)
            download_mock.assert_not_called()

    def test_replenish_invokes_agy_when_requested(self):
        with (
            patch(
                "legacy.replenish_clips.count_unreserved_clips",
                side_effect=[[], [Path("clip1.mp4")]],
            ),
            patch(
                "legacy.replenish_clips.ask_agy_for_queries", return_value=["custom query"]
            ) as agy_mock,
            patch(
                "legacy.replenish_clips.download_gameplay_clip", return_value=Path("clip1.mp4")
            ) as dl_mock,
            redirect_stdout(io.StringIO()),
        ):
            downloaded = replenish(target=1, with_agy=True)
            agy_mock.assert_called_once()
            dl_mock.assert_called_once_with(query="custom query", required_duration=60)
            self.assertEqual(downloaded, [Path("clip1.mp4")])


if __name__ == "__main__":
    unittest.main()
