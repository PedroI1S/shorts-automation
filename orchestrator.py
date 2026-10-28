"""Durable Shorts production queue: topic -> draft -> render -> human review.

Never uploads. `approved` is the hand-off point for a future, idempotent uploader.
Only one runner works at a time (OS file lock, released automatically if the
process dies). Every job stops after MAX_ATTEMPTS failures in total, which
bounds subscription/TTS usage per topic.

Stages:
  queued -> drafting -> drafted -> rendering -> rendered (awaiting review)
  rendered -> approved | rejected
  any failure -> retried, or `failed` after MAX_ATTEMPTS
  interrupted render still holding its reservation -> needs_attention
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from config import STORAGE_DIR, SPEECH_WORDS_PER_SECOND
from draft_story import validate_story
from usage_store import DB_PATH, UsageStore, AlreadyUsed

LOCK_PATH = STORAGE_DIR / 'orchestrator.lock'
MAX_ATTEMPTS = 3
STAGES = ('queued', 'drafting', 'drafted', 'rendering', 'rendered',
          'approved', 'rejected', 'failed', 'needs_attention')
_FIELDS = {'attempts', 'story_path', 'render_job', 'output', 'error', 'review_note'}


class RunnerBusy(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _summary(error):
    return f'{type(error).__name__}: {str(error)[:300]}'


def _read_story(path):
    return validate_story(json.loads(Path(path).read_text(encoding='utf-8')))


class JobQueue:
    def __init__(self, path=None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    id TEXT PRIMARY KEY, topic TEXT NOT NULL, tts_provider TEXT NOT NULL,
                    gameplay_query TEXT, background_file TEXT, stage TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, story_path TEXT, render_job TEXT,
                    output TEXT, error TEXT, review_note TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS queue_jobs_stage ON queue_jobs(stage, created_at);
                CREATE TABLE IF NOT EXISTS queue_events (
                    job_id TEXT NOT NULL REFERENCES queue_jobs(id), at TEXT NOT NULL,
                    stage TEXT NOT NULL, detail TEXT);
                CREATE INDEX IF NOT EXISTS queue_events_job ON queue_events(job_id);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _event(db, job, stage, detail=None):
        db.execute('INSERT INTO queue_events VALUES (?,?,?,?)', (job, _now(), stage, detail))

    # ---- queries -------------------------------------------------------
    def get(self, ref):
        """Fetch by full id or a unique prefix (handy from Telegram)."""
        ref = (ref or '').strip().lower()
        if len(ref) < 4:
            raise ValueError('Use at least 4 characters of the job id.')
        with self.connect() as db:
            rows = db.execute('SELECT * FROM queue_jobs WHERE id LIKE ?', (ref + '%',)).fetchall()
        if len(rows) != 1:
            raise ValueError(f'{"No" if not rows else "Ambiguous"} job matches {ref!r}.')
        return rows[0]

    def list(self, stage=None):
        with self.connect() as db:
            if stage:
                return db.execute('SELECT * FROM queue_jobs WHERE stage=? ORDER BY created_at, rowid', (stage,)).fetchall()
            return db.execute('SELECT * FROM queue_jobs ORDER BY created_at, rowid').fetchall()

    def events(self, job):
        with self.connect() as db:
            return db.execute('SELECT * FROM queue_events WHERE job_id=? ORDER BY rowid', (job,)).fetchall()

    # ---- transitions ---------------------------------------------------
    def enqueue(self, topic, tts_provider='fish', gameplay_query=None, background_file=None):
        topic = ' '.join((topic or '').split())
        if not 1 <= len(topic) <= 1000:
            raise ValueError('Topic must contain 1 to 1,000 characters.')
        if tts_provider not in SPEECH_WORDS_PER_SECOND:
            raise ValueError(f'Unknown speech provider: {tts_provider}')
        if background_file:
            background_file = str(Path(background_file).resolve(strict=True))
        job, now = uuid4().hex, _now()
        with self.connect() as db:
            db.execute('INSERT INTO queue_jobs (id, topic, tts_provider, gameplay_query, background_file,'
                       ' stage, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)',
                       (job, topic, tts_provider, gameplay_query, background_file, 'queued', now, now))
            self._event(db, job, 'queued', 'enqueued')
        return job

    def move(self, job, expected, stage, detail=None, **fields):
        """Conditional transition: fails loudly if another actor already moved the job."""
        assert stage in STAGES and set(fields) <= _FIELDS
        sets = ', '.join(['stage=?', 'updated_at=?'] + [f'{k}=?' for k in fields])
        marks = ','.join('?' * len(expected))
        with self.connect() as db:
            cursor = db.execute(f'UPDATE queue_jobs SET {sets} WHERE id=? AND stage IN ({marks})',
                                (stage, _now(), *fields.values(), job, *expected))
            if cursor.rowcount != 1:
                raise ValueError(f'Job {job[:8]} is not in stage {"/".join(expected)}.')
            self._event(db, job, stage, detail)
        return self.get(job)

    def claim_next(self):
        """Atomically take the oldest actionable job and mark it in progress."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id, stage FROM queue_jobs WHERE stage IN ('queued','drafted') "
                             "ORDER BY created_at, rowid LIMIT 1").fetchone()
            if row is None:
                return None
            stage = 'drafting' if row['stage'] == 'queued' else 'rendering'
            db.execute('UPDATE queue_jobs SET stage=?, updated_at=? WHERE id=?', (stage, _now(), row['id']))
            self._event(db, row['id'], stage, 'claimed by runner')
        return self.get(row['id'])

    def fail_attempt(self, job, retry_stage, error, clear_story=False):
        attempts = job['attempts'] + 1
        stage = retry_stage if attempts < MAX_ATTEMPTS else 'failed'
        fields = {'attempts': attempts, 'error': _summary(error)}
        if clear_story:
            fields['story_path'] = None
        detail = f'attempt {attempts}/{MAX_ATTEMPTS} failed: {_summary(error)}'
        return self.move(job['id'], (job['stage'],), stage, detail, **fields)

    def review(self, ref, decision, note=None):
        if decision not in ('approved', 'rejected'):
            raise ValueError('Decision must be approved or rejected.')
        job = self.get(ref)
        return self.move(job['id'], ('rendered',), decision, note or 'reviewed', review_note=note)

    def retry(self, ref, usage):
        """Manually requeue a failed or needs_attention job with a fresh attempt budget."""
        job = self.get(ref)
        if job['stage'] not in ('failed', 'needs_attention'):
            raise ValueError('Only failed or needs_attention jobs can be retried.')
        stage, story_path = 'queued', None
        if job['story_path']:
            try:
                story = _read_story(job['story_path'])
            except (OSError, ValueError):
                story = None
            owner = usage.story_owner(story['script']) if story else None
            if owner and owner[1] == 'reserved':
                raise ValueError(f'Render {owner[0]} still holds this story. Inspect it, then run: '
                                 f'usage_store.py --release-reservation {owner[0]}')
            if story and not owner:
                stage, story_path = 'drafted', job['story_path']
        return self.move(job['id'], (job['stage'],), stage, 'manual retry',
                         attempts=0, error=None, story_path=story_path)

    def recover_interrupted(self, usage):
        """Resolve jobs left in progress by a runner that died. Call only while holding the lock."""
        recovered = []
        for job in self.list('drafting'):
            recovered.append(self.move(job['id'], ('drafting',), 'queued',
                                       'runner stopped during drafting; will redraft'))
        for job in self.list('rendering'):
            try:
                owner = usage.story_owner(_read_story(job['story_path'])['script'])
            except (OSError, ValueError, TypeError):
                owner = None
            if owner is None:
                job = self.move(job['id'], ('rendering',), 'drafted',
                                'render interrupted with no held reservation; will retry')
            elif owner[1] == 'rendered' and owner[2] and Path(owner[2]).is_file():
                job = self.move(job['id'], ('rendering',), 'rendered',
                                'render had finished before the runner stopped',
                                output=owner[2], render_job=owner[0], error=None)
            else:
                problem = (f'Render {owner[0]} was interrupted (status {owner[1]}, output '
                           f'{owner[2] or "not planned"}). Inspect the output. If none exists, run '
                           f'usage_store.py --release-reservation {owner[0]}, then orchestrator.py retry {job["id"][:8]}.')
                job = self.move(job['id'], ('rendering',), 'needs_attention', problem,
                                render_job=owner[0], error=problem)
            recovered.append(job)
        return recovered


