"""Cross-process, reentrant lock for managed footage operations."""

import os
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from config import STORAGE_DIR

LOCK_PATH = STORAGE_DIR / "source-media.lock"
_guard = threading.RLock()
_local = threading.local()


@contextmanager
def _thread_guard(blocking):
    if not _guard.acquire(blocking=blocking):
        raise BlockingIOError("source lock held by another thread")
    try:
        yield
    finally:
        _guard.release()


@contextmanager
def source_lock(path=None, blocking=True):
    path = Path(path or LOCK_PATH).resolve()
    with _thread_guard(blocking):
        held = getattr(_local, "held", {})
        if path in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if not blocking:
                        raise
                    time.sleep(0.1)
            held[path] = True
            _local.held = held
            try:
                yield
            finally:
                del held[path]
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def synchronized(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with source_lock():
            return function(*args, **kwargs)

    return wrapper
