"""Exercise archive boundaries and secret handling in an isolated workspace."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_transfer_package as package


class TransferPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in package.EXTRA_FILES:
            self.write(name, "{}" if name.endswith(".json") else "fixture\n")
        for name in package.MEDIA:
            self.write(name, b"accepted media fixture")
        self.write("README.md", "# Project\n")
        self.write("app.py", 'print("example")\n')
        self.write("docs/guide.md", "# Current guide\n")
        self.write("docs/history/old.md", "# Historical guide\n")
        self.write("prompts/agy_footage_supply.md", "Research brief\n")
        self.write("tests/__init__.py", "")
        self.write("tests/test_example.py", "# isolated test\n")
        self.write("legacy/__init__.py", "")
        self.write("legacy/batch_generator.py", "# retained legacy entry point\n")
        self.write("shorts_automation/__init__.py", "")
        self.write("shorts_automation/automation/production.py", "# worker implementation\n")
        self.write("shorts_automation/footage/creator_footage.py", "# creator importer\n")
        self.write(
            "shorts_automation/automation/run_production_windows.ps1", "# scheduled launcher\n"
        )
        self.write("scripts/windows/setup_windows.ps1", "# setup entry point\n")

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def test_archive_contains_organized_sources_without_private_state(self):
        for name in ("fish.local.json", "token.json", "client_secret.json"):
            self.write(name, "{}")
            self.write("secrets/" + name, "{}")
        self.write("secrets/telegram.local.json", "{}")
        self.write("secrets/token-candidate.json", "{}")
        for name in (
            "docs/credential.local.json",
            "storage/usage.sqlite3",
            ".venv/secret.py",
            "deployment/old.py",
            "storage/reviews/evidence.json",
            "docs/__pycache__/cached.py",
            "shorts_automation/footage/__pycache__/cached.py",
            "shorts_automation/publishing/token.json",
        ):
            self.write(name, "private fixture")
        archive, _ = package.build_package(self.root)
        with zipfile.ZipFile(archive) as stream:
            names = {name.removeprefix("shorts-automation/") for name in stream.namelist()}
            self.assertIsNone(stream.testzip())
        self.assertTrue(
            {
                "docs/guide.md",
                "docs/history/old.md",
                "prompts/agy_footage_supply.md",
                "tests/test_example.py",
                "legacy/batch_generator.py",
                "shorts_automation/__init__.py",
                "shorts_automation/automation/production.py",
                "shorts_automation/footage/creator_footage.py",
                "shorts_automation/automation/run_production_windows.ps1",
                "scripts/windows/setup_windows.ps1",
                "secrets/production.json",
                "requirements-dev.txt",
            }
            <= names
        )
        self.assertFalse(any(name.endswith(".local.json") for name in names))
        self.assertEqual(
            {name for name in names if name.startswith("secrets/")},
            {"secrets/production.json", "secrets/opencode.local.example.json"},
        )
        self.assertNotIn("token.json", names)
        self.assertNotIn("client_secret.json", names)
        self.assertNotIn("storage/usage.sqlite3", names)
        self.assertFalse(any(name.startswith((".venv/", "deployment/")) for name in names))
        self.assertEqual(
            {name for name in names if name.startswith("storage/")}, set(package.MEDIA)
        )

    def test_known_api_secret_in_document_blocks_package_without_echoing_secret(self):
        secret = "fixture-only-private-key-123456"
        self.write("fish.local.json", json.dumps({"api_key": secret}))
        self.write("docs/accidental.md", "Accidental value: " + secret)
        with self.assertRaises(RuntimeError) as raised:
            package.build_package(self.root)
        self.assertIn("docs", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))
        self.assertFalse((self.root / "deployment/shorts-automation-windows.zip").exists())

    def test_nested_oauth_secret_is_detected_in_selected_source(self):
        secret = "fixture-only-oauth-client-secret"
        self.write("client_secret.json", json.dumps({"installed": {"client_secret": secret}}))
        self.write("app.py", "value = " + repr(secret))
        with self.assertRaisesRegex(RuntimeError, "credential detected"):
            package.build_package(self.root)

    def test_secret_in_migrated_folder_blocks_package_without_echoing_value(self):
        secret = "fixture-only-migrated-private-key"
        self.write("secrets/new-provider.json", json.dumps({"api_key": secret}))
        self.write("docs/accidental.md", secret)
        with self.assertRaises(RuntimeError) as raised:
            package.build_package(self.root)
        self.assertNotIn(secret, str(raised.exception))

    def test_missing_selected_media_fails_before_publishing_archive(self):
        (self.root / package.MEDIA[0]).unlink()
        with self.assertRaisesRegex(RuntimeError, "Required transfer files missing"):
            package.build_package(self.root)

    def test_checksum_matches_verified_archive(self):
        archive, count = package.build_package(self.root)
        self.assertGreater(count, len(package.MEDIA))
        checksum = archive.with_suffix(".zip.sha256").read_text(encoding="utf-8").split()[0]
        self.assertEqual(checksum, hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_failed_zip_write_preserves_previous_package_and_cleans_staged_file(self):
        archive, _ = package.build_package(self.root)
        previous = archive.read_bytes()
        with patch(
            "build_transfer_package.zipfile.ZipFile.write",
            side_effect=OSError("simulated disk failure"),
        ):
            with self.assertRaises(OSError):
                package.build_package(self.root)
        self.assertEqual(archive.read_bytes(), previous)
        self.assertFalse(archive.with_name("shorts-automation-windows.partial.zip").exists())


if __name__ == "__main__":
    unittest.main()
