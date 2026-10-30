# Development

Run commands from the project root with Python 3.13. Workflow implementation
lives in shorts_automation/, grouped by responsibility. Root production.py and
orchestrator.py delegate to the package for CLI compatibility. Windows launchers
live beside automation/rendering code; the installed task uses the automation
launcher. config.py anchors media/database paths at the project root and JSON
settings/credentials in secrets/. Other Python CLIs use `python -m <package.module>`.

## Layout and responsibilities

- `tests/` contains offline regressions; `tests/helpers.py` contains shared fakes.
- `legacy/` contains the old batch generator, Reddit/model story fallback and
  Commons replenisher. The saved-draft pipeline loads the old story generator
  only when explicitly called without a saved draft. Creator research gets its
  shared AGY model default from config.py, without importing legacy code.
- `docs/` contains current playbooks. `docs/history/` contains superseded notes.
- `prompts/` contains versioned AI instructions. The AGY runner loads its brief
  relative to config.BASE_DIR, independent of the caller's working directory.
- `deployment/` contains ignored build artifacts and local installation/recovery
  receipts. Do not delete recovery backups as generic cache cleanup.

### Source map

| Stage or tool | Source files |
| --- | --- |
| `shorts_automation/automation/` | `production.py` coordinates automatic work; `orchestrator.py` owns queue/review/upload reservations |
| `shorts_automation/stories/` | `draft_story.py` drafts/edits; `tts_engine.py` handles voice selection, providers and timestamps |
| `shorts_automation/footage/` | `agy_footage_research.py`, `creator_evidence.py`, `creator_footage.py`, `gameplay_fetcher.py` handle discovery, evidence, imports and probes |
| `shorts_automation/rendering/` | `pipeline.py`, `subtitle_engine.py`, `video_compiler.py`, `speech_preview.py` handle assembly, captions and previews |
| `shorts_automation/publishing/` | `youtube_uploader.py`, `youtube_reauthorize.py`, `telegram_notifier.py` handle uploads, credentials and notifications |
| `shorts_automation/state/` | `usage_store.py` and `source_lock.py` retain usage history and coordinate access |
| Root | `production.py`, `orchestrator.py`, `config.py`, `build_transfer_package.py` |
| `scripts/windows/` | Windows environment setup |
| `secrets/` | Local JSON configuration and credentials; Git-ignored |

`footage/source_cleanup.py` is an unconnected helper, not called by the worker.
Its presence does not enable automatic media deletion. `gameplay_fetcher.py`
contains retained manual Commons sourcing and media probes shared by current imports.

### Module commands

```powershell
.\.venv\Scripts\python.exe -m shorts_automation.stories.draft_story --help
.\.venv\Scripts\python.exe -m shorts_automation.footage.agy_footage_research --help
.\.venv\Scripts\python.exe -m shorts_automation.footage.creator_footage --help
.\.venv\Scripts\python.exe -m shorts_automation.rendering.pipeline --help
.\.venv\Scripts\python.exe -m shorts_automation.publishing.youtube_uploader --help
.\.venv\Scripts\python.exe -m shorts_automation.publishing.youtube_reauthorize --help
.\.venv\Scripts\python.exe -m shorts_automation.state.usage_store --help
```

These help commands are offline. Actual generation, research, authentication and
upload operations have their normal side effects. Retired workflows use
the [legacy module commands](LEGACY.md). Run module commands from the root;
do not execute package files by their filesystem path.

### Runtime folders

| Folder | Contents and retention |
| --- | --- |
| `storage/stories/`, `storage/audio/` | Saved drafts and cached narration/timestamps; preserve for retries |
| `storage/backgrounds/` | Creator originals, prepared segments and provenance; preserve claims and sidecars |
| `storage/output/`, `storage/reviews/` | Rendered videos, receipts, approved comparisons and review evidence; preserve history |
| `storage/temp/`, `storage/logs/` | Generated caption assets and pass logs; worker prunes only its configured aged files |
| `storage/usage.sqlite3` | Durable jobs, source/story claims, schedules and notification history; preserve |
| `deployment/` | Private recovery backups, installation receipts, transfer archives and Hermes runtime repairs |

Old media is not unused merely because its preview was superseded. SQLite,
metadata and review manifests can reference it. Leave it in place during source
organization; see [database cleanup limitations](DATABASE.md).

## Checks

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m pip check
```

Run one group with `python -m unittest tests.test_production -v`.
Dev tooling is pinned separately from runtime requirements. Ruff is configured
locally in pyproject.toml so checks do not inherit unrelated parent settings.
The formatter and import rules keep source consistent without changing runtime
paths or provider choices. Editor/Git line endings are explicit for Windows scripts.

Tests must isolate filesystem mutations in temporary directories and mock model,
TTS, research and upload calls. Some render regressions intentionally invoke local
FFmpeg against tiny generated fixtures. No test should refresh credentials, launch
production, send Telegram messages or upload a video. Live service checks require
separate, clearly scoped work and consume allowances.

## Offline preview

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\shorts_automation\rendering\run_preview_windows.ps1
```

This reuses the accepted Fish audio/metadata and writes windows_caption_test.mp4.
It preserves synchronized captions and the moving yellow word highlight without
an AI request. It is separate from the unit suite.

## Transfer package

```powershell
.\.venv\Scripts\python.exe build_transfer_package.py
```

The builder selects root source/configuration, shorts_automation/, legacy/,
docs/, prompts/, tests/ and only its explicit comparison-media whitelist.
It includes only the explicitly selected noncredential secrets/production.json
and secrets/opencode.local.example.json from secrets/. All other JSONs in that
folder are excluded. It excludes local credentials, database,
background footage, reviews, environments and recovery backups. Known local API
and OAuth secret values are checked against selected bytes without being logged.
Symlinks or sources resolving outside the project are rejected. The ZIP is
published atomically after its integrity check and gets a SHA-256 sidecar.

Do not manually ZIP the project. A source transfer is not an operational backup:
move database history and private credentials separately when moving machines.
Do not include storage/ wholesale just because it is Git-ignored.

## Cleanup policy

The worker only prunes aged generated caption directories and production logs.
Media, narration timestamps, source evidence, database history, voice selections
and credentials are retained. A disk-space floor stops generation before the disk
fills. Developer caches are ignored. Current root __pycache__ files can be removed
when no tests or worker import is active; do not recursively purge environments or
storage as part of ordinary formatting or linting.
