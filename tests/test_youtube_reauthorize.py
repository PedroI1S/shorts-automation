import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_automation.publishing import youtube_reauthorize as reauth


class ReauthorizationTests(unittest.TestCase):
    def test_missing_scope_never_replaces_existing_token(self):
        with tempfile.TemporaryDirectory() as d:
            active = Path(d) / "token.json"
            candidate = Path(d) / "token-candidate.json"
            self.enterContext(patch.object(reauth, "TOKEN_LOCK", Path(d) / "youtube-token.lock"))
            active.write_text("original")
            candidate.write_text("candidate")
            with patch.object(reauth, "verify_candidate", return_value=False):
                with self.assertRaises(ValueError):
                    reauth.promote(candidate, active)
            self.assertEqual(active.read_text(), "original")
            self.assertTrue(candidate.exists())
