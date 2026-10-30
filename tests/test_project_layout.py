"""Protect runtime paths and installed entry points during source reorganization."""

import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from shorts_automation.automation import orchestrator, production
from shorts_automation.footage import agy_footage_research
from shorts_automation.publishing import telegram_notifier, youtube_reauthorize, youtube_uploader
from shorts_automation.stories import draft_story, tts_engine


class ProjectLayoutTests(unittest.TestCase):
    def test_migrated_json_paths_and_stable_runtime_paths(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(config.BASE_DIR, root)
        self.assertEqual(config.STORAGE_DIR, root / "storage")
        self.assertEqual(config.SECRETS_DIR, root / "secrets")
        self.assertEqual(production.CONFIG_PATH, root / "secrets/production.json")
        self.assertEqual(production.HEALTH_PATH, root / "storage/production_health.json")
        self.assertEqual(orchestrator.DB_PATH, root / "storage/usage.sqlite3")
        self.assertEqual(orchestrator.LOCK_PATH, root / "storage/orchestrator.lock")
        self.assertEqual(youtube_uploader.TOKEN_FILE, root / "secrets/token.json")
        self.assertEqual(youtube_reauthorize.CANDIDATE, root / "secrets/token-candidate.json")
        self.assertEqual(youtube_uploader.TOKEN_LOCK, root / "storage/youtube-token.lock")
        self.assertEqual(youtube_uploader.CLIENT_SECRETS_FILE, root / "secrets/client_secret.json")
        self.assertEqual(telegram_notifier.ROUTE_FILE, root / "secrets/telegram.local.json")
        self.assertEqual(tts_engine.SECRETS_DIR, root / "secrets")
        self.assertEqual(draft_story.BASE_DIR, root)
        self.assertEqual(agy_footage_research.PROMPT_PATH, root / "prompts/agy_footage_supply.md")

    def test_installed_root_entry_points_delegate_without_starting_real_work(self):
        root = Path(__file__).resolve().parents[1]
        for name, module in (("production", production), ("orchestrator", orchestrator)):
            with (
                self.subTest(entry_point=name),
                patch.object(module, "main", return_value=0) as main,
            ):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(str(root / f"{name}.py"), run_name="__main__")
                self.assertEqual(stopped.exception.code, 0)
                main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
