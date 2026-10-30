"""Legacy Commons evaluation stock; current creator supply is creator_footage.py.

Run explicitly with python -m legacy.replenish_clips from the project root.
The optional AGY call here generates Commons keywords. License/provenance
filtering is not publication clearance. See docs/LEGACY.md for supported paths.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import BACKGROUNDS_DIR, DEFAULT_AGY_MODEL, GAMEPLAY_QUERIES
from shorts_automation.footage.gameplay_fetcher import DEFAULT_QUERY, download_gameplay_clip
from shorts_automation.state.usage_store import UsageStore, source_keys


def count_unreserved_clips(query=None, min_duration=50.0):
    """Return all cached, unreserved, valid background clips matching query (or all if query=None)."""
    store = UsageStore()
    clips = []
    for sidecar in sorted(BACKGROUNDS_DIR.glob("commons_*.source.json")):
        try:
            d = json.loads(sidecar.read_text(encoding="utf-8"))
            p = sidecar.with_name(sidecar.name.replace(".source.json", ".mp4"))
            if query and d.get("query") != query:
                continue
            if not p.is_file():
                continue
            if store.unavailable(source_keys(d)):
                continue
            clips.append(p)
        except (OSError, ValueError):
            continue
    return clips


def ask_agy_for_queries(model=DEFAULT_AGY_MODEL, count=4, prompt_hint=None):
    """Summon AGY Flash non-interactively to brainstorm atmospheric Commons queries."""
    executable = os.getenv("AGY_EXECUTABLE") or shutil.which("agy")
    # A long-running desktop app/task can inherit PATH from before agy's install.
    # Resolve the CLI's per-user installation without changing global settings.
    if not executable:
        installed = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
        if installed.is_file():
            executable = str(installed)
    if not executable:
        raise RuntimeError("Antigravity CLI (agy) not found in PATH.")

    hint = f" Topic aesthetic: {prompt_hint}." if prompt_hint else ""
    prompt = (
        f"Return ONLY a JSON array of {count} distinct search queries to find atmospheric, "
        "eerie background gameplay, maze, cave, voxel, or motion videos on Wikimedia Commons."
        f"{hint} Examples: ['Labyrinth Minetest', 'dark cave exploration', 'dungeon maze motion']. "
        "Do not use tools, browse, delegate or change files. "
        "Strict rule: Return ONLY the raw JSON array of strings, no markdown, no explanation."
    )
    res = subprocess.run(
        [executable, "--model", model, "--print", prompt],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"AGY Flash invocation failed (code {res.returncode}); inspect the CLI locally."
        )

    text = res.stdout.strip()
    # Strip any accidental markdown formatting
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        queries = json.loads(text)
        if (
            isinstance(queries, list)
            and queries
            and all(isinstance(q, str) and 1 <= len(q.strip()) <= 200 for q in queries)
        ):
            return list(dict.fromkeys(q.strip() for q in queries))[:count]
    except json.JSONDecodeError:
        pass
    raise RuntimeError("AGY did not return a bounded JSON array of queries.")


def replenish(target=3, query=None, with_agy=False, agy_model=DEFAULT_AGY_MODEL, prompt_hint=None):
    """Ensure at least `target` unreserved clips are available in the cache."""
    current = count_unreserved_clips(query=query)
    needed = max(0, target - len(current))
    print(f"[*] Available unreserved clips: {len(current)} / target {target}")
    if needed <= 0:
        print("[✓] Footage cache already meets or exceeds target.")
        return current

    print(f"[*] Sourcing {needed} additional clip(s)...")
    downloaded = []

    # Determine query pool
    queries = []
    if query:
        queries.append(query)
    if with_agy:
        print(f"[*] Summoning AGY Flash ({agy_model}) for query discovery...")
        try:
            suggested = ask_agy_for_queries(
                model=agy_model, count=needed + 2, prompt_hint=prompt_hint
            )
            print(f"[+] AGY Flash suggested queries: {suggested}")
            queries.extend(suggested)
        except Exception as e:
            print(f"[!] AGY Flash query discovery warning: {e}; falling back to default queries.")

    if not queries:
        queries = list(GAMEPLAY_QUERIES) or [DEFAULT_QUERY]

    # Attempt downloads across query pool
    for q in queries:
        if len(downloaded) >= needed:
            break
        try:
            print(f"[*] Searching Commons for query: {q!r}")
            path = download_gameplay_clip(query=q, required_duration=60)
            downloaded.append(path)
            print(f"[✓] Successfully cached: {path.name}")
        except Exception as e:
            print(f"[-] Could not source clip for {q!r}: {e}")

    total = len(count_unreserved_clips(query=query))
    print(f"[*] Replenish complete. Total unreserved clips: {total}")
    return downloaded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", type=int, default=3, help="Minimum unreserved clips to maintain (default: 3)."
    )
    parser.add_argument("--query", type=str, default=None, help="Specific search query on Commons.")
    parser.add_argument(
        "--with-agy", action="store_true", help="Summon AGY Flash agent to discover queries."
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_AGY_MODEL, help="AGY model for discovery."
    )
    parser.add_argument(
        "--hint", type=str, default=None, help="Theme hint for AGY query discovery."
    )
    parser.add_argument(
        "--status", action="store_true", help="Print current unreserved footage pool and exit."
    )

    args = parser.parse_args(argv)

    if args.status:
        clips = count_unreserved_clips(query=args.query)
        print(f"Unreserved clips in cache: {len(clips)}")
        for c in clips:
            sidecar = c.with_suffix(".source.json")
            info = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
            print(f"  • {c.name} ({info.get('license', 'unknown')}): {info.get('title', '')}")
        return 0

    replenish(
        target=args.target,
        query=args.query,
        with_agy=args.with_agy,
        agy_model=args.model,
        prompt_hint=args.hint,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
