"""Durable render reservations. Crashed jobs stay reserved until explicitly released."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from config import STORAGE_DIR, OUTPUT_DIR

DB_PATH = STORAGE_DIR / 'usage.sqlite3'


class AlreadyUsed(RuntimeError):
    pass


def story_key(script):
    normalized = ' '.join(script.casefold().split())
    return 'story:' + hashlib.sha256(normalized.encode()).hexdigest()


def source_keys(metadata, path=None):
    keys = []
    if metadata.get('pageid'):
        keys.append('commons:' + str(metadata['pageid']))
    url = metadata.get('download_url') or metadata.get('source_url') or metadata.get('source')
    if url and str(url).startswith('https://'):
        parsed = urlsplit(url)
        keys.append('url:' + parsed.netloc.lower() + unquote(parsed.path).replace(' ', '_'))
    for field in ('original_sha256', 'sha256'):
        if metadata.get(field):
            keys.append('sha256:' + metadata[field])
    if path and Path(path).is_file():
        keys.append('sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest())
    return list(dict.fromkeys(keys))


class UsageStore:
    def __init__(self, path=None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, output TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS claims (
                    key TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id));
                CREATE INDEX IF NOT EXISTS claims_job ON claims(job_id);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def begin(self, script):
        job = uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, NULL, NULL)',
                       (job, 'reserved', datetime.now(timezone.utc).isoformat()))
            try:
                db.execute('INSERT INTO claims VALUES (?,?)', (story_key(script), job))
            except sqlite3.IntegrityError:
                raise AlreadyUsed('This story is already rendered or reserved.') from None
        return job

    def unavailable(self, keys):
        with self.connect() as db:
            return any(db.execute('SELECT 1 FROM claims WHERE key=?', (k,)).fetchone() for k in keys)

    def reserve_source(self, job, metadata, path=None):
        keys = source_keys(metadata, path)
        if not keys:
            raise ValueError('Cannot reserve footage without source identity.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone() != ('reserved',):
                raise ValueError('Job is not reservable.')
            for key in keys:
                owner = db.execute('SELECT job_id FROM claims WHERE key=?', (key,)).fetchone()
                if owner and owner[0] != job:
                    raise AlreadyUsed('This footage is already rendered or reserved.')
                db.execute('INSERT OR IGNORE INTO claims VALUES (?,?)', (key, job))

    def complete(self, job, output):
        with self.connect() as db:
            cursor = db.execute("UPDATE jobs SET status='rendered', output=? WHERE id=? AND status='reserved'",
                                (str(Path(output).resolve()), job))
            if cursor.rowcount != 1:
                raise ValueError('Cannot complete an inactive job.')

    def plan_output(self, job, output):
        with self.connect() as db:
            db.execute("UPDATE jobs SET output=? WHERE id=? AND status='reserved'",
                       (str(Path(output).resolve()), job))

    def release_reservation(self, job):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,output FROM jobs WHERE id=?', (job,)).fetchone()
            if not row or row[0] != 'reserved':
                raise ValueError('Only reserved jobs can be released.')
            if row[1] and Path(row[1]).exists():
                raise ValueError('An output exists. Inspect/reconcile it before releasing this job.')
            db.execute('DELETE FROM claims WHERE job_id=?', (job,))
            db.execute("UPDATE jobs SET status='failed', error='Reservation manually released' WHERE id=?", (job,))

    def fail(self, job):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone() == ('reserved',):
                db.execute('DELETE FROM claims WHERE job_id=?', (job,))
                db.execute("UPDATE jobs SET status='failed', error='Render interrupted or failed' WHERE id=?", (job,))

    def import_outputs(self, directory=OUTPUT_DIR):
        count = 0
        for sidecar in Path(directory).glob('*.metadata.json'):
            output = sidecar.with_name(sidecar.name.replace('.metadata.json', '.mp4'))
            if not output.is_file():
                continue
            d = json.loads(sidecar.read_text(encoding='utf-8'))
            keys = [story_key(d['story']['script']), *source_keys(d.get('background_source', {}))]
            job = 'import:' + hashlib.sha256(str(output.resolve()).encode()).hexdigest()
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM jobs WHERE id=? OR output=?', (job, str(output.resolve()))).fetchone():
                    continue
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,NULL)',
                           (job, 'rendered', datetime.now(timezone.utc).isoformat(), str(output.resolve())))
                for key in keys:
                    db.execute('INSERT OR IGNORE INTO claims VALUES (?,?)', (key, job))
                count += 1
        return count


@contextmanager
def render_job(script):
    store = UsageStore()
    store.import_outputs()
    job = store.begin(script)
    try:
        yield store, job
    finally:
        # A completed render keeps its claims even if writing the sidecar fails.
        store.fail(job)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-reservation', help='Only for a stopped job with no output; never release a running job.')
    args = parser.parse_args()
    store = UsageStore()
    print('Imported output records:', store.import_outputs())
    if args.release_reservation:
        store.release_reservation(args.release_reservation)
    with store.connect() as db:
        for row in db.execute('SELECT id,status,output FROM jobs ORDER BY created_at'):
            print(*row)
