# Current handoff

Snapshot: 2026-10-29. Read this first, then SETUP_WINDOWS.md and the current source.
The complete chronological record is preserved in
[docs/history/HANDOFF_2026-10-28.md](docs/history/HANDOFF_2026-10-28.md). Historical
statements about missing Windows setup, model access or upload integration are
superseded by this summary.

## User decisions

- Keep Windows on the Ryzen 5 4600G / integrated graphics / 16 GB PC.
- Use existing free allowances only. No purchases, upgrades or paid fallbacks.
- Keep Fish and ElevenLabs; retain the selected Fish voice and accepted synchronized
  captions with the moving yellow word highlight.
- User verified Fish's commercial-use restriction concerns selling generated voice
  products and accepted its use for narrated Shorts. Record this as user verification,
  not independent legal advice. No paid upgrade/fallback is authorized.
- Target three English Shorts daily at 07:00, 12:00 and 19:00 America/New_York.
- Maintain at least three confirmed future public releases. The worker targets
  four so one can release while a replacement is prepared. Private previews,
  drafts, past schedules and uncertain uploads do not count toward this minimum.
- No minimum Short duration or script word count (user decision, 2026-10-29).
  Prioritize quality, clarity and a complete payoff without padding. The current
  maximum remains 58 seconds including the narration tail.
- Public scheduled publishing was explicitly enabled by the user on 2026-10-29,
  superseding the earlier pause. The user also explicitly retained Telegram
  upload/scheduling notifications. Maintenance and tests must preserve this mode.
- Use Hermes + Telegram for remote maintenance. AGY handles footage discovery;
  MonoCode/OpenCode remains available as the user's coding interface.
- Footage target is Minecraft parkour like YouTube u7kdVe8q5zs with actual
  creator-posted download links, not dark Minetest cave demos.
- Keep horror stories, but make them scarier and understandable on one listen.
  Female protagonists should use a female voice. New drafts use an editorial
  rewrite and explicit gender metadata; see prompts/story_horror.md and
  docs/STORY_WORKFLOW.md. Fish Official Delia (American English) replaces the rejected Sofiah female voice;
  the previously selected default voice is preserved.

## Working implementation

- Active folder: C:\Users\Pedro\Documents\shorts-automation. Do not use the stale
  original OneDrive copy.
- Native .venv, Python 3.13 and FFmpeg work. Offline regression suite and preview
  pass. Current checks are documented in docs/DEVELOPMENT.md.
- production.py owns automatic premises, durable future slots, retries, media
  validation, optional autoapproval/upload, local health reporting and cleanup.
- ShortsAutomationProduction runs every 30 minutes and at the current user's
  sign-in. Latest inspected task result is 0. PC AC sleep is already disabled.
- enabled=true, publish_enabled=true, private_upload_enabled=false,
  telegram_notify_enabled=true, footage_discovery=creator_downloads. New uploads
  are private with a future publishAt, then YouTube releases them at the assigned
  New York slots. Preparation caps at three only when both upload modes are off.
- Hermes drafting uses the existing openai-codex / gpt-6.1-terra login. Telegram
  upload/scheduling notifications are explicitly authorized; other external
  messages still require an explicit instruction.
- AGY gemini-3.8-flash-medium plans searches and ranks evidence. A bounded Python
  broker reads public video metadata/download pages. Isolated ranking sessions
  avoid terminal permission requests and coding-workspace instructions.
- Creator importer rechecks description permission and posted links, verifies
  public free video bytes, and allocates disjoint 60-second windows. SQLite schema 2
  tracks reserved/rendered intervals; adjacent windows can share a recording but
  overlapping windows cannot. Source admission now occurs before TTS.
- Known creator records supply later unused windows without another AGY discovery
  call. Exhausted video IDs are excluded from new discovery. Legacy whole-source
  claims remain conservative; no history is silently released.
- Live creator import: creator_WGP0e-hQxXg.mp4, 60s, 1080p/60fps. Matching previews
  and evidence remain in storage/reviews/minecraft_creator_quality/.
- Three finished Minecraft Shorts passed full media validation and sampled-frame
  review, using source intervals 5–65, 65–125 and 125–185 seconds. Review manifest
  and contact sheet: storage/reviews/minecraft_batch_20261029_012324/.
  This was the initial preparation batch, before the story revision and public
  activation. Superseded videos retain their files and history.
- A separate private YouTube preview upload succeeded. Receipt is ignored under
  deployment/. Public scheduling was subsequently enabled on 2026-10-29.

## Remaining rollout work

- Fish use for narrated Shorts was accepted based on the user's verification.
  Keep the verified free-offer expiry guard and the selected voice; do not buy a plan.
- Old NodeCore/Minetest previews are retired from the automatic backlog with their
  files/history retained. Their still-future slots are replaced once in chronological
  publishing order for the new Minecraft parkour format.
- Test real reboot and live interrupted-upload reconciliation. Unknown upload
  outcomes must never be automatically reuploaded.
