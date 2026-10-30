"""Regression tests: deny network and unexpected external processes by default."""

import atexit
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from shorts_automation.state import source_lock

# Tests must never wait on or create the running worker's operational lock.
_temporary_runtime = tempfile.TemporaryDirectory(prefix="shorts_tests_")
atexit.register(_temporary_runtime.cleanup)
source_lock.LOCK_PATH = Path(_temporary_runtime.name) / "source-media.lock"


def _deny_network(*args, **kwargs):
    raise AssertionError("Network access is forbidden during tests")


socket.socket.connect = _deny_network
socket.socket.connect_ex = _deny_network
socket.getaddrinfo = _deny_network
_original_popen = subprocess.Popen


def _check_command(args):
    # Only local media binaries and the local Python lock probe are permitted.
    if not isinstance(args, (list, tuple)) or not args:
        raise AssertionError("Unexpected subprocess during tests")
    executable = os.path.normcase(os.path.abspath(os.fspath(args[0])))
    name = os.path.basename(executable).lower()
    is_media = name in {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"} and not any(
        "://" in str(arg) for arg in args[1:]
    )
    is_lock_probe = (
        executable == os.path.normcase(os.path.abspath(sys.executable))
        and len(args) >= 3
        and args[1] == "-c"
        and "source_lock" in args[2]
    )
    if not (is_media or is_lock_probe):
        raise AssertionError("Unexpected subprocess during tests: " + name)


class _SafePopen(_original_popen):
    def __init__(self, args, *positional, **kwargs):
        _check_command(args)
        super().__init__(args, *positional, **kwargs)


subprocess.Popen = _SafePopen
