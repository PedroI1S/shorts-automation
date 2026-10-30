# Durable production queue

The queue in `storage/usage.sqlite3` takes manual topics through original drafting,
rendering, review, and explicit YouTube scheduling. Manual rendering uses
`shorts_automation\automation\run_orchestrator_windows.ps1`. The separate automatic worker in `production.py`
has an installed Windows task and can approve/publish its own validated jobs.
See PRODUCTION.md; public scheduling was explicitly enabled on 2026-10-29.

## Commands

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe orchestrator.py enqueue --topic "A night guard finds his name on tomorrow's visitor log"
.\.venv\Scripts\python.exe orchestrator.py enqueue --topics-file topics.txt --provider fish
powershell -NoProfile -ExecutionPolicy Bypass -File .\shorts_automation\automation\run_orchestrator_windows.ps1 -MaxJobs 1
.\.venv\Scripts\python.exe orchestrator.py status
.\.venv\Scripts\python.exe orchestrator.py show <id-prefix>
.\.venv\Scripts\python.exe orchestrator.py approve <id-prefix> --note "Reviewed output and permissions"
.\.venv\Scripts\python.exe orchestrator.py reject <id-prefix> --note "Weak ending"
.\.venv\Scripts\python.exe orchestrator.py schedule <id-prefix> --dry-run
.\.venv\Scripts\python.exe orchestrator.py schedule-approved --dry-run
.\.venv\Scripts\python.exe orchestrator.py retry <id-prefix>
.\.venv\Scripts\python.exe orchestrator.py replenish --target 3
```

IDs accept unique prefixes of at least four characters. `enqueue` defaults to
Fish and accepts `--gameplay` or `--background-file`. Drafting/rendering consume
allowances; the offline preview does not. `run` never uploads. Removing `--dry-run`
from a scheduling command uploads and schedules actual publication.

## Production and recovery

`queued -> drafting -> drafted -> rendering -> rendered -> approved | rejected`

- One render runner holds an OS lock, released on process death.
- Draft/render failures are bounded to three attempts per job, at most one per run.
  A failed topic cannot exhaust its retry budget within a single multi-job pass. Invalid/duplicate/
  overlong stories are redrafted; other rendering failures retain the saved draft.
- An interrupted draft returns to queued. An interrupted render is reconciled
  against the usage store: completed output becomes rendered; held reservations
  require manual inspection (`needs_attention`). `retry` refuses held reservations.
- See DATABASE.md for explicit source/story reservation release safeguards.

## YouTube scheduling

`approved -> uploading -> scheduled`

- Only approved jobs can be scheduled. Stored video IDs prevent reupload.
- A SQLite transaction reserves the job and slot before contacting YouTube.
  Simultaneous requests cannot upload that job twice or claim its reserved slot.
- Default times are 07:00, 12:00 and 19:00 America/New_York (US Eastern), for
  three Shorts per day. These wall-clock times follow daylight saving time. `tzdata` supplies
  timezone rules on Windows. Slots roll over to later days, skip booked instants,
  and have at least 45 minutes of lead time.
- Explicit `--publish-at` values require a timezone, a future instant, and an
  unreserved slot. Equivalent offset and Z representations compare as one instant.
- Pending automatic production slots are reserved too, before any video upload.
  Manual scheduling and bulk dry-run previews skip them; the assigned automatic
  job can use its own slot.
- Uploads use private status with `publishAt`. YouTube will later publish the video.
- Dry runs print a plan without storing a fake video ID, changing queue state,
  reserving a slot or adding history. Bulk previews use distinct proposed slots.
- An exception leaves `upload_uncertain`. A hard crash can leave `uploading`.
  Both block automatic retry and preserve the slot: the server may have accepted
  the video even if the local process did not receive its ID.

### Uncertain upload reconciliation

Stop the scheduling process first. Inspect YouTube Studio before changing state.
If the upload exists, verify its privacy/publishing settings and record its ID:

```powershell
.\.venv\Scripts\python.exe orchestrator.py reconcile-upload <id-prefix> --video-id <11-character-id> --note "Found video in Studio; checked schedule"
```

If channel inspection confirms that no upload exists:

```powershell
.\.venv\Scripts\python.exe orchestrator.py reconcile-upload <id-prefix> --not-uploaded --note "Checked Studio; no upload exists"
```

That explicit confirmation returns the job to approved and releases its slot.
Do not use it simply because a request timed out. Reconciliation records a human
inspection; it does not query YouTube or repair remote settings automatically.

## Validation and limitations

Scheduling regressions simulate success, lost responses, hard-crash reservations,
missing IDs, concurrent requests, slot conflicts and dry runs. Real resumable
upload persistence, automatic channel reconciliation and live failure/reboot
recovery remain unverified. This is duplicate prevention by durable reservation,
not a claim of exactly-once delivery across all clients or remote failures.

The standalone uploader and old batch manifests do not share these guarantees.
Automatic premise supply, bounded automatic approval, a production task, generated
temp/log retention and a local health report now exist in production.py. Optional
Telegram notifications use a durable upload outbox (see PRODUCTION.md). Scheduling does not open an
OAuth browser when credentials are missing; it fails with login instructions.
Explicit local setup is `python -m shorts_automation.publishing.youtube_uploader --authenticate`.

API references checked on 2026-10-28:
- https://developers.google.com/youtube/data/reference/rest/v3/videos#status.publishAt
- https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol
