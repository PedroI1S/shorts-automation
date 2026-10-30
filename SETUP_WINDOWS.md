# Windows setup and verification

The active PC is already configured. Start with verification, not reinstallation.
Current operations are in [docs/PRODUCTION.md](docs/PRODUCTION.md); superseded
migration instructions are preserved in
[docs/history/SETUP_WINDOWS_MIGRATION.md](docs/history/SETUP_WINDOWS_MIGRATION.md).

## Verify this PC

Run from C:\Users\Pedro\Documents\shorts-automation:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m pip check
powershell -NoProfile -ExecutionPolicy Bypass -File .\shorts_automation\rendering\run_preview_windows.ps1
.\.venv\Scripts\python.exe production.py status
Get-ScheduledTaskInfo -TaskName ShortsAutomationProduction
```

The offline preview consumes no AI allowance. Public scheduling was explicitly
enabled on 2026-10-29; verification and setup must preserve the chosen mode.
When both upload switches are off, a healthy worker can report no work because
its three-video preparation backlog is already full.

## Fresh Windows installation

1. Install Python 3.13 with its launcher, and FFmpeg/ffprobe on PATH.
2. Place the source in a local folder outside OneDrive.
3. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup_windows.ps1`.
   It creates a native .venv, installs requirements and runs the complete suite.
4. Run `shorts_automation\rendering\run_preview_windows.ps1` and check the saved video.
5. Configure credentials privately. Preserve local voice selections. Existing
   Hermes and AGY subscription logins must be configured separately on a new PC.
6. Inspect secrets/production.json before considering task installation. The installer
   starts production preparation and consumes allowances; it is not part of tests.

The existing production task uses normal user privileges and requires sign-in and
an awake PC. A Startup watchdog fallback is available if Task Scheduler refuses
registration. Actual pre-login operation is not provided.

## Private local files

All formerly root JSON files live in the Git-ignored secrets/ folder. This includes
noncredential production settings and the OpenCode example as well as credentials.

secrets/fish.local.json and secrets/elevenlabs.local.json provide api_key/voice_id. The code also
accepts provider-specific environment variables. secrets/client_secret.json and secrets/token.json
hold Google OAuth data. Keep all of them out of chat, Telegram, Git and archives.
Do not print their contents to diagnose setup. `build_transfer_package.py` selects
source and accepted comparison media without these files or virtual environments.

Hermes setup/recovery details: [docs/HERMES_WINDOWS.md](docs/HERMES_WINDOWS.md).
Development tooling: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
