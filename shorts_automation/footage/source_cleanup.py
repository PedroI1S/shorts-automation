"""Conservative cleanup of completed managed prepared creator segments.

Call only when all footage readers and writers participate in source_lock.
"""

import hashlib
import json
import re
from pathlib import Path

from config import BACKGROUNDS_DIR
from shorts_automation.state.source_lock import source_lock
from shorts_automation.state.usage_store import (
    SEGMENT_POLICY,
    segment_range,
    source_keys,
    source_origins,
)


def cleanup_exhausted_segments(root, store):
    root = Path(root).resolve(strict=True)
    if root != BACKGROUNDS_DIR.resolve():
        raise ValueError("Cleanup root must be the configured backgrounds directory.")
    removed = 0
    with source_lock():
        for sidecar in root.glob("creator_*.source.json"):
            try:
                if sidecar.is_symlink() or sidecar.resolve().parent != root:
                    continue
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                if meta.get("segment_policy") != SEGMENT_POLICY:
                    continue
                interval = segment_range(meta)
                if interval is None:
                    continue
                origins = source_origins(meta)
                identity = meta.get("youtube_video_id")
                if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                    continue
                expected = f"creator_{identity}_{interval[0]:09d}_{interval[1]:09d}"
                if sidecar.name != expected + ".source.json":
                    continue
                video = root / (expected + ".mp4")
                if video.is_symlink() or not video.is_file() or video.resolve().parent != root:
                    continue
                if hashlib.sha256(video.read_bytes()).hexdigest() != meta.get("sha256"):
                    continue
                with store.connect() as db:
                    keys = list(dict.fromkeys(origins + source_keys(meta)))
                    if any(
                        db.execute(
                            "SELECT 1 FROM claims c LEFT JOIN jobs j ON c.job_id=j.id "
                            "WHERE c.key=? AND (j.status IS NULL OR j.status != 'rendered')",
                            (key,),
                        ).fetchone()
                        for key in keys
                    ):
                        continue
                    rows = [
                        row
                        for origin in origins
                        for row in db.execute(
                            "SELECT s.start_ms,s.end_ms,j.status FROM source_segments s "
                            "LEFT JOIN jobs j ON s.job_id=j.id WHERE s.source_key=?",
                            (origin,),
                        )
                    ]
                    if any(status != "rendered" for _, _, status in rows):
                        continue
                    if not any(
                        (a, b) == interval and status == "rendered" for a, b, status in rows
                    ):
                        continue
                video.unlink()
                removed += 1
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return removed
