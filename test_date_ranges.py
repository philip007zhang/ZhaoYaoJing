import unittest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from date_ranges import resolve_date_range, range_limits, subset_export


class DateRangeTests(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo('Australia/Sydney')
        self.now = datetime(2026, 11, 10, 12, tzinfo=self.tz)

    def test_arbitrary_weekdays_and_inclusive_end(self):
        start, end = resolve_date_range('2026-10-20', '2026-11-06', self.now)
        self.assertEqual(start.date().isoformat(), '2026-10-20')
        self.assertEqual(end.date().isoformat(), '2026-11-07')
        self.assertLess(datetime(2026, 11, 6, 23, 59, 59, tzinfo=self.tz), end)

    def test_single_day(self):
        start, end = resolve_date_range('2026-11-09', '2026-11-09', self.now)
        self.assertEqual(end - start, timedelta(days=1))

    def test_default_is_last_completed_week(self):
        start, end = resolve_date_range(None, None, self.now)
        self.assertEqual(start.date().isoformat(), '2026-10-31')
        self.assertEqual(end.date().isoformat(), '2026-11-07')

    def test_start_only_clips_to_today(self):
        start, end = resolve_date_range('2026-11-07', None, self.now)
        self.assertEqual(end.date().isoformat(), '2026-11-11')

    def test_30_calendar_days_including_today(self):
        lower, today = range_limits(self.now)
        self.assertEqual(lower.date().isoformat(), '2026-10-12')
        start, end = resolve_date_range('2026-10-12', '2026-11-10', self.now)
        self.assertEqual((end - start).days, 30)
        for first, last in [('2026-10-11', '2026-11-01'), ('2026-11-01', '2026-11-11'), ('2026-11-10', '2026-11-09')]:
            with self.subTest(first=first, last=last), self.assertRaises(ValueError):
                resolve_date_range(first, last, self.now)

    def test_calendar_range_preserves_dst(self):
        start, end = resolve_date_range('2026-10-03', '2026-10-09', datetime(2026, 10, 10, tzinfo=self.tz))
        self.assertEqual((end.timestamp() - start.timestamp()) / 3600, 167)

    def test_subset_filters_existing_export_without_overwriting(self):
        from history_store import write_outputs
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp) / 'week'
            rows = [dict(group='示例群', sender='成员', attr='friend', type='text', content='示例',
                         time=f'2026-11-0{day}T12:00:00+11:00') for day in (1, 5)]
            start, end = resolve_date_range('2026-10-31', '2026-11-06', self.now)
            write_outputs(root, rows, '示例群', start, end, 'test', {'boundary_reached': True})
            subset = subset_export(root, datetime(2026, 11, 5, tzinfo=self.tz), datetime(2026, 11, 6, tzinfo=self.tz))
            self.assertEqual(len(json.loads((subset / 'messages.json').read_text('utf-8'))), 1)
            self.assertEqual(len(json.loads((root / 'messages.json').read_text('utf-8'))), 2)
            with self.assertRaisesRegex(ValueError, '超出'):
                subset_export(root, datetime(2026, 10, 20, tzinfo=self.tz), end)


if __name__ == '__main__':
    unittest.main()
