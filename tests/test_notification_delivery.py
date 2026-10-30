import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.publishing import telegram_notifier as notifier


class DeliveryTests(unittest.TestCase):
    def test_configured_chat_used_and_inherited_pythonpath_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = Path(tmp) / "telegram.local.json"
            route.write_text(json.dumps({"chat_id": "12345"}), encoding="utf-8")
            exe = Path(tmp) / "hermes.exe"
            exe.touch()
            completed = subprocess.CompletedProcess(
                [], 0, '{"success": true, "message_id": "1"}', ""
            )
            with (
                patch.object(notifier, "ROUTE_FILE", route, create=True),
                patch.dict(os.environ, {"HERMES_HOME": tmp, "PYTHONPATH": "wrong"}),
                patch(
                    "shorts_automation.publishing.telegram_notifier.Path.is_file", return_value=True
                ),
                patch(
                    "shorts_automation.publishing.telegram_notifier.subprocess.run",
                    return_value=completed,
                ) as run,
            ):
                notifier.send_telegram("test")
            args, kwargs = run.call_args
            self.assertIn("telegram:12345", args[0])
            self.assertNotIn("PYTHONPATH", kwargs["env"])

    def test_success_exit_without_delivery_confirmation_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = Path(tmp) / "telegram.local.json"
            route.write_text(json.dumps({"chat_id": "12345"}), encoding="utf-8")
            result = subprocess.CompletedProcess([], 0, '{"success": false}', "")
            with (
                patch.object(notifier, "ROUTE_FILE", route, create=True),
                patch.dict(os.environ, {"HERMES_HOME": tmp}),
                patch(
                    "shorts_automation.publishing.telegram_notifier.Path.is_file", return_value=True
                ),
                patch(
                    "shorts_automation.publishing.telegram_notifier.subprocess.run",
                    return_value=result,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    notifier.send_telegram("test")
