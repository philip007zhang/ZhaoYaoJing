import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from weekly_chat import TEST_GROUP, analyze, week, write_outputs, ZoneInfo, collect_history, chronological, find_cached_week
from types import SimpleNamespace
from unittest.mock import patch


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo('Australia/Sydney')
        self.start, self.end = week(datetime(2026, 11, 7, 12, tzinfo=self.tz))

    def row(self, time, **extra):
        return dict(group=TEST_GROUP, time=time, attr='friend', type='text',
                    sender='成员', content='内容', **extra)

    def test_recent_completed_week(self):
        self.assertEqual(self.start.date().isoformat(), '2026-10-31')
        self.assertEqual(self.end.date().isoformat(), '2026-11-07')
        friday = week(datetime(2026, 11, 6, 23, tzinfo=self.tz))
        self.assertEqual(friday[1].date().isoformat(), '2026-10-31')

    def test_dst_uses_calendar_days(self):
        start, end = week(datetime(2026, 10, 10, 12, tzinfo=self.tz))
        self.assertEqual((end.timestamp() - start.timestamp()) / 3600, 167)

    def test_boundaries_unknown_and_repeated_messages(self):
        rows = [self.row(self.start.isoformat()), self.row(self.start.isoformat()),
                self.row(self.end.isoformat()), self.row(None)]
        kept, excluded, uncertain, activity = analyze(rows, TEST_GROUP, self.start, self.end)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(len(uncertain), 1)
        self.assertEqual(activity[0]['messages'], 2)
        self.assertNotEqual(kept[0]['evidence_id'], kept[1]['evidence_id'])

    def test_separator_and_group_filter(self):
        rows = [dict(group=TEST_GROUP, type='time', time=self.start.isoformat()),
                self.row(None), dict(self.row(self.start.isoformat()), group='另一个群')]
        kept, excluded, uncertain, _ = analyze(rows, TEST_GROUP, self.start, self.end)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]['time_basis'], 'preceding_separator')
        self.assertEqual(len(excluded), 1)
        self.assertFalse(uncertain)

    def test_outputs_never_claim_complete_or_overwrite(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            out = Path(tmp) / 'run'
            write_outputs(out, [self.row(self.start.isoformat())], TEST_GROUP,
                          self.start, self.end, 'test_fixture')
            self.assertEqual(json.loads((out / 'coverage.json').read_text('utf-8'))['coverage'], 'unverified')
            self.assertTrue((out / 'activity.csv').exists())
            with self.assertRaises(FileExistsError):
                write_outputs(out, [], TEST_GROUP, self.start, self.end, 'test_fixture')

    def history(self, pages):
        class Fake:
            def __init__(self):
                self.calls = []

            def ChatInfo(self):
                return {'chat_name': TEST_GROUP, 'chat_type': 'group'}

            def GetHistoryMessage(self, **kwargs):
                self.calls.append(kwargs)
                result = pages.pop(0)
                if isinstance(result, Exception):
                    raise result
                return [SimpleNamespace(**row) for row in result]
        return Fake()

    def test_history_crosses_start_and_preserves_duplicates(self):
        new = self.row('2026-11-02T12:00:00+11:00')
        old = self.row('2026-10-30T23:00:00+11:00')
        fake = self.history([[new, new], [old, new, new]])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            rows, state = collect_history(fake, TEST_GROUP, self.start, Path(tmp) / 'pages', batch=2)
            self.assertTrue(state['boundary_reached'])
            self.assertEqual(len(rows), 5)
            self.assertEqual([c['n'] for c in fake.calls], [2, 2])
            self.assertTrue(all(not c['goback'] for c in fake.calls))

    def test_stalled_history_does_not_claim_boundary(self):
        page = [self.row('2026-11-02T12:00:00+11:00')]
        fake = self.history([page, page, page, page])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            rows, state = collect_history(fake, TEST_GROUP, self.start, Path(tmp) / 'pages')
            self.assertFalse(state['boundary_reached'])
            self.assertEqual(state['stop_reason'], 'no_progress_boundary_unverified')

    def test_error_keeps_last_successful_page(self):
        page = [self.row('2026-11-02T12:00:00+11:00')]
        fake = self.history([page, RuntimeError('read failed')])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            rows, state = collect_history(fake, TEST_GROUP, self.start, Path(tmp) / 'pages')
            self.assertEqual(len(rows), 1)
            self.assertEqual(state['stop_reason'], 'error')
            self.assertTrue((Path(tmp) / 'pages' / 'state.json').exists())

    def test_mixed_time_blocks_do_not_abort(self):
        rows = []
        for minute in (20, 35, 25):
            rows.extend([dict(group=TEST_GROUP, type='time', time=f'2026-11-06T08:{minute}:00+11:00'),
                         self.row(None)])
        ordered = chronological(rows, self.tz)
        times = [r['time'] for r in ordered if r['type'] == 'time']
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(ordered), 6)

    def test_streaming_export_from_database(self):
        from history_store import HistoryStore
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            store = HistoryStore(Path(tmp) / 'history.sqlite3')
            store.add(1, [self.row('2026-11-06T10:00:00+11:00')])
            store.add(2, [self.row('2026-11-01T10:00:00+11:00')])
            out = Path(tmp) / 'report'
            meta = write_outputs(out, store, TEST_GROUP, self.start, self.end, 'test')
            self.assertEqual(meta['included'], 2)
            saved = json.loads((out / 'messages.json').read_text('utf-8'))
            self.assertLess(saved[0]['effective_time'], saved[1]['effective_time'])

    def test_timeout_retries_without_discarding_older_packages(self):
        page = [self.row('2026-11-02T12:00:00+11:00')]
        older = [self.row('2026-10-30T12:00:00+11:00')]
        fake = self.history([page, TimeoutError('loading'), older])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            rows, state = collect_history(fake, TEST_GROUP, self.start, Path(tmp) / 'pages')
            self.assertTrue(state['boundary_reached'])
            self.assertEqual(len(rows), 2)

    def cache_fixture(self, root, name='complete', complete=True):
        folder = root / name
        write_outputs(folder, [self.row(self.start.isoformat())], TEST_GROUP,
                      self.start, self.end, 'test', {'boundary_reached': complete})
        return folder

    def test_cache_matches_group_period_and_completed_export(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)
            complete = self.cache_fixture(root)
            self.cache_fixture(root, 'partial', False)
            self.assertEqual(find_cached_week([root], TEST_GROUP, self.start, self.end), complete.resolve())
            self.assertIsNone(find_cached_week([root], '其他群', self.start, self.end))
            self.assertIsNone(find_cached_week([root], TEST_GROUP, self.end, self.end))

    def test_cache_rejects_truncated_or_missing_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)
            folder = self.cache_fixture(root)
            (folder / 'transcript.jsonl').write_text('{broken', encoding='utf-8')
            self.assertIsNone(find_cached_week([root], TEST_GROUP, self.start, self.end))

    def test_cli_reuses_existing_data_and_only_runs_analysis(self):
        import weekly_chat
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = self.cache_fixture(Path(tmp))
            argv = ['weekly_chat.py', '--group', TEST_GROUP, '--start', '2026-10-31', '--analyze']
            with patch('sys.argv', argv), patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only'}), \
                    patch('weekly_chat.find_cached_week', return_value=folder), \
                    patch('weekly_chat.capture') as capture_mock, \
                    patch('gemini_analysis.run_analysis', return_value=folder / 'analysis') as analysis_mock:
                weekly_chat.main()
                capture_mock.assert_not_called()
                analysis_mock.assert_called_once_with(folder, 'gemini-4-argon')

    def test_force_collect_bypasses_cache(self):
        import weekly_chat
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            out = Path(tmp) / 'new'
            argv = ['weekly_chat.py', '--group', TEST_GROUP, '--start', '2026-10-31',
                    '--force-collect', '--out', str(out)]
            with patch('sys.argv', argv), patch('weekly_chat.find_cached_week') as cache_mock, \
                    patch('weekly_chat.capture', return_value=([], {'boundary_reached': True})) as capture_mock:
                weekly_chat.main()
                cache_mock.assert_not_called()
                capture_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
