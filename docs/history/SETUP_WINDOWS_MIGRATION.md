# Windows PC setup: Hermes + Telegram + Shorts

Windows validation on 2026-10-28: prerequisites installed, all 12 tests passed,
and the offline Fish preview rendered successfully. See WINDOWS_VALIDATION.md.
For the remaining model-account and Telegram setup, see HERMES_WINDOWS_NEXT.md.

This PC stays on Windows. Hermes provides remote maintenance through Telegram.
The Python project renders videos. Windows Task Scheduler will launch production
jobs after restart and duplicate-upload handling are ready. No production schedule
is installed by the setup scripts in this package.

## 1. Install Hermes on the PC

Open PowerShell on Windows and run the official installer:

```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

Reopen PowerShell afterward. Follow the setup prompts. Model-provider selection
is still pending for Hermes. MonoCode is confirmed to run installed OpenCode CLI
and reuse its existing login, rather than provide its own model API. That explains
the existing free DeepSeek access; it does not establish free access through a
direct Hermes endpoint. If a supported OpenAI-compatible
endpoint is available, `hermes model` can configure its base URL, API key and exact
model ID; enter the key locally. Verify chat and tool calling through Hermes.
Do not configure a paid fallback or buy credits.

`opencode.local.example.json` is a local configuration worksheet, not an automatic
Hermes import. Copy to `opencode.local.json` if useful; the latter is Git-ignored.

Official references:
- https://hermes-agent.nousresearch.com/docs/user-guide/windows-native
- https://hermes-agent.nousresearch.com/docs/user-guide/configuration
- https://hermes-agent.nousresearch.com/docs/integrations/providers

OpenCode's current Hermes guide says its free chat models return HTTP 403 from
Hermes, while paid/Go models are supported. A frontend that drives the OpenCode
CLI is a different connection. Do not assume the same free access is available
through a direct Hermes provider connection:
https://dev.opencode.ai/v2/docs/console/harnesses/hermes

### Optional MonoCode connection from the Mac

MonoCode can connect to the Windows PC over SSH, install a matching host package,
and run agent sessions there. Install and log in to OpenCode on the Windows PC
under the same account used for SSH. Enable and verify Windows OpenSSH Server,
then use MonoCode on the Mac: Settings -> Connections -> Add machine. Follow the
SSH setup prompts; do not open a model server to the public internet.

This remote feature is experimental. Its Windows host uses a per-user scheduled
task and requires that same user to remain signed in and the PC awake. Locking
the desktop is supported; signing out or rebooting interrupts agents, and the
task starts again at the next login. Verify recovery on the actual PC.

Use MonoCode/OpenCode for remote coding from the Mac, and Hermes/Telegram for
phone-based maintenance if the separate Hermes model connection is configured.
The production video scheduler remains independent of those interfaces.

References:
- https://github.com/hardbeat920/monocode/blob/main/docs/providers.md
- https://github.com/hardbeat920/monocode/blob/main/docs/remote-access.md

## 2. Connect Telegram

In Telegram, create your own bot with @BotFather using `/newbot`. Keep its token
local. Find your numeric Telegram user ID, then run on the Windows PC:

```powershell
hermes gateway setup
```

Select Telegram. Enter the bot token and allow only your numeric Telegram user ID.
Test the bot privately. Once setup and model access work:

```powershell
hermes gateway install
hermes gateway start
hermes gateway status
```

On native Windows, the installed Hermes task starts at user logon. It does not
guarantee availability before sign-in after a reboot. Test a real reboot and sign-in,
and check Telegram replies again. Before leaving the PC unattended we still need
to configure and test the required recovery behavior. Disable automatic sleep
while plugged in; the display can still turn off.

Official references:
- https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram/
- https://hermes-agent.nousresearch.com/docs/user-guide/messaging

## 3. Install the project prerequisites

Install Python 3.13 for Windows with its Python launcher:
https://www.python.org/downloads/windows/

Install a Windows FFmpeg build including ffmpeg.exe and ffprobe.exe, and add its
bin directory to PATH. Windows builds are linked from:
https://ffmpeg.org/download.html

Extract this package to a local folder such as `C:\YouTube\shorts-automation`.
Reopen PowerShell in that folder. Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_preview_windows.ps1
```

The execution-policy setting applies only to these PowerShell processes. Setup
downloads the pinned Python dependencies; the preview reuses the included Fish
audio and timestamps, without any TTS or LLM API call. No upload occurs.

Open `storage\output\windows_caption_test.mp4`. Verify voice playback, three-word
captions, moving yellow highlights, and readable fonts. Windows fonts are detected
automatically; `SUBTITLE_FONT_PATH` can override the font.

The dependency versions were exercised on the Mac. Native Windows installation,
render speed, and hardware behavior must be verified on the target PC.

## 4. Move credentials separately

This archive excludes API keys, Google OAuth credentials, tokens, virtual
environments, and downloaded gameplay. Transfer `fish.local.json` and
`elevenlabs.local.json` separately using a private method, or enter their contents
locally using the example files. Never paste credentials into a Telegram message.

The current ElevenLabs library voice requires a paid plan via API. The successful
free-plan sample used built-in George through a temporary voice override; the saved
credentials still contain your original selection. See README.md before retesting.

The included Fish clip is for local evaluation. Confirm applicable commercial
rights before publishing provider-generated content. The selected free model and
pricing must be rechecked when moving to unattended production.

## 5. Give Hermes the project context

Send the bot a message like:

> My Shorts project is at C:\YouTube\shorts-automation. Read SETUP_WINDOWS.md
> and README.md. Use .venv\Scripts\python.exe with PYTHONUTF8=1. The offline
> preview is run_preview_windows.ps1. Check whether the tests pass and tell me
> where the preview was saved. Keep API keys out of responses. We are testing
> free services and have not enabled uploads or scheduled production yet.

Hermes model access must be tested separately from the Fish/ElevenLabs voice APIs.

## Before unattended production

- Integrate and verify the working OpenCode endpoint for script generation.
- Finish persistent job status, retries, and duplicate-upload prevention.
- Fix timezone scheduling and ensure every selected slot is in the future.
- Benchmark one render at a time on the Ryzen PC.
- Test recovery after network loss, a failed job, and a reboot.
- Configure production tasks separately from the Hermes remote-control task.

The current project is a tested local prototype; these steps remain before calling
the whole system ready for unattended operation.
