import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shorts_automation.footage import creator_evidence as e
from shorts_automation.footage import creator_footage as f
from shorts_automation.footage.agy_footage_research import (
    compact_evidence,
    invoke_json,
    make_prompt,
    validate_against_evidence,
)
from shorts_automation.state.usage_store import UsageStore


class CreatorEvidenceTests(unittest.TestCase):
    def test_creator_link_spelling_variations_are_normalized(self):
        links = e.description_links(
            "Download mediafire.com/file/a/test.mp4/file\nhttps_://t.ly/abc\nhttps://example.com/x"
        )
        self.assertIn("https://mediafire.com/file/a/test.mp4/file", links)
        self.assertIn("https://t.ly/abc", links)

    def test_private_destinations_are_rejected_before_http(self):
        with (
            patch(
                "shorts_automation.footage.creator_evidence.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ),
            patch("shorts_automation.footage.creator_evidence.requests.get") as get,
        ):
            with self.assertRaises(ValueError):
                e.public_get("https://example.com/private")
            get.assert_not_called()

    def test_mediafire_button_requires_real_video_response(self):
        page = MagicMock(
            status_code=200, url="https://www.mediafire.com/file/a/file", encoding="utf-8"
        )
        page.headers = {"Content-Type": "text/html"}
        page.iter_content.return_value = [
            b'<a href="https://download.mediafire.com/a.mp4" id="downloadButton">Download</a>'
        ]
        file = MagicMock(status_code=200, url="https://download.mediafire.com/a.mp4")
        file.headers = {"Content-Type": "video/mp4", "Content-Length": "1000"}

        def context(response):
            context = MagicMock()
            context.__enter__.return_value = response
            return context

        with patch(
            "shorts_automation.footage.creator_evidence.public_get",
            side_effect=[context(page), context(file)],
        ):
            result = e.inspect_page(page.url)
        self.assertEqual(result["access_status"], "free_direct")
        self.assertEqual(result["verified_price"], "0")
        self.assertEqual(result["file_probe"]["content_type"], "video/mp4")

    def test_public_drive_video_landing_resolves_to_verified_download(self):
        landing = "https://drive.google.com/file/d/abc_123-xyz/view?usp=sharing"
        page = MagicMock(status_code=200, url=landing, encoding="utf-8")
        page.headers = {"Content-Type": "text/html"}
        page.iter_content.return_value = [b"<html>Google Drive file</html>"]
        file = MagicMock(
            status_code=200, url="https://drive.google.com/uc?export=download&id=abc_123-xyz"
        )
        file.headers = {"Content-Type": "video/mp4", "Content-Length": "1000"}
        with patch(
            "shorts_automation.footage.creator_evidence.public_get", side_effect=[page, file]
        ) as get:
            page.__enter__.return_value = page
            file.__enter__.return_value = file
            result = e.inspect_page(landing)
        self.assertEqual(result["access_status"], "free_direct")
        self.assertEqual(result["direct_file_url"], file.url)
        self.assertEqual(get.call_args_list[1].args[0], file.url)

    def test_drive_html_download_confirmation_is_not_accepted_as_video(self):
        landing = "https://drive.google.com/file/d/abc_123-xyz/view"
        page = MagicMock(status_code=200, url=landing, encoding="utf-8")
        page.headers = {"Content-Type": "text/html"}
        page.iter_content.return_value = [b"<html>Google Drive file</html>"]
        file = MagicMock(status_code=200, url="https://drive.google.com/uc")
        file.headers = {"Content-Type": "text/html"}
        page.__enter__.return_value = page
        file.__enter__.return_value = file
        with patch(
            "shorts_automation.footage.creator_evidence.public_get", side_effect=[page, file]
        ):
            result = e.inspect_page(landing)
        self.assertEqual(result["access_status"], "unknown")
        self.assertIsNone(result["direct_file_url"])

    def test_model_cannot_invent_free_file_evidence(self):
        data = {
            "ready": [
                {
                    "video_url": "https://youtube.com/watch?v=abcdefghijk",
                    "download_landing_url": "https://example.com/file",
                }
            ]
        }
        with self.assertRaises(ValueError):
            validate_against_evidence(data, {"download_pages": []})

    def test_large_packet_fits_windows_command_budget_and_keeps_verified_source(self):
        videos = [
            {"id": str(i), "video_url": "https://youtu.be/" + str(i), "description": "word " * 2000}
            for i in range(10)
        ]
        evidence = {
            "searches": ["minecraft"],
            "videos": videos,
            "download_pages": [
                {
                    "landing_url": "https://example.com/" + str(i),
                    "linked_from_video": "https://youtu.be/9",
                    "access_status": "free_direct" if i == 0 else "unknown",
                    "page_text": "text " * 1000,
                }
                for i in range(10)
            ],
        }
        compact = compact_evidence(evidence)
        self.assertEqual(compact["videos"][0]["id"], "9")
        command = ["agy", "--print", make_prompt() + json.dumps(compact)]
        self.assertLess(len(subprocess.list2cmdline(command)), 30000)

    def test_agy_runs_outside_coding_workspace_without_permission_bypass(self):
        result = MagicMock(returncode=0, stdout=json.dumps({"response": '{"ok":true}'}))
        with patch(
            "shorts_automation.footage.agy_footage_research.subprocess.run", return_value=result
        ) as run:
            self.assertEqual(
                invoke_json("agy", "configured-model", "Return JSON, no tools."), '{"ok":true}'
            )
        command = run.call_args.args[0]
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertNotIn("--mode", command)
        self.assertIn("shorts_footage_research_", run.call_args.kwargs["cwd"])


class CreatorImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.record = {
            "video_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "download_landing_url": "https://mediafire.com/file/a/file",
            "access_status": "free_direct",
            "commercial_use": "explicitly_allowed",
            "permission_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "permission_excerpt": "You can use it for free...No credit required.",
        }
        self.video = {
            "title": "Minecraft Parkour Gameplay",
            "creator": "Creator",
            "duration_seconds": 400,
            "description": "You can use it for free. Anything. No credit required.\nhttps://mediafire.com/file/a/file",
            "width": 1920,
            "height": 1080,
            "fps": 60,
        }
        for name, value in [("BACKGROUNDS_DIR", self.root)]:
            p = patch.object(f, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_permission_and_free_access_checked_before_ffmpeg(self):
        with (
            patch("shorts_automation.footage.creator_footage.read_video", return_value=self.video),
            patch("shorts_automation.footage.creator_footage.UsageStore") as store,
            patch(
                "shorts_automation.footage.creator_footage.inspect_page",
                return_value={"access_status": "paid"},
            ),
            patch("shorts_automation.footage.creator_footage.subprocess.run") as run,
        ):
            store.return_value.unavailable.return_value = False
            store.return_value.source_unavailable.return_value = False
            store.return_value.next_segment_start.return_value = 5
            with self.assertRaisesRegex(ValueError, "no longer publicly accessible"):
                f.import_creator_clip(self.record, {f.LICENSE})
            run.assert_not_called()

    def test_import_caches_verified_segment_with_provenance(self):
        page = {
            "access_status": "free_direct",
            "direct_file_url": "https://download.mediafire.com/a.mp4",
            "file_probe": {"bytes": "10000", "content_type": "video/mp4"},
        }

        def render(command, **kwargs):
            Path(command[-1]).write_bytes(b"normalized video fixture")
            return MagicMock(returncode=0)

        with (
            patch("shorts_automation.footage.creator_footage.read_video", return_value=self.video),
            patch("shorts_automation.footage.creator_footage.UsageStore") as store,
            patch("shorts_automation.footage.creator_footage.inspect_page", return_value=page),
            patch("shorts_automation.footage.creator_footage.get_video_duration", return_value=60),
            patch(
                "shorts_automation.footage.creator_footage.require_vertical_detail", return_value={}
            ),
            patch(
                "shorts_automation.footage.creator_footage.has_vertical_detail", return_value=True
            ),
            patch("shorts_automation.footage.creator_footage.subprocess.run", side_effect=render),
        ):
            store.return_value.unavailable.return_value = False
            store.return_value.source_unavailable.return_value = False
            store.return_value.next_segment_start.return_value = 5
            output = f.import_creator_clip(self.record, {f.LICENSE})
            self.assertEqual(f.cached_creator_clip({f.LICENSE}), output)
        metadata = json.loads(output.with_suffix(".source.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_url"], "https://youtu.be/abcdefghijk")
        self.assertEqual(metadata["segment_duration"], 60)
        self.assertEqual(metadata["license"], f.LICENSE)
        self.assertFalse(metadata["looped"])
        self.assertNotIn("download.mediafire.com", json.dumps(metadata))

    def test_creator_mode_does_not_use_old_commons_adapter(self):
        from shorts_automation.automation import production

        config = production.load_config()
        with (
            patch(
                "shorts_automation.footage.creator_footage.get_creator_background",
                return_value=self.root / "new.mp4",
            ) as source,
            patch("shorts_automation.footage.gameplay_fetcher.get_background_clip") as old_source,
            patch("shorts_automation.rendering.pipeline.run_pipeline") as renderer,
        ):
            production.render_automatic(
                config, story_file=self.root / "story.json", tts_provider="fish"
            )
        source.assert_called_once()
        old_source.assert_not_called()
        self.assertEqual(renderer.call_args.kwargs["background_file"], self.root / "new.mp4")

    def test_known_recording_supplies_next_unused_segment_without_agy(self):
        store = UsageStore(self.root / "usage.sqlite3")
        page = {
            "access_status": "free_direct",
            "direct_file_url": "https://download.mediafire.com/a.mp4",
            "file_probe": {"bytes": "1000"},
        }

        def render(command, **kwargs):
            start = command[command.index("-ss") + 1]
            Path(command[-1]).write_bytes(("different frames at " + start).encode())
            return MagicMock(returncode=0)

        with (
            patch("shorts_automation.footage.creator_footage.UsageStore", return_value=store),
            patch("shorts_automation.footage.creator_footage.read_video", return_value=self.video),
            patch("shorts_automation.footage.creator_footage.inspect_page", return_value=page),
            patch("shorts_automation.footage.creator_footage.get_video_duration", return_value=60),
            patch(
                "shorts_automation.footage.creator_footage.require_vertical_detail", return_value={}
            ),
            patch(
                "shorts_automation.footage.creator_footage.has_vertical_detail", return_value=True
            ),
            patch("shorts_automation.footage.creator_footage.subprocess.run", side_effect=render),
            patch("shorts_automation.footage.agy_footage_research.research") as research,
        ):
            first = f.import_creator_clip(self.record, {f.LICENSE})
            metadata = json.loads(first.with_suffix(".source.json").read_text(encoding="utf-8"))
            job = store.begin("first narration")
            store.reserve_source(job, metadata, first)
            store.complete(job, self.root / "first.mp4")
            second = f.get_creator_background({"background_licenses": [f.LICENSE]})
            next_meta = json.loads(second.with_suffix(".source.json").read_text(encoding="utf-8"))
            self.assertEqual((metadata["segment_start"], next_meta["segment_start"]), (5, 65))
            self.assertNotEqual(first, second)
            self.assertFalse(store.source_unavailable(next_meta, second))
            research.assert_not_called()


if __name__ == "__main__":
    unittest.main()
