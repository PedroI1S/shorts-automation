# Render usage database

SQLite lives at `storage/usage.sqlite3` (ignored with storage). No paid service,
server or extra Python dependency is needed. Keep this file when moving PCs;
the source-transfer ZIP excludes storage except its selected media, so transfer
the database privately/separately when moving operational history.

The render pipeline reserves a normalized story fingerprint before TTS. It then
reserves the selected background using its Commons page ID, download URL without
query parameters, known original/prepared hashes, and the file hash. A source
cannot be reused in a different query or under a renamed identical file. This is
exact identity tracking, not semantic story or perceptual video deduplication.

SQLite transactions and unique claim keys allow only one job to reserve a given
story/source. Candidate discovery and cache selection exclude reserved/used
sources. A final transactional claim protects against concurrent selection.
A competing job stops rather than silently reusing the clip. Used sources stay
blocked even if their video output is later deleted. Explicit local background
files are also subject to reservations.

After FFmpeg succeeds, the job becomes `rendered` before metadata writing.
Ordinary failures/interrupts release claims for retries and retain a failed-job
record. A killed process/power loss leaves a `reserved` job: no automatic expiry
can accidentally allow a duplicate render. The intended output path is recorded
before FFmpeg starts. Review any interrupted output before recovery.

List jobs and import historical `.metadata.json` outputs idempotently:

```powershell
.venv\Scripts\python.exe usage_store.py
```

Two prior gameplay renders were imported in this session. Missing-metadata
renders cannot be inferred automatically; one known old render's metadata was
backfilled from this session's verified source/story association.

For a STOPPED reservation with no output file, release its claims explicitly:

```powershell
.venv\Scripts\python.exe usage_store.py --release-reservation JOB_ID
```

Never release a running job. The command refuses jobs with an existing output
or a non-reserved status. Inspect partial/completed output and reconcile manually
instead of deleting the database or expiring reservations blindly.

Scope: render-time story/footage reuse prevention. A small pool can now exhaust;
the workflow must find another eligible source or stop. There is no reuse
override by default. Segment-level reuse of distinct parts of a long video is
not enabled: one rendered use consumes the entire source. No upload-idempotency,
publishing schedule or unattended-production claim is implied by this database.
