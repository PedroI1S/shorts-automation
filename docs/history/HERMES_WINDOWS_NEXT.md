# Hermes + Telegram: finish locally

## Latest verified status — 2026-10-28

Telegram now verified end to end: numeric-only allowlist passed inspection,
one Telegram inbound message and one completed Hermes response were recorded.
Gateway connected successfully with healthy polling. No message content, IDs,
or bot token was printed during verification.

Installed login auto-start via `hermes gateway install`. Windows refused the
Scheduled Task without administrator approval; elevation was not requested and
Hermes installed its Startup-folder fallback instead:
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Hermes_Gateway.vbs`.
Stopped the gateway cleanly and invoked this exact VBS entry; it started a new
gateway process successfully. Real reboot/sign-in recovery remains untested.
This is login startup, not a boot service or verified crash-recovery system.
Production scheduling and publishing remain disabled.

Telegram setup follow-up: token and allowlist are now saved locally. The wizard
raised a restart timeout, but the gateway continued booting while installing
Telegram dependencies. Logs subsequently confirmed healthy getUpdates polling
and connection to Telegram (manual gateway, no login task).
The saved TELEGRAM_ALLOWED_USERS value contains letters rather than a numeric
user ID; it needs local correction before the user's DM is expected to work.
No token or actual allowlist value was printed during diagnosis.

Launcher follow-up: Hermes regenerated its EXE using the virtualized Python path
after the earlier one-time repair. Pinned the source install stamp's supported
`runtimeDir` field to the physical LocalCache tools directory and regenerated
both the internal `.hermes/bin/hermes.exe` and public `bin/hermes.exe` using
Hermes's own publication routines. Verified regeneration selects the physical
interpreter, checked the embedded EXE shebang, and loaded `gateway setup --help`.
Original stamp backup: `deployment/hermes-install-stamp.before-runtime-path.json`.
External interactive setup is still pending verification. Recheck after updates
that rewrite the install stamp.

The user selected `openai-codex` / `gpt-6.1-terra` using subscription login.
An authenticated Hermes request succeeded and executed `pwd` in the Shorts
project, exit 0. This verifies both inference and a terminal tool call.
Fallback providers remain empty and borrowed CLI logins remain disabled.
Groq is optional; no Groq API key is required for the verified subscription route.

A second Windows portability issue was fixed: the OpenAI SDK's screenshot-param
module path was 261 characters and Windows LongPathsEnabled is 0. The file exists
via the extended path, but normal Python import failed. A local change to Hermes's
`pm/environments.py::activate_dependencies` uses GetShortPathNameW to select the
existing 8.3 site-packages alias before imports. Full SDK import now passes.
The original file is backed up in this project's ignored
`deployment/hermes-environments.before-short-path.py`. Hermes updates may replace
this local fix; recheck SDK imports after updating. No registry settings changed.

The running manual gateway was cleanly restarted to load this fix. No login
autostart task was installed. Telegram token and user allowlist are still absent
from the checked profile; run `hermes gateway setup` locally next.

The earlier Groq proposal and installer troubleshooting below are retained as
history; subscription model/tool connectivity is now verified.

Hermes v0.22.5 installation completed and its CLI version was verified in the
Codex session. Gateway status is stopped. First check `hermes --version` in a
fresh standalone PowerShell: Windows package AppData redirection affected this
installation, so availability outside Codex still needs verification.

Follow-up: standalone PowerShell could not find `hermes`. The actual launcher
directory below was added to the user PATH and its CLI version checked:
`C:\Users\Pedro\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\hermes\bin`.
Existing terminals can invoke the full executable path; a fresh shell should
pick up the corrected PATH. External-shell verification remains pending.

The external shell then exposed a second issue: the EXE embedded the virtualized
Python path `AppData\Local\hermes\tools\...`, which does not exist outside Codex.
Rebuilt `hermes.exe` using Hermes's own `mint_launcher`, binding the physical
LocalCache Python path above, and set user `HERMES_HOME` to that same physical
Hermes root. Verified the embedded interpreter exists, `--version` works, and
`model --help` loads. Existing PowerShell sessions must refresh HERMES_HOME:
`$env:HERMES_HOME = [Environment]::GetEnvironmentVariable('HERMES_HOME','User')`.
External interactive model setup is still pending user verification.

## Free model route

OpenCode's official Hermes guide still says free chat models require OpenCode
and return HTTP 403 from Hermes. MonoCode/OpenCode access is separate.

Suggested first test: Groq Free plan, custom OpenAI-compatible endpoint
`https://api.groq.com/openai/v1`, model `openai/gpt-oss-120b`.
Groq currently lists this model in its Free plan limits (30 requests/minute,
1,000/day, 8,000 tokens/minute and 200,000/day); your account's Limits page is
authoritative. Agent prompts/tools can exhaust a quota quickly.

1. Create a free account at https://console.groq.com/ and create an API key there.
   Keep the organization on Free; do not add a payment method or upgrade.
2. Open a fresh PowerShell after Hermes installation. Run `hermes --version`.
3. Run `hermes model`; choose Groq if offered, otherwise a custom endpoint.
   Enter the endpoint above, the key locally, and the exact model ID above.
4. Keep fallback providers empty. Do not import other paid provider logins.
   In `config.yaml`, `auth.adopt_external_logins: false` disables automatic
   borrowing of other CLI credentials; `fallback_providers: []` keeps the
   provider fallback chain empty. Check any existing configuration before editing.
5. Test a short chat, then ask Hermes to read this project's AGENTS.md and report
   its working directory using its terminal tool. A chat-only response does not
   establish successful tool calling. Stop on quota/auth errors and inspect them;
   do not switch to a billed route.

Do not paste keys into this chat or Telegram. The proposed model route is not
verified until an authenticated Hermes chat and tool call succeed.

## Telegram (not configured yet)

1. In Telegram open the official verified @BotFather account, run `/newbot`,
   choose a name and unique bot username. Keep the resulting bot token local.
2. Run `hermes gateway setup` in local PowerShell; choose Telegram and enter the
   token there. Allow only your numeric Telegram user ID; never use `*`.
   Follow Hermes's pairing/setup instructions to obtain/approve your identity.
3. After model validation, run `hermes gateway start`. Open your bot privately
   and send a short test. Then ask it to read AGENTS.md at the project path.
4. Only after replies work, run `hermes gateway install`, and check
   `hermes gateway status`. Verify restart and real reboot/sign-in behavior.
   The native scheduled task runs at user logon, not necessarily machine boot.

Default native installation paths:

- CLI: `%LOCALAPPDATA%\hermes\bin\hermes.exe`
- Configuration and secrets: `%LOCALAPPDATA%\hermes\`
- Source: `%LOCALAPPDATA%\hermes\hermes-agent\`

Keep the production scheduler separate. No YouTube uploads are authorized by
this remote-control setup.

## Verified references (2026-10-28)

- https://hermes-agent.nousresearch.com/docs/user-guide/windows-native
- https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram/
- https://hermes-agent.nousresearch.com/docs/integrations/providers
- https://dev.opencode.ai/v2/docs/console/harnesses/hermes
- https://console.groq.com/docs/rate-limits
- https://console.groq.com/docs/models