- Source availability is finite; inspect failed jobs and the health report rather
  than assuming three successful daily renders are guaranteed.

## Hygiene and paths

Current docs are in docs/, archived notes in docs/history/, tests in tests/, and
AGY's brief in prompts/agy_footage_supply.md. Workflow implementation now lives in
shorts_automation/ by stage; retired evaluation code lives in legacy/. Root
production.py/orchestrator.py remain as compatibility entry points. All formerly
root JSONs now live in secrets/, including production.json and credentials.
Windows launchers live beside automation/rendering code; setup lives in
scripts/windows/. The installed task's action was migrated and verified to use
shorts_automation/automation/run_production_windows.ps1. Storage database/media
paths are unchanged. Other Python CLIs use the package commands in docs/DEVELOPMENT.md.
Use build_transfer_package.py to include these source trees without credentials
or environments.

Latest offline validation (2026-10-29): 195 tests, Ruff lint/format checks and pip
check passed. Earlier offline Fish preview/full decode, Markdown links and SQLite
integrity checks also passed. Rebuild transfer ZIPs with build_transfer_package.py
after further source changes.
Automatic approval review blocked removal of obsolete root test
bytecode; those ignored files remain and must not be represented as deleted.

Story/voice revision: new text-only review drafts and a 9.4-second female Fish
sample are in storage/reviews/story_horror_v2/. The Sofiah sample was rejected for
its accent; female_voice_Delia_sample.mp3 is the configured replacement sample.
The user accepted the revised stories and Delia sample on 2026-10-28. These
text/audio approvals have not regenerated the three existing rendered videos,
which still contain the earlier stories/voice choices. The approved female-led
story has now completed a separate full Delia render: 45.8 seconds, 1080x1920,
source interval 185–245 seconds, synchronized highlight captions. Full decode,
media/voice checks, sampled frames and SQLite integrity passed. Manifest:
storage/reviews/story_horror_v2/full_video_review.json. This render is local,
not scheduled or uploaded at that milestone. The later public activation below
supersedes the pause described in the earlier session record.

## Workflow review fixes — 2026-10-29

- Footage replenishment now stops behind the three-video backlog guard when both
  upload modes are off. At review time public publishing was disabled and the
  config enabled private-only uploads and Telegram notifications. The later
  explicit public activation supersedes that mode.
- Manual scheduling and bulk previews now respect pending production slot
  reservations in SQLite. An automatic job can still use its own assigned slot.
- New credit sidecars include creator credit_text. Upload metadata also recovers
  that text from older source metadata without duplicating it.
- Newly missed slots are reported on that pass; later expired terminal failures
  count in historical_failed_jobs instead of failing every future pass. Queue
  records/errors/events remain intact. Uncertain uploads and needs_attention jobs
  stay actionable even with a full preparation backlog.
- Removed the 45-second render/validation floor and 120-word draft floor. Prompts
  ask for complete, clear horror without padding; maximum word/duration limits,
  voice selection, captions, source claims and full media checks remain enforced.
- Existing jobs 16ffeac5 and b11b7a39 passed full local validation under the revised
  duration policy and returned from needs_attention to rendered. Their narration
  lasts 40.333 and 43.964 seconds. Footage/story format, retained usage ownership
  and SQLite quick_check passed; no new synthesis, render, upload or message was
  performed during this recovery.
- Test footage locks are isolated in temporary storage so the offline suite can
  run alongside the scheduled worker. Live reboot and interrupted-upload checks
  remain outstanding. Current lint/format and dependency checks are clean.

## Public scheduling activation — 2026-10-29

The user explicitly requested starting public publishing and keeping Telegram
notifications. Config was switched atomically to publish_enabled=true and
private_upload_enabled=false. The previous config and activation receipt are in
ignored deployment/. No existing private preview was made public or reuploaded.

Four current-format videos passed full decode, story/voice/source checks, retained
usage ownership and sampled-frame review. The production pass uploaded all four
and exited successfully with health=ok, no problems and four confirmed Telegram
notifications. YouTube's upload responses returned private status with the exact
assigned future publishAt for every video:

- 2026-10-29 19:00 New York / 20:00 Sao Paulo: The Hatch Behind My Bed,
  https://youtube.com/shorts/orieX-wfe0s
- 2026-10-30 07:00 New York / 08:00 Sao Paulo: Thirty Seconds Ahead of Me,
  https://youtube.com/shorts/PthZtrjj27o
- 2026-10-30 12:00 New York / 13:00 Sao Paulo: The Voice in the Closet,
  https://youtube.com/shorts/hb-mZ1BHL5M
- 2026-10-30 19:00 New York / 20:00 Sao Paulo: The Keeper in the Crate,
  https://youtube.com/shorts/rn9GJJDPqhw

Preflight: storage/reviews/public_rollout_20261029_180606/preflight.json and contact
sheets. Scheduling evidence: each output's .upload-receipt.json and
deployment/public-publishing-scheduled.json. A subsequent videos.list request
received HTTP 403 with the existing upload-only OAuth grant; publication-time
and processing-status reads are not independently verified. Do not treat this as
an uncertain upload or reupload: all four IDs and accepted schedules are retained.
The installed 30-minute worker remains active for future preparation/scheduling.

