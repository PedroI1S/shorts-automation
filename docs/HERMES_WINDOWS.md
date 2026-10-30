# Hermes remote maintenance on Windows

Hermes and the production worker have separate roles. Hermes provides user-requested
remote maintenance through Telegram; deterministic Python/FFmpeg owns production.

Verified in the project history: Hermes v0.22.5 was installed; the configured
openai-codex / gpt-6.1-terra subscription route completed inference and a terminal
call. Numeric Telegram allowlisting and an end-to-end reply were verified.
A user-logon Startup fallback was installed for the gateway after Scheduled Task
registration was refused, and the user reported a successful reboot/sign-in test.
Production Task Scheduler registration later succeeded independently.

These are prior validation results, not a claim that every remote service was
retested during repository cleanup. Current health should be inspected locally
without printing credentials or sending new messages without instruction.

## Project location and environment

The active project is C:\Users\Pedro\Documents\shorts-automation. Old OneDrive
sessions may remember a stale location. Use .venv/Scripts/python.exe and UTF-8.
Windows production launchers load the user's HERMES_HOME if it is not inherited.
AGY has a separate per-user executable resolver for stale PATH environments.

## Recovery notes

The original installation needed local repairs for Windows AppData redirection
and long Python import paths. Recoverable backups are retained under the ignored
deployment/ folder. Hermes updates may replace those local repairs; inspect the
[historical troubleshooting record](history/HERMES_WINDOWS_NEXT.md) before making
changes. Do not delete bootstrap runtimes or install-stamp backups as generic junk.

Keep bot tokens, numeric allowlist data, model credentials and private messages
out of source, archives and chat output. The current worker does not send external
failure notifications; its local health JSON and logs can be inspected via the
already configured maintenance channel.
