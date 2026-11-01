import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from shorts_automation.automation.orchestrator import JobQueue


class GenderBalanceTests(unittest.TestCase):
    def test_assignments_alternate_and_survive_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queue.db'
            queue = JobQueue(path)
            self.assertEqual(queue.assign_gender('story', 'a'), 'male')
            self.assertEqual(queue.assign_gender('series', 'b'), 'female')
            reopened = JobQueue(path)
            self.assertEqual(reopened.assign_gender('story', 'a'), 'male')
            self.assertEqual(reopened.assign_gender('series', 'b'), 'female')
            self.assertEqual(reopened.assign_gender('story', 'c'), 'male')

    def test_queue_passes_assignment_to_drafter_and_reuses_on_retry(self):
        from unittest.mock import Mock
        from shorts_automation.automation.orchestrator import _draft
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / 'queue.db')
            job = queue.enqueue('test')
            if isinstance(job, str):
                job = queue.get(job)
            drafter = Mock(side_effect=RuntimeError('offline'))
            _draft(queue, job, drafter)
            _draft(queue, job, drafter)
            self.assertEqual([call.kwargs['gender'] for call in drafter.call_args_list], ['male', 'male'])

    def test_series_queue_reserves_once_across_retries(self):
        from unittest.mock import Mock
        from shorts_automation.automation import series_queue
        with tempfile.TemporaryDirectory() as tmp:
            queue = JobQueue(Path(tmp) / 'queue.db')
            ids = [queue.enqueue(str(i)) for i in range(3)]
            identity = series_queue.link(queue, ids)
            drafter = Mock(side_effect=RuntimeError('offline'))
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'offline'):
                    series_queue.draft_job(queue, queue.get(ids[0]), drafter)
            self.assertEqual([c.kwargs['gender'] for c in drafter.call_args_list], ['male', 'male'])
            self.assertEqual(queue.assign_gender('series', identity), 'male')
            self.assertEqual(queue.assign_gender('story', 'next'), 'female')

    def test_series_rejects_model_ignoring_assignment(self):
        from unittest.mock import patch
        from shorts_automation.stories import series_story
        from tests.series_helpers import arc
        with tempfile.TemporaryDirectory() as tmp, patch.object(series_story, 'query_hermes', return_value=arc()):
            with self.assertRaisesRegex(ValueError, 'assigned'):
                series_story.draft_series('topic', identity='a'*32, directory=tmp, gender='male')

    def test_draft_rejects_model_ignoring_assignment(self):
        from unittest.mock import patch
        from shorts_automation.stories import draft_story
        story = {'title': 'A Very Strange Night', 'script': 'A strange night.',
                 'protagonist_gender': 'female', 'narrator_gender': 'female'}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(draft_story, 'STORAGE_DIR', Path(tmp)), \
             patch.object(draft_story, 'query_hermes', return_value=story):
            with self.assertRaisesRegex(ValueError, 'assigned'):
                draft_story.draft('a night', gender='male')

    def test_concurrent_assignments_are_balanced_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queue.db'
            JobQueue(path)
            def assign(i):
                return JobQueue(path).assign_gender('story', str(i // 2))
            with ThreadPoolExecutor(max_workers=8) as pool:
                genders = list(pool.map(assign, range(40)))
            self.assertEqual(genders.count('male'), 20)
            self.assertEqual(genders.count('female'), 20)
            self.assertTrue(all(genders[i] == genders[i+1] for i in range(0, 40, 2)))
