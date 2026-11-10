"""Inclusive local calendar dates for the last 30 days, including today."""
from datetime import datetime, timedelta


def range_limits(now):
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=29), today


def resolve_date_range(start_value, end_value, now):
    lower, today = range_limits(now)
    def parse(value):
        return datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=now.tzinfo)
    if start_value:
        start = parse(start_value)
        end_day = parse(end_value) if end_value else min(start + timedelta(days=6), today)
    elif end_value:
        end_day = parse(end_value)
        start = max(lower, end_day - timedelta(days=6))
    else:
        end_exclusive = today - timedelta(days=(today.weekday() - 5) % 7)
        start, end_day = end_exclusive - timedelta(days=7), end_exclusive - timedelta(days=1)
    if start > end_day:
        raise ValueError('起始日期不能晚于截止日期')
    if start < lower or end_day > today or end_day < lower or start > today:
        raise ValueError(f'请选择过去30天内的日期（含今天）：{lower.date()} 至 {today.date()}')
    return start, end_day + timedelta(days=1)


def subset_export(folder, start, end):
    """Stream a narrower interval from an existing export, preserving originals."""
    import json
    from pathlib import Path
    from history_store import write_outputs
    folder = Path(folder).resolve()
    meta = json.loads((folder / 'coverage.json').read_text('utf-8'))
    original_start = datetime.fromisoformat(meta['start'])
    original_end = datetime.fromisoformat(meta['end_exclusive'])
    if start < original_start or end > original_end:
        raise ValueError('所选日期超出已有记录范围，请选择“采集并分析”获取缺少日期。')
    if start == original_start and end == original_end:
        return folder
    def records():
        with (folder / 'transcript.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                when = datetime.fromisoformat(row['effective_time'])
                if start <= when < end:
                    row['source_evidence_id'] = row.get('evidence_id')
                    row['source_time_basis'] = row.get('time_basis', 'explicit')
                    row['time'] = row['effective_time']
                    yield row
    out = folder.parent / ('range-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    history = dict(meta.get('history') or {}, parent_export=folder.name)
    write_outputs(out, records(), meta['group'], start, end, 'subset_existing_export', history)
    return out
