# Current handoff

Snapshot: 2026-11-01. Read this first, then SETUP_WINDOWS.md and the current source.
The complete chronological record is preserved in
[docs/history/HANDOFF_2026-10-28.md](docs/history/HANDOFF_2026-10-28.md). Historical
statements about missing Windows setup, model access or upload integration are
superseded by this summary.

## Local Kokoro narration — 2026-11-01

At the user's request all narration now uses hexgrad/Kokoro-82M (Apache-2.0)
locally on the CPU; Fish Audio, ElevenLabs and Edge were removed from the code,
and secrets/fish.local.json and secrets/elevenlabs.local.json were moved to the
Windows Recycle Bin. The user should also revoke those API keys on the provider
dashboards. Kokoro needs Python <3.13, so it runs in `.venv-kokoro` (Python 3.12,
CPU torch) through shorts_automation/stories/kokoro_worker.py; the main .venv is
unchanged. Voices: config.KOKORO_VOICES (am_fenrir / af_heart narrate; four more
per gender for chat contacts, so same-gender contacts work). Speed 1.1; the
pre-TTS duration gate uses 3.0 words/s (measured 3.3-3.7).

secrets/production.json now has tts_provider="kokoro" without the Fish fields;
publication mode and story_format were not changed. The four queued, undrafted
jobs were switched from fish to kokoro (backup:
storage/usage.pre-kokoro-2026-11-01T030947.sqlite3). The eleven already scheduled
uploads, including the complete 3-part arc, keep their Fish audio and history.
Validation on Windows: full offline suite and Ruff on changed files passed; a real
9 s narration + caption preview (storage/output/kokoro_caption_test.mp4) and a
real two-voice chat (af_heart/af_bella, 14.4 s audio in 20.7 s) were generated.
No live drafting, full production render or upload was run with Kokoro yet.

## Narrated horror writing upgrade — 2026-10-31

At the user's request the narrated horror series brief, editorial pass and
premises were upgraded: stronger openings and cliffhangers, one learnable
threat rule per arc, recent-arc avoidance and a cliché check on new drafts.
See docs/STORY_WORKFLOW.md. 265 offline tests pass; no live drafting was run,
so the first upgraded arc has not been reviewed yet.

## Series-only production with chat arcs — 2026-10-31

The user requested chat-overlay Shorts for conversation stories (multiple voices),
modeled on text-thread story videos, and series-only production for everything.
They chose relationship drama/cheating/revenge for chats, 3/4-part arcs for chats
too, and alternating arc formats (narrated horror, then chat drama, and so on).

New: `story_format="series"` and `series_formats` in production config; chat arc
drafting (prompts/story_chat_series.md); per-sender voice planning and joined
multi-voice narration (tts_engine); the chat overlay renderer; a `format` column
on story_series (migrated in place, existing arcs read as narrated); drama upload
tags. Details are in docs/STORY_WORKFLOW.md and docs/PRODUCTION.md.

Not yet activated on the Windows PC: secrets/production.json there still says
`story_format="mixed"` until the user, or Hermes on the user's instruction, sets
`"story_format": "series"`. Publication mode is unchanged. (Superseded 2026-11-01: Kokoro voice pools now
cover same-gender chat contacts; see the Kokoro section above.)

Validation: 261 offline tests (19 new) and Ruff checks on changed files passed on
macOS with a temporary stand-in production config. An offline preview was rendered
with macOS `say` voices standing in for Fish and a synthetic background:
storage/reviews/chat_preview_20261031/ on the Mac. No live drafting, Fish/ElevenLabs
generation, footage research or upload was run. The first real chat arc
(Hermes drafting, Fish voices, creator footage) has not been reviewed yet.

## Gameplay detail fix — 2026-10-29

The user reported soft gameplay in the released "The Hatch Behind My Bed" and
requested a fix only for new videos, preserving everything already made.
Inspection found landscape 1080p cropped to roughly 608x1080 then enlarged to
1080x1920; the importer also reduced the available 4K original to landscape
1080p before cropping. YouTube initially chose Auto (360p) in the inspection
session, but 1080p processing was complete and playable.

New creator imports now probe the actual original, require native detail for a
1080x1920 crop, crop before Lanczos downscaling, and prepare portrait H.264 at
CRF 18. A new `_vertical_v1` filename suffix preserves existing cache files.
Cache/backup selection skips footage requiring enlargement; 1080p/1440p
landscape sources no longer qualify for new automatic work. Measured source
and crop dimensions are recorded alongside the preparation policy. Rights,
nonoverlap, allowances, captions, final 30fps and publication mode are retained.
See docs/FOOTAGE_RESEARCH.md for the new admission policy. Existing finished
videos and their schedules must remain unchanged; this policy is not a reason
to retire or regenerate them. Inspection evidence is retained under
storage/reviews/gameplay_resolution_20261029/.

Validation: 232 offline tests, Ruff lint/format and dependency checks passed.
A five-second preview from the actual local 4K original passed full decode at
1080x1920/30fps with cached Fish narration and synchronized yellow highlights.
All 93 baseline file hashes (existing outputs, source media/provenance and
production settings) and all rows in the five checked queue/usage tables were
unchanged; SQLite quick_check passed. No live generation, research, upload or
Telegram delivery was invoked. The installed task reads the updated source on
its next run; publication settings were preserved.

