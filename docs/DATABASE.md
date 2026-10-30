# Render usage database

SQLite lives at storage/usage.sqlite3, outside the transfer ZIP. Preserve it
privately when moving PCs; deleting media must not silently release usage history.

## Claims and source segments

A normalized story fingerprint is reserved before TTS. Supplied creator footage
is also admitted before TTS, so a duplicate/overlapping source cannot spend voice
allowance before it is rejected. Ordinary render failure releases the story and
source claims; completed work keeps them.

Schema 2 adds source_segments alongside jobs and claims. Each interval uses
integer milliseconds and half-open bounds: [5s,65s) and [65s,125s) are adjacent;
[64.999s,124.999s) overlaps and is rejected. SQLite BEGIN IMMEDIATE serializes the
final admission across processes. Allocation is a preview; reserve_source is the
atomic decision. Copied normalized-file hashes remain protected too.

Segment-aware creator metadata uses segment_policy=nonoverlapping-v1, a measured
source duration, stable video/download identities, start time and duration. One
long recording can supply multiple different Shorts without repeating a time
range. With a 5-second lead-in and 60-second windows, the verified 409.7-second
recording provides six full windows. Exhaustion returns no slot instead of looping
or reusing an interval. New discovery excludes exhausted video IDs.

The importer reuses valid unused cache first, then known creator records, then
AGY discovery. Every new import rechecks current creator permission and refreshes
the public download link. Cached legacy creator clips with explicitly recorded,
valid bounds can be upgraded to segment metadata. Existing whole-recording claims
are never silently cleared: they conservatively block segment reuse. Conversely,
a whole-source reservation cannot cover an existing used/reserved segment.

This tracks exact source/time/hash identity, not perceptual similarity or copied
stories with different wording. Different recording mirrors cannot be reliably
recognized without shared identity evidence or matching prepared hashes.

## Automatic source-media cleanup limitation

Automatic deletion of consumed source media is **not implemented**. A rendered
segment claim records use of a time interval, not ownership of a particular
cache file, and a reserved interval is not completed use. The production runner
lock does not cover standalone importer, cache-selection, or pipeline invocations;
selection and extraction can therefore race with a file deletion or replacement.
Do not infer safe deletion from exhaustion or from a hash claim alone. In
particular, retain user-provided originals, source sidecars, output files, rights
records, and usage claims. A safe implementation needs a shared cross-process
protocol covering all selection, publication, reservation, rendering and cleanup
paths, plus a migration/restart plan for already-running processes. Until then,
leave media in place and manage disk capacity manually after stopping all writers
and inspecting the exact files and reservations.

## Completion, crash and retry

After FFmpeg succeeds, the render job becomes rendered before sidecar writing.
A normal failure releases its source_segments and claims rows. A hard process
termination leaves reserved rows until explicit recovery, preventing accidental
reuse. A completed output retains its interval even after database reopen or
failed cleanup. Historical metadata imports also restore segment reservations.

List/import records:

```powershell
.\.venv\Scripts\python.exe -m shorts_automation.state.usage_store
```

For a stopped reserved job with no output, inspect it and explicitly release:

```powershell
.\.venv\Scripts\python.exe -m shorts_automation.state.usage_store --release-reservation JOB_ID
```

Never release running work. Existing output or a non-reserved status is refused.
Inspect and reconcile instead of deleting the database or blindly expiring rows.

A verified backup was saved under deployment/backups/ before the schema-2
migration. These private backups are excluded from source packages. Upload
reservations and public scheduling are separate queue concerns; see ORCHESTRATOR.md.
