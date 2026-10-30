import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shorts_automation.footage import creator_footage as footage
from shorts_automation.footage import video_quality as quality


def probe_result(width, height, **extra):
    return MagicMock(
        returncode=0,
        stdout=json.dumps({"streams": [{"width": width, "height": height, **extra}]}),
    )


class NativeDetailTests(unittest.TestCase):
    def test_4k_and_portrait_sources_have_enough_native_vertical_detail(self):
        for width, height, crop in [(3840, 2160, (1214, 2160)), (1080, 1920, (1080, 1920))]:
            with (
                self.subTest(size=(width, height)),
                patch.object(quality.subprocess, "run", return_value=probe_result(width, height)),
            ):
                data = quality.require_vertical_detail(Path("fixture.mp4"))
                self.assertEqual((data["vertical_crop_width"], data["vertical_crop_height"]), crop)

    def test_landscape_1080p_and_narrow_portrait_cannot_pass_as_full_hd_vertical(self):
        for width, height in [(1920, 1080), (2560, 1440), (720, 2560)]:
            with (
                self.subTest(size=(width, height)),
                patch.object(quality.subprocess, "run", return_value=probe_result(width, height)),
                self.assertRaisesRegex(ValueError, "native detail is required"),
            ):
                quality.require_vertical_detail(Path("fixture.mp4"))

    def test_invalid_geometry_is_refused_and_signed_url_is_not_reported(self):
        cases = [
            MagicMock(returncode=1, stderr="signed private URL"),
            MagicMock(returncode=0, stdout="broken JSON"),
            probe_result(3840, 2160, sample_aspect_ratio="2:1"),
        ]
        for result in cases:
            with patch.object(quality.subprocess, "run", return_value=result):
                with self.assertRaises(ValueError) as error:
                    quality.require_vertical_detail("https://example.org/video?secret=token")
                self.assertNotIn("secret", str(error.exception))
                self.assertNotIn("signed", str(error.exception))

    def test_old_cache_is_skipped_without_modifying_or_upgrading_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "creator_old.mp4"
            video.write_bytes(b"old source")
            sidecar = video.with_suffix(".source.json")
            metadata = {
                "query": footage.CREATOR_QUERY,
                "title": "Minecraft Parkour",
                "license": footage.LICENSE,
                "source_url": "https://example.org/source",
                "author": "Creator",
                "license_url": "https://example.org/license",
                "permission_excerpt": "Free to use",
                "download_landing_url": "https://example.org/download",
                "youtube_video_id": "abcdefghijk",
                "segment_start": 5,
                "segment_duration": 60,
                "source_duration": 400,
                "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            }
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            before = sidecar.read_bytes()
            store = MagicMock()
            store.source_unavailable.return_value = False
            with (
                patch.object(footage, "BACKGROUNDS_DIR", root),
                patch.object(footage, "UsageStore", return_value=store),
                patch.object(footage, "get_video_duration", return_value=60),
                patch.object(quality.subprocess, "run", return_value=probe_result(1920, 1080)),
            ):
                self.assertIsNone(footage.cached_creator_clip({footage.LICENSE}))
            self.assertEqual(sidecar.read_bytes(), before)
            self.assertEqual(video.read_bytes(), b"old source")
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_download_file_geometry_is_checked_before_encoding_or_publishing_cache(self):
        from tests.test_creator_evidence import CreatorImportTests

        fixture = CreatorImportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with (
            patch.object(footage, "read_video", return_value=fixture.video),
            patch.object(footage, "UsageStore") as store,
            patch.object(
                footage,
                "inspect_page",
                return_value={
                    "access_status": "free_direct",
                    "direct_file_url": "https://example.org/direct.mp4",
                },
            ),
            patch.object(quality.subprocess, "run", return_value=probe_result(1920, 1080)) as run,
        ):
            store.return_value.next_segment_start.return_value = 5
            with self.assertRaisesRegex(ValueError, "native detail is required"):
                footage.import_creator_clip(fixture.record, {footage.LICENSE})
            self.assertEqual([call.args[0][0] for call in run.call_args_list], ["ffprobe"])
            self.assertEqual(list(fixture.root.iterdir()), [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg not installed")
class RealVerticalPreparationTests(unittest.TestCase):
    def test_real_4k_frame_crops_and_downscales_to_native_full_hd(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "portrait.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=3840x2160:rate=1:duration=1",
                    "-vf",
                    quality.VERTICAL_FILTER,
                    "-frames:v",
                    "1",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(output),
                ],
                check=True,
                capture_output=True,
            )
            geometry = quality.require_vertical_detail(output)
            self.assertEqual((geometry["source_width"], geometry["source_height"]), (1080, 1920))
            subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
                check=True,
                capture_output=True,
            )