## User decisions

- Keep Windows on the Ryzen 5 4600G / integrated graphics / 16 GB PC.
- Use existing free allowances only. No purchases, upgrades or paid fallbacks.
- Narration is local Kokoro-82M only (2026-11-01); keep the accepted synchronized
  captions with the moving yellow word highlight. No paid upgrade/fallback is authorized.
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
- Hermes drafting uses the existing openai-codex login: gpt-6.1-sol (medium)
  writes and gpt-6.1-terra (high) scores each arc (see docs/STORY_WORKFLOW.md). Telegram
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

- Review the first full Kokoro-narrated production render before relying on it
  unattended; the voice was only checked on short samples.
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

Latest offline validation (2026-10-29): 232 tests, Ruff lint/format checks and pip
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

## Cleaner public descriptions — 2026-10-29

The user requested removing the verbose footage License/Changes lines and the
sentence explaining that credit is appreciated but optional, from future uploads
and already scheduled videos. youtube_uploader now filters those public lines
for creator-permission sources explicitly marked credit_required=false. Simple
gameplay/creator/source credits remain. Full local sidecars, permission evidence,
required credits and other license attribution are retained.

The current OAuth grant includes youtube.force-ssl as well as youtube.upload;
the earlier upload-only read limitation is superseded. All six upcoming scheduled
videos were updated through snippet-only API requests and read back successfully:
PthZtrjj27o, hb-mZ1BHL5M, rn9GJJDPqhw, jmDf6PBmBvU, Ce_KINyh7g0 and 4rnclBFY4kk.
Titles, tags, categories, default text language, publication status and exact
publishAt values were verified unchanged. The already released orieX-wfe0s was
outside this scheduled-video cleanup. Backups, accepted update responses and
readback verification are in ignored deployment/description_cleanup_20261029/.
No generation, rendering, upload, scheduling or Telegram delivery was performed.

Validation: 224 offline tests passed, including old/new sidecar filtering,
unchanged local provenance and preserved required/unknown-license attribution.

## Mixed standalone and serial stories — 2026-10-29

The user requested longer horror stories across 3–4 Shorts, with cliffhangers
encouraging viewers to find the continuation, and selected a mix with standalones.
secrets/production.json now has story_format=mixed, series_standalones_between=3,
series_parts=[3,4] and series_min_lead_hours=4. Public scheduling, private-upload
mode, Telegram, voice files, daily slots, allowance guards and the minimum reserve
were preserved. Activation waited for the runner lock, used an atomic config
replacement, and checked SQLite integrity. Its receipt and prior config are in
ignored deployment/; a verified pre-series database backup is in deployment/backups/.
The fresh local reserve at activation contained six future scheduled videos.
Existing scripts, outputs and accepted schedules were not replaced by this feature.

stories/series_story.py drafts a complete arc and continuity bible in one call,
then edits the full arc in a second call, with the existing bounded JSON repairs
and no paid fallback. Every nonfinal episode ends on a concrete cliffhanger;
the next answers it, and the final episode resolves the planted clue and central
danger. Each part keeps the existing word/duration maximum and has no minimum.
One explicit narrator/gender/provider is retained through the complete arc.
Bundles are saved atomically under storage/stories/series/<id>/ with a manifest
and per-part drafts. Restart reuses the bundle instead of paying for new drafting.

automation/series_queue.py adds story_series and series_episodes tables while
retaining all render/source claims and history. Mixed production binds only
untouched queued jobs to consecutive slots; prepared/scheduled jobs stay intact.
It renders at most one part per configured pass. Every part must be rendered,
validated and voice-consistent before any part can be approved for publication.
The complete prepared arc uploads in order, so the scheduled count may temporarily
exceed four; further generation then stops. Low reserves or an imminent existing
release prioritize standalone preparation. Failed, needs_attention and uncertain
members block the arc. A lost upload response can still leave a partial remote
schedule, requiring explicit inspection/reconciliation; later parts are not skipped.

Series titles are searchable as Part N/3 or N/4 with one common title. The caption
renderer shows a part badge and a continuation cue over the final two seconds,
including the existing silent tail, without stretching speech or adding padding.
The final part has no next-part cue. Caption wording/yellow highlighting, source
credits and selected voices are retained. Descriptions and Telegram notices include
part information without claiming the next part is already public.
Queue status/show expose membership; bulk dry runs preserve state and use no fake IDs.

Validation: all 232 current offline tests passed, including serial continuity,
restart reuse, per-pass budgets, ordered/uncertain uploads, reserve prioritization,
voice consistency, metadata/caption labels and unchanged standalone behavior.
Ruff lint/format and the new CLI help checks passed. An 11.3-second cached-Fish
caption preview passed full decode, 1080x1920/audio checks and sampled-frame review:
storage/output/series_caption_preview.mp4; frames in storage/reviews/serial_story_format/.
This is a label/caption preview, not a newly generated serial story. No live model,
TTS, source research, upload or Telegram delivery was invoked for this feature's
tests or activation. The existing worker will prepare new arcs when the reserve
needs replenishment. The source ZIP predates these latest changes; rebuild it with
build_transfer_package.py before transferring source.
