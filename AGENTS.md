# Project instructions

Read HANDOFF.md first, then SETUP_WINDOWS.md, and inspect the current source.
Use current guides in docs/; docs/history/ preserves superseded session notes.

## Folder map

- `shorts_automation/`: implementation grouped into automation/, stories/,
  footage/, rendering/, publishing/ and state/. Use absolute package imports.
- Root: production.py/orchestrator.py compatibility entry points, config.py
  and build_transfer_package.py. Runtime media/database paths still resolve here.
- `secrets/`: all formerly root JSONs, including credentials, provider/voice
  settings, production.json and the OpenCode example. Use config.SECRETS_DIR.
- Windows launchers live beside automation/rendering code; environment setup
  is scripts/windows/setup_windows.ps1. The installed task uses the automation launcher.
- `legacy/`: retained old batch, story fallback and Commons replenisher; invoke
  with `python -m legacy.<module>` from the root. Never use as an automatic fallback.
- `docs/`, `prompts/`, `tests/`: current guides, AI briefs and offline regressions.
- `storage/`, `deployment/`: private runtime data and recovery/build artifacts.
  Files can be referenced by absolute paths in SQLite; do not reorganize them blindly.
- See docs/DEVELOPMENT.md for the source map and docs/LEGACY.md for migrated commands.

## User preferences

- Keep Windows on the Ryzen 5 4600G / integrated graphics / 16 GB PC.
- Use APIs/existing subscription allowances for AI and local FFmpeg rendering.
- Free services only: no purchases, upgrades or silent paid fallbacks.
- Keep Fish Audio and ElevenLabs available. Preserve the chosen Fish voice,
  synchronized captions and moving yellow word highlight.
- Three daily English Shorts target 07:00, 12:00 and 19:00 America/New_York.
- Maintain at least three confirmed future public releases. Replenish toward four
  to keep one extra above that minimum; count future scheduled uploads, not drafts
  or private previews. Keep allowance, source, quality and upload-uncertainty guards.
- Shorts have no minimum duration or word count. Prioritize story quality and a
  complete payoff without padding; retain the current maximum duration guard.
- Automatic Shorts are series-only (user decision, 2026-10-31): coherent 3/4-part
  arcs that alternate between narrated first-person horror and chat-overlay
  drama/cheating/revenge text threads voiced by each sender. Early episodes need
  concrete cliffhangers; the final episode pays off the main threat. Preserve one
  narrator and voice (one stable voice per chat sender), numbering and ordered release. Prepare/validate the whole arc before
  scheduling Part 1; never skip an uncertain or failed continuation. A prepared
  arc may briefly exceed the four-video reserve target when uploaded together.
- The user explicitly enabled public scheduling on 2026-10-29, with Telegram
  notifications. Preserve the publication mode during maintenance and setup;
  only an explicit user instruction authorizes changing it.
- Hermes + Telegram provides remote maintenance. AGY manages creator-footage
  discovery. The user also uses MonoCode/OpenCode.
- Footage should match the Minecraft parkour reference u7kdVe8q5zs, using actual
  creator-posted download links. Do not silently substitute dark cave demos.

## Development and state

- Use .venv/Scripts/python.exe with PYTHONUTF8=1. Tests are in tests/;
  run `python -m unittest discover -v` from the root. See docs/DEVELOPMENT.md.
- Keep root scheduled-task entry points and config/storage paths stable unless
  the task is explicitly migrated and verified.
- Preserve local credentials, database history, source provenance and accepted
  media. Never print credential contents or include them in packages.
- secrets/ is Git-ignored. The transfer builder permits only its two noncredential
  JSONs (production settings and the OpenCode example); all credential JSONs stay out.
- Use build_transfer_package.py for source transfers. Its whitelist excludes
  environments and secrets and includes shorts_automation/, legacy/, docs/,
  prompts/ and tests/.
- Tests must use temporary workspaces for every filesystem mutation and mock
  model/TTS/upload calls. Live generation, research and upload checks are separate
  actions that consume existing allowances or change external state.
- Do not mistake rendering success for commercial rights, monetization eligibility
  or verified unattended readiness. Current limitations are in HANDOFF.md.
