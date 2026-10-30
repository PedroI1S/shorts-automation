"""Safety checks for the test suite's side-effect guard."""

import socket
import subprocess
import unittest


class HermeticSafetyTests(unittest.TestCase):
    def test_network_connections_are_blocked(self):
        with socket.socket() as sock, self.assertRaisesRegex(AssertionError, "Network access"):
            sock.connect(("127.0.0.1", 1))

    def test_hermes_process_is_blocked(self):
        with self.assertRaisesRegex(AssertionError, "Unexpected subprocess"):
            subprocess.run(["hermes", "send", "--to", "telegram:123"], check=True)

    def test_media_network_input_is_blocked(self):
        with self.assertRaisesRegex(AssertionError, "Unexpected subprocess"):
            subprocess.run(["ffmpeg", "-i", "https://example.invalid/a", "output.mp4"], check=False)