## Rolling scheduled reserve — 2026-10-29

The user requested never having fewer than three videos scheduled. Production
now uses minimum_scheduled_videos=3 and refills toward four future public uploads,
with a 72-hour planning horizon to leave alternative slots after failures. Ready
automatic videos are scheduled before spending on new drafting; each render is
validated/scheduled immediately and generation/research stops at the target.
The existing one-job-per-pass budget, quality/source claims, free-offer guard and
uncertain-upload protections remain in force. The minimum counts unique real
YouTube IDs with a future scheduled_at, including manually scheduled uploads,
while retaining all past job history. Public scheduling and Telegram remain on.

Health now includes scheduled_buffer with minimum, target, future_scheduled,
deficit, next_release and checked_at. A fresh end-of-pass clock accounts for
videos whose release time passes during work. Below-minimum reserves require
attention; a count of three triggers replenishment. PC/network/provider failures
can still prevent replenishment, so this is an enforced production target rather
than a guarantee of uninterrupted supply or independently read channel state.
Activation was verified with the real worker at 2026-10-29 18:20 UTC: health=ok,
minimum=3, target=4, future_scheduled=4 and deficit=0. Generation, research,
uploads and messages were skipped because the reserve was already full.

## Workflow folder migration — 2026-10-29

The user requested organizing the workflow into folders by responsibility.
Implementation modules now live under shorts_automation/:

- automation/: production worker, durable queue, retries and scheduling coordination.
- stories/: original drafting/editing and voice providers.
- footage/: AGY research, public evidence, creator import and media probes.
- rendering/: pipeline, synchronized highlight captions, FFmpeg and offline preview.
- publishing/: YouTube upload/authentication and Telegram notifications.
- state/: SQLite usage history and shared locks.

legacy/ retains the old batch generator, Reddit/model story fallback and Commons
replenisher. Those commands now use python -m legacy.<module>. Current creator
research no longer imports a legacy module just to obtain its model default;
the saved-draft pipeline loads the old story generator only for explicit calls
without a saved draft. Legacy and current evaluation behavior is otherwise retained.

Root production.py and orchestrator.py are thin delegates, so installed task and
manual Windows launcher paths remain stable. The preview launcher uses the new
module command. config.py remains at the root; config, credentials, database,
original media, provenance, accepted comparisons and recovery backups were not
relocated or deleted. Public scheduling, Telegram, voice selections and the
three-minimum/four-target reserve settings were preserved.

README.md and AGENTS.md identify the folders; docs/DEVELOPMENT.md contains the
source map and current module commands. The README's stale paused-publication
statement was corrected. Source transfers now include shorts_automation/ and
legacy/. OAuth tests use temporary token locks instead of touching the live lock.

Validation: 194 offline tests passed, including runtime-path/launcher and package
boundary checks; 12 CLI help checks, Ruff lint/format, pip check, and the accepted
cached-audio Windows caption preview passed. The installed task action still
targets the same root run_production_windows.ps1. This maintenance did not invoke
live generation, research, authentication, uploads or Telegram delivery. A worker
pass/reboot and interrupted-upload reconciliation were not run as migration tests.

## JSON and Windows launcher migration — 2026-10-29

The user explicitly requested moving root JSONs to secrets/ and keeping launchers
with their workflow. All seven root JSON files were moved byte-for-byte, including
Fish/ElevenLabs voice settings, Telegram route, OAuth client/token, production
settings and the OpenCode example. config.SECRETS_DIR is the shared location;
TTS, authentication, token staging/promotion, Telegram and production use it.
Runner/source/token locks were held for the JSON migration. The folder is Git-ignored.
Runtime story/source/audio/output metadata remains paired with media in storage/.

Windows script locations:

- shorts_automation/automation/: run_orchestrator_windows.ps1 (manual render to
  review), run_production_windows.ps1 (automatic worker), install_production_windows.ps1.
- shorts_automation/rendering/run_preview_windows.ps1: cached-audio offline preview.
- scripts/windows/setup_windows.ps1: environment setup and offline tests.

Each script resolves the project root from its new location. The installed task
action now targets the relocated production launcher; triggers, principal and
settings were compared with a saved XML backup and are unchanged. The backup is
in ignored deployment/. No live production pass was started for the migration.
Publishing, Telegram, voices and reserve settings are unchanged.

Current guides and commands use the new paths. The source-transfer whitelist
includes relocated scripts and only the two noncredential JSONs from secrets/
(production settings and the OpenCode example). All other secrets/ files stay
out; known secret scanning reads the new folder as well as legacy root locations.
195 offline tests passed, including migrated credential paths, voice selection,
package boundaries and secret leakage checks. All five PowerShell scripts passed
syntax parsing. Reboot and interrupted-upload checks remain outstanding.
