import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from usage_store import UsageStore, AlreadyUsed, source_keys


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = UsageStore(self.root/'usage.sqlite3')

    def test_story_normalization_blocks_reuse(self):
        self.db.begin('A Story Here')
        with self.assertRaises(AlreadyUsed):
            self.db.begin(' a  story\nHERE ')

    def test_sources_are_unique_across_queries_and_jobs(self):
        a, b = self.db.begin('first'), self.db.begin('second')
        self.db.reserve_source(a, {'pageid': 7, 'query': 'one'})
        with self.assertRaises(AlreadyUsed):
            self.db.reserve_source(b, {'pageid': 7, 'query': 'other'})

    def test_fail_releases_but_completion_survives_reopen(self):
        a = self.db.begin('first')
        self.db.reserve_source(a, {'pageid': 7})
        self.db.fail(a)
        b = self.db.begin('first')
        self.db.reserve_source(b, {'pageid': 7})
        self.db.complete(b, self.root/'finished.mp4')
        self.db.fail(b)
        self.assertTrue(UsageStore(self.db.path).unavailable(['commons:7']))

    def test_simultaneous_reservations_have_one_winner(self):
        a, b = self.db.begin('first'), self.db.begin('second')
        def reserve(job):
            try:
                UsageStore(self.db.path).reserve_source(job, {'pageid': 8})
                return True
            except AlreadyUsed:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(reserve, [a, b])), [False, True])

    def test_import_is_idempotent_and_blocks_previous_work(self):
        (self.root/'old.mp4').write_bytes(b'video')
        (self.root/'old.metadata.json').write_text(json.dumps({
            'story': {'script': 'old narration'}, 'background_source': {'pageid': 4}}))
        self.assertEqual(self.db.import_outputs(self.root), 1)
        self.assertEqual(self.db.import_outputs(self.root), 0)
        self.assertTrue(self.db.unavailable(['commons:4']))
        with self.assertRaises(AlreadyUsed):
            self.db.begin('old narration')

    def test_changed_urls_and_copied_files_preserve_identity(self):
        a = source_keys({'download_url': 'https://upload.wikimedia.org/a.webm?x=1'})
        b = source_keys({'download_url': 'https://upload.wikimedia.org/a.webm?x=2'})
        self.assertEqual(a, b)
        p, q = self.root/'a.mp4', self.root/'renamed.mp4'
        p.write_bytes(b'same'); q.write_bytes(b'same')
        self.assertEqual(source_keys({}, p), source_keys({}, q))

    def test_crash_release_requires_missing_output(self):
        job = self.db.begin('crashed')
        output = self.root/'complete_or_partial.mp4'
        self.db.plan_output(job, output)
        output.write_bytes(b'existing output')
        with self.assertRaises(ValueError):
            self.db.release_reservation(job)
        other = self.db.begin('stopped before output')
        self.db.release_reservation(other)
        self.db.begin('stopped before output')
