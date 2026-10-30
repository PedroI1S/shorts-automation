# Windows validation — 2026-10-28

Project: `C:\Users\Pedro\OneDrive\Documentos\shorts-automation`.

## Verified on this PC

- Windows 11 Pro for Workstations, 64 bit; Ryzen 5 4600G with Radeon Graphics;
  approximately 15.4 GiB usable RAM (16 GB installed).
- Installed Python 3.13.15 and Gyan FFmpeg 9.0.2 using winget.
- Created native `.venv`; all seven pinned direct dependencies installed.
- `setup_windows.ps1`: all 12 speech timing regression tests passed.
- `run_preview_windows.ps1`: successful cached Fish render, 6.41 seconds wall time
  including Python startup and caption PNG creation. No generation API calls.
- Output: `storage/output/windows_caption_test.mp4`, 1080x1920, 30 fps,
  H.264/AAC, 11.30 seconds, 380,620 bytes. Full FFmpeg decode passed.
- Windows Impact font selected. Inspected frames at 0.08, 0.25 and 0.45 seconds:
  yellow moves through I / HEARD / MY while the caption stays fixed.
- AC sleep timeout is already zero (never); no power settings changed.
- System timezone: E. South America Standard Time (Brasilia, UTC-03:00).
- FFmpeg lists libx264, h264_amf and hevc_amf. AMF is compiled in;
  actual hardware encoding has not been tested.

This is an ultrafast-preset plain-background preview benchmark. It does not
measure the full gameplay renderer's `fast` preset or sustained production load.
Neither voice provider implementation nor caption timing needed changes.

## Remote maintenance setup

The official Hermes installer completed with
`-NonInteractive -SkipBrowser -SkipComputerUse`. CLI verification returned
Hermes v0.22.5, stable, commit `bf0203a794a0`, Python 3.14.9.
`hermes gateway status` confirmed the gateway is not running. No gateway
autostart task was installed. Credentials and gateway configuration require
local user input. See HERMES_WINDOWS_NEXT.md.

Applied and confirmed using the Hermes CLI:
`auth.adopt_external_logins = false`, `fallback_providers = []`, and curator paused.

The CLI reports its source inside Codex's Windows package LocalCache:
`C:\Users\Pedro\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\hermes\hermes-agent`.
Verify `hermes --version` in a fresh standalone PowerShell before relying on
remote access; invocation inside this desktop session alone does not verify
that a new external terminal sees the launcher and its redirected files.

Installer note: uv bootstrap failed with "Missing expected target directory"
under AppData in the desktop app context. Retrying with process-scoped
`UV_PYTHON_INSTALL_DIR` set to the project's ignored
`deployment/hermes-bootstrap-python` successfully installed bootstrap Python
3.14.9. Hermes's own runtime is independent of the project's Python 3.13 venv.

No publishing, production tasks, purchases, or paid model fallbacks were enabled.
The full-pipeline defects listed in HANDOFF.md remain outstanding.
