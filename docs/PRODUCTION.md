# Automatic production

The worker is installed on this Windows PC. The user explicitly enabled public
scheduled publishing and Telegram notifications on 2026-10-29. The current source provider
is creator_downloads, targeting Minecraft parkour with creator-posted download
links. This guide describes current behavior, not the earlier Commons prototype.

## Controls and schedule

Settings live in ../secrets/production.json:

- enabled=true runs preparation; enabled=false pauses the entire worker.
- publish_enabled=true enables automatic public scheduling under the user's
  explicit activation. Set false only when the user requests a pause.
- private_upload_enabled=false selects public scheduling instead of private-only
  review uploads. Only one upload mode can be enabled at a time.
- private_upload_enabled=true permits private-only uploads at the Eastern slots,
  without a public publishAt. It cannot be combined with publish_enabled=true.
  With both upload switches false, three rendered videos fill the preparation
  backlog; the worker retains them and skips drafting, TTS and footage research.
- Daily targets are 07:00, 12:00 and 19:00 America/New_York. tzdata/zoneinfo follows
  New York daylight saving time independently of the PC clock.
- minimum_scheduled_videos=3 establishes the rolling minimum of confirmed future
  public releases. The worker refills toward four (minimum plus one) so a release
  leaves three while its replacement is prepared. It counts unique real YouTube
  IDs in scheduled state with scheduled_at strictly after the current instant,
  including explicitly scheduled manual jobs. Private previews, drafts, expired
  schedules and uncertain uploads do not fill this reserve.
- Planning looks 72 hours ahead and requires at least 45 minutes of lead time.
  Extra planned jobs provide alternatives when nearer slots fail; planning alone
  consumes no generation allowance. Full reserve skips generation and research.
- Videos have no minimum duration. Complete, clear stories can be short; positive
  finite audio, synchronized captions and the 58-second maximum still apply.
- Each pass advances at most one automatic job. There are three failures total
  per job, with retries on later passes rather than a tight loop.
- story_format=mixed adds serial arcs alongside standalones. With
  series_standalones_between=3, three standalone Shorts separate arcs;
  series_parts=[3,4] prefers alternating supported lengths. A new arc needs
  consecutive untouched queued slots and series_min_lead_hours=4 of preparation
  time. It also requires the minimum scheduled reserve and at least that much
  time until the next existing release; otherwise a standalone takes priority.
- A series is drafted/edited as a complete arc once, then rendered one part per
  pass. All parts must pass media, continuity and actual voice checks before
  Part 1 can be scheduled. Parts upload together in order; finishing one prepared
  arc may temporarily exceed the four-video reserve target. No further generation
  occurs while the reserve is full. Existing drafts and accepted schedules are
  not converted or replaced by the new format. Missing story_format keeps the
  earlier standalone behavior; setting standalone affects new assignments only.
