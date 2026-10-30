# Legacy and evaluation paths

Old evaluation implementations are grouped in `legacy/`. They remain available
for explicit experiments and retained manual modes. The installed creator-download
workflow does not select them as a fallback.

| Entry point | Status |
| --- | --- |
| `legacy/batch_generator.py` | Old batch/manifest flow; known scheduling, persistence and output-move limitations |
| `legacy/content_hunter.py` | Old Reddit/Ollama/Gemini/template story fallback, loaded only by a manual pipeline call without a saved draft |
| `legacy/replenish_clips.py` and manual `--gameplay` | Commons evaluation sourcing; `--with-agy` here brainstorms Commons queries, not the creator-download broker |
| `youtube_uploader.py --manifest` | Direct legacy uploads without the durable queue's idempotency guarantees |

Use production.py for the automatic workflow, orchestrator.py for manual queue
operations, and agy_footage_research.py / creator_footage.py for current creator
footage discovery/import. No legacy path should become a silent fallback for the
current creator-download worker. `shorts_automation/footage/gameplay_fetcher.py`
also serves current creator imports and the rendering pipeline's media probes.

## Migrated legacy commands

Run from the project root with the native virtual environment. The three legacy
implementations moved on 2026-10-29; their former root module paths are retired.
Root Python queue entry points and storage paths remain stable. JSON settings
now live in secrets/ and Windows launchers beside their workflows; the installed
task action was migrated to the automation launcher. Implementations live in shorts_automation/;
see [the current source map and commands](DEVELOPMENT.md).

| Former command or import | Current explicit equivalent |
| --- | --- |
| `python batch_generator.py ...` | `python -m legacy.batch_generator ...` |
| `python replenish_clips.py ...` | `python -m legacy.replenish_clips ...` |
| `from content_hunter import generate_story` | `from legacy.content_hunter import generate_story` |
| `from replenish_clips import replenish` | `from legacy.replenish_clips import replenish` |

For an offline CLI check:

```powershell
.\.venv\Scripts\python.exe -m legacy.batch_generator --help
.\.venv\Scripts\python.exe -m legacy.replenish_clips --help
```

Running these workflows beyond help can consume allowances and create files.
The manual `orchestrator.py replenish` command remains available and explicitly
loads the legacy Commons replenisher. Existing fixed/antigravity evaluation modes
remain supported; secrets/production.json still selects creator_downloads.

Historical exploration and defects are recorded in history/. Media, source
evidence, credentials and database history were not moved or deleted with this
source reorganization. Unconnected helpers such as source_cleanup.py are not
evidence that automatic media deletion is enabled.
