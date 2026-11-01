# YouTube Shorts automation

Original English horror stories, creator-provided Minecraft parkour footage,
local Kokoro-82M narration, synchronized word highlighting, and local FFmpeg renders.

Stories now mix standalone Shorts with connected 3–4-part horror arcs. Early parts
end on concrete cliffhangers, with numbered titles and on-screen continuation cues;
the final part delivers the payoff. Three standalones separate arcs, and each part
uses a normal publishing slot. See [story formats](docs/STORY_WORKFLOW.md).

**Current configuration:** the installed Windows worker has public scheduling
and Telegram notifications enabled. It maintains a minimum of three confirmed
future public releases and refills toward four. Publishing targets are 07:00,
12:00 and 19:00 in America/New_York, following daylight saving time.

## Start here

Coding assistants: read [AGENTS.md](AGENTS.md), then [HANDOFF.md](HANDOFF.md)
and [SETUP_WINDOWS.md](SETUP_WINDOWS.md). These files are in the project root.
For operating instructions, start with [docs/README.md](docs/README.md).

Run commands from this project folder in PowerShell:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe production.py status
powershell -NoProfile -ExecutionPolicy Bypass -File .\shorts_automation\rendering\run_preview_windows.ps1
```

The preview reuses cached audio and makes no generation or upload API calls.
Fresh drafting, narration and footage research consume existing service allowances.
No paid fallback, purchase or subscription upgrade is authorized.

## Project layout

| Location | Purpose |
| --- | --- |
| `shorts_automation/` | Application implementation grouped by workflow stage |
| Root `production.py`, `orchestrator.py` | Compatibility CLI entry points |
| Root `config.py`, `build_transfer_package.py` | Stable path configuration and source-transfer builder |
| `secrets/` | Local credentials and JSON configuration; production settings live here too |
| `scripts/windows/` | Windows environment setup |
| `branding/` | Channel logo, banner, generated source artwork and design prompts |
| `tests/` | Offline regression tests and shared fakes |
| `legacy/` | Retained batch, Reddit/model fallback and Commons replenishment code; explicit evaluation only |
| `docs/` | Current operating and development guides |
| `docs/history/` | Preserved session history and superseded migration notes |
| `prompts/` | Current horror story and AGY footage research briefs |
| `storage/` | Ignored database, media, source evidence, reviews, logs and temporary files |
| `deployment/` | Ignored transfer archives, installation receipts and recovery backups |

```text
shorts_automation/
  automation/   Worker, queue, retries and scheduling coordination
  stories/      Story drafting/editing and narration providers
  footage/      AGY research, public evidence, creator imports and media probes
  rendering/    Video pipeline, captions, FFmpeg and offline preview
  publishing/   YouTube authentication/uploads and Telegram notifications
  state/        SQLite usage history and shared locks
legacy/         Retired evaluation workflows
secrets/        Local credentials and JSON settings
scripts/windows/ Windows environment setup
```

Windows launchers live beside the workflow they launch:

| Script | Purpose |
| --- | --- |
| `shorts_automation/automation/run_production_windows.ps1` | Installed automatic worker; prepares, validates and schedules uploads |
| `shorts_automation/automation/run_orchestrator_windows.ps1` | Manual queue runner; defaults to one job and stops for review without uploading |
| `shorts_automation/automation/install_production_windows.ps1` | Installs/updates the production task; `-Start` starts real production |
| `shorts_automation/rendering/run_preview_windows.ps1` | Offline caption preview using accepted cached audio |
| `scripts/windows/setup_windows.ps1` | Creates/checks the Python environment and runs offline tests |

## Workflows

The automatic path is `production.py` → durable queue → Hermes draft/edit →
verified creator footage → local Kokoro narration → synchronized captions → local FFmpeg
render → media validation → scheduled YouTube upload → Telegram notification.
The [development guide](docs/DEVELOPMENT.md) maps each stage to its source files.

- [Windows setup](SETUP_WINDOWS.md): prerequisites and local verification.
- [Automatic production](docs/PRODUCTION.md): installed task, controls, checks and recovery.
- [Manual queue](docs/ORCHESTRATOR.md): enqueue, render, review and scheduling commands.
- [Creator footage research](docs/FOOTAGE_RESEARCH.md): AGY search, evidence and download adapter.
- [Narration and stories](docs/STORY_WORKFLOW.md): saved drafts, providers and captions.
- [Database](docs/DATABASE.md): story/source claims and interrupted render recovery.
- [Development](docs/DEVELOPMENT.md): tests, lint, packaging and repository conventions.
- [Documentation index](docs/README.md): current guides and historical references.

To prepare one manually queued evaluation video, first import creator footage
with `python -m shorts_automation.footage.creator_footage` and use its printed file path:

```powershell
.\.venv\Scripts\python.exe orchestrator.py enqueue --topic "A night guard finds his name on tomorrow's visitor log" --provider kokoro --background-file <creator-clip.mp4>
powershell -NoProfile -ExecutionPolicy Bypass -File .\shorts_automation\automation\run_orchestrator_windows.ps1 -MaxJobs 1
.\.venv\Scripts\python.exe orchestrator.py status
```

The automatic worker uses the creator-download provider configured in
`secrets/production.json`. Manual `--gameplay` searches and `legacy/replenish_clips.py` retain
legacy Commons behavior; see the footage guide before choosing an entry point.

## Public rollout

The user explicitly enabled public scheduling and Telegram notifications on
2026-10-29. Narration switched to local Kokoro-82M (Apache-2.0) on 2026-11-01.
Old-format previews are retired
without deleting their media, and the backlog uses the Minecraft parkour segment
workflow. A private YouTube upload succeeded; live interrupted-upload reconciliation
and a real production reboot test remain unverified. This project does not guarantee monetization,
content rights, availability or revenue.

Retired workflows are grouped in `legacy/`; use the module commands in
[the legacy guide](docs/LEGACY.md) for explicit evaluation. They have known
persistence/fallback limitations. Use `production.py` and `orchestrator.py`
for production development.

Credentials stay in ignored local files; never paste them into chat, Telegram,
source control or an archive. Use `build_transfer_package.py` for source transfers.
Read [HANDOFF.md](HANDOFF.md) when continuing implementation.