- Already prepared automatic videos are validated/scheduled before new drafting.
  Each new render is scheduled immediately, and work stops when the reserve
  reaches four. Manual jobs are counted when scheduled, never autoapproved.

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe production.py status
.\.venv\Scripts\python.exe production.py plan
.\.venv\Scripts\python.exe orchestrator.py status
Get-ScheduledTaskInfo -TaskName ShortsAutomationProduction
```

## Proactive footage supply

For `creator_downloads` with `authorized_local_creator_source`, each enabled pass
that has room in its preparation backlog
counts unclaimed 60-second slots beginning at 5 seconds in that original. At two
or fewer, it looks for an available verified cached creator segment; otherwise it
runs the bounded existing evidence research (four candidates requested, at most
three imports) and prepares one 60-second backup. It does not download a whole
original. Research/import failures appear in production health as a problem and
are retried on a later pass. The disk and provider safety stops still run first.
The threshold is not a global inventory count and does not apply to other modes.

No exhausted-original deletion is implemented: user-owned originals, metadata,
outputs and claims remain untouched. The existing allocator does not coordinate
all manual file users through one lock, and absence of a usable slot can mean a
reservation, not completed consumption. Do not infer deletion safety from it.

## Installed Windows task

ShortsAutomationProduction invokes shorts_automation\automation\run_production_windows.ps1 every 30 minutes
and at the current user's sign-in, at normal privileges without a stored password.
It does not depend on this chat staying open. The latest inspected task result
was 0. The PC is configured not to sleep on AC power. Keep the user signed in;
locking the desktop is fine. Operation before sign-in is not provided.

shorts_automation\automation\install_production_windows.ps1 -Start installs/updates and starts the task. This
is an operational command, not an offline verification step. If registration is
refused, the installer can use a hidden Startup-folder VBS watchdog instead. That
fallback was not needed for the current production task. A real production reboot
test is still outstanding.

## Automatic pass

1. Acquire the same OS lock as the manual render runner; concurrent runs exit.
2. Stop when paused, free disk is below 5 GiB, or the verified Fish free window
   has expired. No paid service/model fallback exists.
3. Recover interrupted render state. Plan each future slot and queue job in one
   SQLite transaction, respecting existing manual publishing reservations.
4. Choose a previously unused setting/object/anomaly premise. Hermes creates
   the original English script. This avoids extra model calls for topic supply.
   The current premise pool has 1,440 combinations; exhaustion fails visibly.
5. Consume eligible unused creator stock first. Otherwise AGY plans public
   searches, the evidence broker reads real metadata/download pages, AGY ranks
   them, and the importer verifies the chosen creator's current description,
   permission text and publicly free video response. It imports a real 60-second
   segment before TTS. There is no fallback to dark Commons caves or paid files.
6. Narrate/render through the accepted providers and synchronized captions.
7. Validate story, provider, attribution, dimensions, audio and duration; decode
   the whole output. Failed validation requires attention.
8. When public publishing is explicitly enabled, approve validated automatic
   jobs and upload privately with their assigned future publishAt. YouTube later
   publishes them at that time. Manual jobs are never autoapproved by this worker.
   Complete series are validated/approved together; a failed or unknown upload
   stops later parts. Finishing an already started arc is allowed above the
   reserve target, without further drafting, TTS or footage research.
9. Atomically write health status and prune aged generated captions/production
   logs. Locked Windows temporary files are skipped without invalidating a pass.

Creator permission is stored with its actual URL/excerpt as Creator commercial
permission, not falsely labelled Creative Commons. The user verified and accepted
Fish's use for narrated Shorts; that decision is recorded in secrets/production.json.
See [footage research](FOOTAGE_RESEARCH.md) for source allocation.

## Health, storage and recovery

- storage/production_health.json is the machine-readable status.
- scheduled_buffer records minimum, target, future_scheduled, deficit,
  next_release and checked_at using a fresh clock at the end of the pass.
  Falling below three marks health needs_attention; a reserve of three triggers
  replenishment toward four. This cannot guarantee supply through PC/network
  outages, expired free offers or provider/source failures. It never bypasses
  media validation, reuploads an uncertain video or spends on a paid fallback.
- A newly missed slot is reported as a problem on that pass. On later passes,
  expired terminal failures count in historical_failed_jobs without failing health.
  Their queue records, errors and events remain intact. Future failed slots,
  needs_attention, uploading and upload_uncertain still require attention,
  including when the preparation backlog is full.
- storage/logs/production_*.log contains UTF-8 pass logs.
- SQLite job/slot history lives in storage/usage.sqlite3.
- The worker retains media, narration/timestamps, source evidence, credentials
  and database history. Only generated caption directories and production logs
  age out; the disk floor prevents unbounded work from filling the drive.
- When `telegram_notify_enabled` is true, each production pass sends a message
  for confirmed private uploads or uploads scheduled for public release. The
  scheduled message reports the intended release time, not confirmation that
  the video has become public; there is no publication-time monitor.
- The destination is the chat ID in ignored `secrets/telegram.local.json`; Hermes must
  have a working Telegram bot and that chat must be reachable. Failed messages
  remain in the SQLite outbox and retry on later worker passes without retrying
  the upload. Delivery is at-least-once: a crash or timeout after Telegram
  accepts a message can cause a duplicate. The worker must be running for retries.

Missed slots fail instead of becoming immediate public uploads; new future slots
are planned normally. Source/quota failures can prevent the target daily count.
Source identity is reserved and not silently reused under a different query/file.
Manual scheduling and dry-run previews also respect pending automatic slot
reservations. A production job can still schedule its own assigned slot.
Creator credit_text and full provenance remain in local credit sidecars and
metadata. For creator-permission footage explicitly marked credit_required=false,
public descriptions keep the gameplay, creator and source credit, while omitting
License/Changes lines and the optional-credit policy sentence. Required credits
and other license attribution remain intact, including for older renders.
An unknown upload outcome stays uploading/upload_uncertain and is never
reuploaded automatically. Inspect the channel, then use the explicit
[queue reconciliation commands](ORCHESTRATOR.md). Resumable uploads have bounded
HTTP requests, 8 MiB chunks and transport retries; live disconnect recovery remains
unverified.

## Verified and outstanding

The Windows worker completed three current-format Minecraft parkour Shorts with
Fish narration and synchronized captions. They use disjoint source intervals
5–65, 65–125 and 125–185 seconds and passed full decode/media checks and sampled-frame
review. The review manifest is storage/reviews/minecraft_batch_20261029_012324/.
A real Fish zero-duration caption edge case was previously fixed and recovered
using cached narration. The creator-download path completed live AGY research
and imported 1080p/60fps Minecraft parkour. A separate
caption preview was uploaded privately to verify YouTube access; its receipt is
ignored under deployment/. The user subsequently enabled public scheduling on
2026-10-29. The first activation preflight is recorded under
storage/reviews/public_rollout_20261029_180606/ and deployment/public-publishing-activation.json.

The worker retires older NodeCore/Minetest previews while retaining media/history
and creates one replacement per future slot in chronological order. Only current
Minecraft parkour segment output fills the new backlog. Four current-format
videos were uploaded with accepted public release schedules during the explicit
2026-10-29 activation; all four Telegram notices were delivered. Real production
reboot and interrupted-upload checks remain outstanding. Upload receipts confirm
the accepted publishAt values. The original upload-only OAuth grant returned
HTTP 403 for a subsequent videos.list processing/status read. The current grant
also includes youtube.force-ssl; on 2026-10-29, live snippet/status reads and
description-only updates succeeded for all six upcoming scheduled videos, with
their release times and publication status verified unchanged.
The worker stops after the verified Fish free window (currently
2026-11-30) unless that offer is explicitly reverified. Do not buy a plan or infer
commercial clearance from a successful render.