@contextmanager
def runner_lock(path=LOCK_PATH):
    """Non-blocking exclusive lock; the OS releases it if the process crashes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, 'a+')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RunnerBusy('Another orchestrator run is active.') from None
    try:
        yield
    finally:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


# ---- runner --------------------------------------------------------------
def _draft(queue, job, drafter):
    try:
        path = drafter(job['topic'])
        _read_story(path)  # Never advance an unreadable or out-of-range draft.
    except Exception as error:
        return queue.fail_attempt(job, 'queued', error)
    return queue.move(job['id'], ('drafting',), 'drafted', f'story saved: {Path(path).name}',
                      story_path=str(path), error=None)


def _render(queue, job, renderer, usage):
    from pipeline import NarrationTooLong
    try:
        story = _read_story(job['story_path'])
    except (OSError, ValueError, TypeError) as error:
        return queue.fail_attempt(job, 'queued', error, clear_story=True)
    if usage.story_owner(story['script']):
        # Checked before any TTS call: an identical story would be blocked anyway.
        return queue.fail_attempt(job, 'queued', AlreadyUsed('Draft duplicates an existing story.'),
                                  clear_story=True)
    background = job['background_file']
    try:
        output = Path(renderer(story_file=Path(job['story_path']), tts_provider=job['tts_provider'],
                               gameplay_query=job['gameplay_query'],
                               background_file=Path(background) if background else None))
    except NarrationTooLong as error:
        return queue.fail_attempt(job, 'queued', error, clear_story=True)
    except Exception as error:
        return queue.fail_attempt(job, 'drafted', error)
    sidecar = output.with_suffix('.metadata.json')
    render_job = json.loads(sidecar.read_text(encoding='utf-8')).get('job_id') if sidecar.is_file() else None
    return queue.move(job['id'], ('rendering',), 'rendered', 'awaiting review',
                      output=str(output), render_job=render_job, error=None)


def process_one(queue, usage, drafter, renderer):
    """Advance the oldest actionable job as far as it can go. Returns its final row or None."""
    job = queue.claim_next()
    if job is None:
        return None
    if job['stage'] == 'drafting':
        job = _draft(queue, job, drafter)
        if job['stage'] != 'drafted':
            return job
        job = queue.move(job['id'], ('drafted',), 'rendering', 'continuing to render')
    return _render(queue, job, renderer, usage)


def run(max_jobs=1, queue=None, usage=None, drafter=None, renderer=None, lock_path=LOCK_PATH):
    queue, usage = queue or JobQueue(), usage or UsageStore()
    if drafter is None:
        from draft_story import draft as drafter
    if renderer is None:
        from pipeline import run_pipeline as renderer
    with runner_lock(lock_path):
        usage.import_outputs()
        recovered = queue.recover_interrupted(usage)
        processed = []
        while len(processed) < max_jobs:
            job = process_one(queue, usage, drafter, renderer)
            if job is None:
                break
            processed.append(job)
    return recovered, processed


# ---- CLI -----------------------------------------------------------------
def _line(job):
    note = job['error'] or job['review_note'] or ''
    return (f"{job['id'][:8]}  {job['stage']:<15} {job['attempts']}/{MAX_ATTEMPTS}  "
            f"{job['tts_provider']:<10} {job['topic'][:40]:<40}  {note[:70]}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('enqueue', help='Add topics to the queue.')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--topic')
    group.add_argument('--topics-file', type=Path, help='UTF-8 text file, one premise per line.')
    p.add_argument('--provider', choices=sorted(SPEECH_WORDS_PER_SECOND), default='fish')
    p.add_argument('--gameplay', help='Commons search query for background footage.')
    p.add_argument('--background-file', type=Path, help='Owned/licensed local footage.')
    p = sub.add_parser('run', help='Draft and render queued jobs, then stop at review.')
    p.add_argument('--max-jobs', type=int, default=1)
    p = sub.add_parser('status', help='List jobs.')
    p.add_argument('--stage', choices=STAGES)
    p = sub.add_parser('show', help='Job details and history.')
    p.add_argument('job')
    for name in ('approve', 'reject'):
        p = sub.add_parser(name, help=f'{name.title()} a rendered video.')
        p.add_argument('job')
        p.add_argument('--note')
    p = sub.add_parser('retry', help='Requeue a failed or needs_attention job.')
    p.add_argument('job')
    args = parser.parse_args(argv)

    queue = JobQueue()
    try:
        if args.command == 'enqueue':
            topics = ([args.topic] if args.topic else
                      [t for t in args.topics_file.read_text(encoding='utf-8').splitlines() if t.strip()])
            for topic in topics:
                print('queued', queue.enqueue(topic, args.provider, args.gameplay, args.background_file)[:8], topic[:60])
        elif args.command == 'run':
            if args.max_jobs < 1:
                parser.error('--max-jobs must be at least 1.')
            try:
                recovered, processed = run(args.max_jobs, queue)
            except RunnerBusy as error:
                print(error)
                return 0
            for job in recovered:
                print('recovered', _line(job))
            for job in processed:
                print('processed', _line(job))
            if not processed:
                print('Nothing to do.')
            return 1 if any(j['stage'] in ('failed', 'needs_attention') for j in recovered + processed) else 0
        elif args.command == 'status':
            for job in queue.list(args.stage):
                print(_line(job))
        elif args.command == 'show':
            job = queue.get(args.job)
            for key in job.keys():
                print(f'{key:>15}: {job[key]}')
            print('\nHistory:')
            for event in queue.events(job['id']):
                print(f"  {event['at']}  {event['stage']:<15} {event['detail'] or ''}")
        elif args.command in ('approve', 'reject'):
            decision = {'approve': 'approved', 'reject': 'rejected'}[args.command]
            print(_line(queue.review(args.job, decision, args.note)))
        elif args.command == 'retry':
            print(_line(queue.retry(args.job, UsageStore())))
    except ValueError as error:
        print('Error:', error)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
