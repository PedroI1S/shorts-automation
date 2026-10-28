# Project context for the next coding session

Read `HANDOFF.md` first, then `SETUP_WINDOWS.md`, and inspect the current source.
The user is moving this YouTube Shorts prototype from a Mac to their Windows PC
(Ryzen 5 4600G, integrated graphics, 16 GB DDR4) for eventual 24/7 operation.

User preferences established in the session:

- Keep Windows. Use APIs for AI work and benchmark local FFmpeg rendering.
- Use free services for now; no purchases, upgrades, or silent paid fallbacks.
- Keep Fish Audio and ElevenLabs available. Fish's selected voice is currently
  preferred, but the user attributes the difference to voice selection.
- Preserve the improved synchronized captions and moving yellow word highlight.
- User wants Hermes with Telegram for remote maintenance and already uses
  MonoCode, which runs installed agent CLIs including OpenCode.
- Model connectivity for Hermes and automated story generation remains unresolved.

Start with setup checks and the offline preview. Twelve regression tests last
passed on the Mac. Windows scripts have not been executed on the target PC.
Uploads and unattended production are not enabled; known scheduling, persistence,
and duplicate-upload defects remain. Do not mistake README marketing claims for
verified readiness or monetization eligibility.

API keys are in ignored local credential files when present. Do not print their
contents or include them in packages. Use `build_transfer_package.py` to build a
transfer archive with the selected test media and without secrets or environments.
