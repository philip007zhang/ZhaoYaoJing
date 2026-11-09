"""Local WeChat weekly export and analysis preparation. No sending operations."""
import argparse
import csv
import importlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from console_output import configure_console

configure_console()

LOCAL_DEPS = Path(__file__).resolve().parent / '.deps'
if LOCAL_DEPS.is_dir():
    sys.path.insert(0, str(LOCAL_DEPS))

TEST_GROUP = '示例讨论群'


def week(now):
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end -= timedelta(days=(end.weekday() - 5) % 7)
    return end - timedelta(days=7), end


def parse_time(value, tz, reference=None):
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        reference = reference or datetime.now(tz)
        reference = reference.replace(tzinfo=tz) if reference.tzinfo is None else reference.astimezone(tz)
        midnight = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        # WeChat renders recent days as 今天/昨天/星期六 instead of dates.
        # Resolve once against the capture date, never against the target week.
        match = re.fullmatch(r'(?:(今天|昨天|前天|(?:星期|周|礼拜)[一二三四五六日天])\s*)?(?:(上午|下午|晚上|中午|凌晨|早上)\s*)?(?:(\d{1,2}):(\d{2})(?::(\d{2}))?)?', text)
        if match and any(match.groups()):
            label, period, hour, minute, second = match.groups()
            day = midnight
            if label in ('昨天', '前天'):
                day -= timedelta(days=1 if label == '昨天' else 2)
            elif label and label not in ('今天',):
                weekday = '一二三四五六日'.index(label[-1].replace('天', '日'))
                day -= timedelta(days=(midnight.weekday() - weekday) % 7)
            h = int(hour or 0)
            if period in ('下午', '晚上') and h < 12:
                h += 12
            elif period == '中午' and 1 <= h < 11:
                h += 12
            elif period in ('上午', '凌晨', '早上') and h == 12:
                h = 0
            try:
                return day.replace(hour=h, minute=int(minute or 0), second=int(second or 0))
            except ValueError:
                return None
        date_match = re.fullmatch(r'(?:(\d{4})[年/-])?(\d{1,2})[月/-](\d{1,2})日?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', text)
        if date_match:
            year, month, day, hour, minute, second = date_match.groups()
            try:
                resolved = datetime(int(year or reference.year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0), tzinfo=tz)
                if not year and resolved.date() > reference.date():
                    resolved = resolved.replace(year=resolved.year - 1)
                return resolved
            except ValueError:
                return None
        return None
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


def normalize_time_rows(rows, tz, reference):
    for row in rows:
        if row.get('type') != 'time':
            continue
        label = str(row.get('time_label') or row.get('content') or '').strip()
        # Prefer a visible relative label over an implicit library conversion.
        relative = bool(re.match(r'^(?:今天|昨天|前天|星期|周[一二三四五六日天]|礼拜)', label))
        value = label if relative else row.get('time') or label
        parsed = parse_time(value, tz, reference)
        if parsed is None and value != label:
            parsed = parse_time(label, tz, reference)
        if parsed:
            row['time_original'] = row.get('time')
            row['time_label'] = label or str(value)
            row['time_reference'] = reference.isoformat()
            row['time_precision'] = 'minute' if re.search(r'\d{1,2}:\d{2}', str(value)) else 'day'
            row['time'] = parsed.isoformat()
    return rows


def serialize_messages(messages, group):
    rows = []
    for msg in messages:
        row = {}
        for key in ('type', 'attr', 'sender', 'content', 'time', 'id',
                    'quote_content', 'quote_nickname', 'info', 'url', 'link'):
            try:
                value = getattr(msg, key, None)
            except (ValueError, TypeError):
                # Some client/library combinations cannot parse weekday labels.
                # Keep the visible time-message content for our own resolver.
                if key != 'time':
                    raise
                value = None
            if value is not None and not callable(value):
                row[key] = value
        row['group'] = group
        rows.append(row)
    return rows


def chronological(rows, tz):
    # Keep messages attached to their preceding separator. UI loading can repeat
    # overlapping blocks; a timestamp regression is not a reason to abort.
    blocks, block = [], []
    for row in rows:
        if row.get('type') == 'time' and block:
            blocks.append(block)
            block = []
        block.append(row)
    if block:
        blocks.append(block)
    def key(block):
        times = [parse_time(r.get('time'), tz) for r in block]
        return next((t.timestamp() for t in times if t), float('-inf'))
    return [row for block in sorted(blocks, key=key) for row in block]


def collect_history(wx, group, start, page_dir, batch=200, max_pages=100, timeout=60, download_media=False, reference=None):
    from history_store import HistoryStore
    page_dir.mkdir(parents=True, exist_ok=False)
    store = HistoryStore(page_dir / 'history.sqlite3')
    reference = reference or datetime.now(start.tzinfo)
    state = dict(boundary_reached=False, stop_reason='max_pages', pages=0,
                 strategy='fixed_batch_goback_false', goback_requested=False,
                 possible_overlap=True, unrecovered_timeout_pages=[], time_reference=reference.isoformat())
    previous = None
    repeats = 0
    timeouts = 0
    try:
        for page in range(1, max_pages + 1):
            info = wx.ChatInfo()
            if info.get('chat_name') != group or info.get('chat_type') != 'group':
                raise RuntimeError('采集期间聊天目标发生变化，停止读取。')
            with (page_dir / f'callback-{page:04d}.jsonl').open('w', encoding='utf-8') as journal:
                def checkpoint(message):
                    journal.write(json.dumps(normalize_time_rows(serialize_messages([message], group), start.tzinfo, reference)[0],
                                             ensure_ascii=False, default=str) + '\n')
                    journal.flush()
                try:
                    result = wx.GetHistoryMessage(n=batch, interval=0.3, speed=1,
                                                  goback=False, timeout=timeout, callback=checkpoint)
                    timeouts = 0
                except TimeoutError:
                    timeouts += 1
                    # goback=False may already have advanced the viewport.
                    # The callback journal is recovery evidence, not a complete
                    # returned package. Never certify a later export as complete
                    # while a timed-out interval has not been reconstructed.
                    state['unrecovered_timeout_pages'].append(page)
                    state.update(stop_reason='timeout_retry', consecutive_timeouts=timeouts)
                    (page_dir / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(f'第 {page} 包加载超时，保留回调日志，重试 {timeouts}/3', flush=True)
                    if timeouts >= 3:
                        state['stop_reason'] = 'repeated_timeout_boundary_unverified'
                        break
                    continue
            if not isinstance(result, list):
                raise RuntimeError('GetHistoryMessage 未返回消息列表')
            current = normalize_time_rows(serialize_messages(result, group), start.tzinfo, reference)
            # Persist the returned package before any optional processing.
            (page_dir / f'page-{page:04d}.json').write_text(
                json.dumps(current, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            if download_media:
                videos = 0
                for row in current:
                    if row.get('type') == 'video':
                        row['media_download_status'] = 'deferred_unbounded_wechat_menu_download'
                        videos += 1
                if videos:
                    print(f'本包含 {videos} 条视频：跳过可能无响应的微信菜单下载，保留消息并继续采集。', flush=True)
            (page_dir / f'page-{page:04d}.json').write_text(
                json.dumps(current, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            state['pages'] = page
            state['stop_reason'] = 'max_pages'
            if not current:
                state['stop_reason'] = 'empty_result'
                break
            current = chronological(current, start.tzinfo)
            fingerprint = [(r.get('type'), r.get('attr'), r.get('sender'),
                            r.get('content'), r.get('time')) for r in current]
            repeats = repeats + 1 if fingerprint == previous else 0
            previous = fingerprint
            # Entire identical consecutive snapshots add no new UI evidence.
            # Original packages remain on disk even when skipped in the index.
            if repeats == 0:
                store.add(page, current)
            times = [parse_time(r.get('time'), start.tzinfo) for r in current]
            times = [t for t in times if t is not None]
            print(f'历史包 {page}/{max_pages}：本次请求 {batch}，返回 {len(current)} 条，'
                  f'最早时间 {min(times).isoformat() if times else "未知"}', flush=True)
            if times and min(times) <= start:
                state['start_boundary_observed'] = True
                state['start_boundary_precision'] = 'day' if any(
                    r.get('time_precision') == 'day' and parse_time(r.get('time'), start.tzinfo) == start
                    for r in current) else 'minute'
                if state['unrecovered_timeout_pages']:
                    state.update(boundary_reached=False, stop_reason='crossed_start_with_unrecovered_timeout')
                else:
                    state.update(boundary_reached=True, stop_reason='crossed_start' if min(times) < start else 'reached_start')
                print(f'已到达起始日期 {start.date().isoformat()}，停止向前回溯。', flush=True)
                break
            if repeats >= 3:
                state['stop_reason'] = 'no_progress_boundary_unverified'
                break
            (page_dir / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            del current, result
    except KeyboardInterrupt:
        state['stop_reason'] = 'interrupted'
    except Exception as exc:
        state.update(stop_reason='error', error=f'{type(exc).__name__}: {exc}')
    finally:
        (page_dir / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return store, state


def capture(group, library, start, page_dir, batch, max_pages, timeout, download_media=False):
    try:
        module = importlib.import_module(library)
    except ImportError as exc:
        raise RuntimeError(f'当前 Python 未安装 {library}；请在已配置链接库的环境运行。') from exc
    wx = module.WeChat()
    wx.ChatWith(who=group, exact=True)
    info = wx.ChatInfo()
    if info.get('chat_name') != group or info.get('chat_type') != 'group':
        raise RuntimeError(f'目标群核验失败：{info}')
    if not callable(getattr(wx, 'GetHistoryMessage', None)):
        raise RuntimeError('当前链接库没有 GetHistoryMessage，请使用支持该方法的 Plus 版本。')
    print('先返回最新消息位置，再按固定批量向前回溯。', flush=True)
    wx.GetHistoryMessage(n=1, goback=True, timeout=timeout)
    return collect_history(wx, group, start, page_dir, batch, max_pages, timeout, download_media)


def analyze(rows, group, start, end):
    included, excluded, uncertain = [], [], []
    anchor = None
    for index, original in enumerate(rows, 1):
        row = dict(original)
        row['evidence_id'] = f'M{index:06d}'
        if row.get('group') != group:
            excluded.append(dict(row, exclusion='different_or_missing_group'))
            continue
        timestamp = parse_time(row.get('time'), start.tzinfo)
        if row.get('type') == 'time':
            anchor = timestamp
            if not anchor:
                uncertain.append(dict(row, exclusion='unparsed_time_marker'))
            continue
        if row.get('attr') not in ('friend', 'self'):
            excluded.append(dict(row, exclusion='system_or_unknown_origin'))
            continue
        effective = timestamp or anchor
        # A UI separator is contextual time, not an exact per-message timestamp.
        row['time_basis'] = 'explicit' if timestamp else 'preceding_separator'
        row['effective_time'] = effective.isoformat() if effective else None
        if not effective:
            uncertain.append(dict(row, exclusion='missing_timestamp'))
        elif start <= effective < end:
            included.append(row)
        else:
            excluded.append(dict(row, exclusion='outside_period'))
    members = defaultdict(lambda: {'messages': 0, 'characters': 0, 'days': set()})
    for row in included:
        # Display names are not unique account IDs. Self has a separate label.
        name = '本人（self）' if row.get('attr') == 'self' else row.get('sender') or '未知发送者'
        member = members[name]
        member['messages'] += 1
        if row.get('type') in ('text', 'quote'):
            member['characters'] += len(str(row.get('content', '')))
        member['days'].add(row['effective_time'][:10])
    activity = [dict(sender=name, messages=value['messages'],
                     characters=value['characters'], active_days=len(value['days']))
                for name, value in members.items()]
    activity.sort(key=lambda value: (-value['messages'], value['sender']))
    return included, excluded, uncertain, activity


from history_store import write_outputs


def find_cached_week(roots, group, start, end):
    """Find a finished export by metadata, never by folder name alone."""
    candidates = set()
    for root in roots:
        root = Path(root)
        if root.is_dir():
            candidates.add(root.resolve())
            candidates.update(p.parent.resolve() for p in root.glob('*/coverage.json'))
    valid = []
    for folder in candidates:
        try:
            metadata = folder / 'coverage.json'
            meta = json.loads(metadata.read_text(encoding='utf-8'))
            if (meta.get('group') != group or meta.get('start') != start.isoformat()
                    or meta.get('end_exclusive') != end.isoformat()
                    or (meta.get('history') or {}).get('boundary_reached') is not True):
                continue
            if not all((folder / name).is_file() for name in
                       ('raw.json', 'messages.json', 'transcript.jsonl', 'activity.csv')):
                continue
            # Validate the analysis input in a streaming pass. A truncated export
            # or metadata-only directory must not suppress a fresh capture.
            count = 0
            with (folder / 'transcript.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    when = parse_time(row.get('effective_time'), start.tzinfo)
                    if (row.get('group') != group or not row.get('evidence_id')
                            or when is None or not start <= when < end):
                        raise ValueError('cached transcript does not match its period')
                    count += 1
            if count != meta.get('included'):
                continue
            valid.append((metadata.stat().st_mtime_ns, str(folder), folder))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return max(valid)[2] if valid else None


def main():
    parser = argparse.ArgumentParser(description='群聊周报；默认最近结束的周六至周五。')
    parser.add_argument('--group', help='省略时启动询问群名')
    parser.add_argument('--start', help='起始周六 YYYY-MM-DD')
    parser.add_argument('--timezone', default='Australia/Sydney')
    parser.add_argument('--input', type=Path, help='已导出的 JSON 数组（按时间从早到晚）')
    parser.add_argument('--library', choices=['wxautox4', 'wxauto4'], default='wxautox4')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--batch', type=int, default=200, help='每轮增加读取的历史消息数')
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--page-timeout', type=float, default=60)
    parser.add_argument('--analyze', action='store_true', help='采集达到起始日期后调用 Gemini 分析')
    parser.add_argument('--model', default=os.environ.get('GEMINI_MODEL', 'gemini-4-argon'))
    parser.add_argument('--ask-key', action='store_true', help='在本机终端隐藏输入 Gemini API Key')
    parser.add_argument('--force-collect', action='store_true', help='忽略已有周记录，重新采集到新目录')
    parser.add_argument('--cache-dir', type=Path, help='另行搜索已有采集结果的根目录')
    parser.add_argument('--media', action='store_true', help='下载可取得的视频并解读公开链接，纳入议题分析')
    parser.add_argument('--prompt-file', type=Path, help='自定义分析提示词 UTF-8 文件')
    args = parser.parse_args()
    if args.input and not args.input.is_file():
        parser.exit(1, f'未找到已有导出文件：{args.input.resolve()}\n'
                    '若要直接读取微信，请去掉 --input 参数，例如：\n'
                    '  python weekly_chat.py --start 2026-10-31\n'
                    '程序将调用 GetHistoryMessage 读取历史消息。\n')
    try:
        from gemini_analysis import get_api_key
        if args.analyze and not get_api_key():
            if args.ask_key:
                import getpass
                os.environ['GEMINI_API_KEY'] = getpass.getpass('Gemini API Key（隐藏输入，仅本次使用）：')
            if not get_api_key():
                raise ValueError('请配置 GEMINI_API_KEY，或添加 --ask-key 在本机隐藏输入。')
        if args.batch < 1 or args.max_pages < 1 or args.page_timeout <= 0:
            raise ValueError('batch、max-pages 和 page-timeout 必须大于零')
        tz = ZoneInfo(args.timezone)
        group = args.group or input(f'请输入群名（回车使用测试群 {TEST_GROUP}）：').strip() or TEST_GROUP
        start, end = week(datetime.now(tz))
        if args.start:
            start = datetime.strptime(args.start, '%Y-%m-%d').replace(tzinfo=tz)
            if start.weekday() != 5:
                raise ValueError('--start 必须是周六')
            end = start + timedelta(days=7)
        print(f'群：{group}\n周期：{start.isoformat()} <= 时间 < {end.isoformat()}')
        analysis_options = {}
        if args.media:
            analysis_options['media'] = True
        if args.prompt_file:
            analysis_options['prompt_text'] = args.prompt_file.read_text('utf-8')
        if not args.input and not args.force_collect:
            roots = [Path('outputs'), Path(__file__).resolve().parent / 'outputs']
            if args.cache_dir:
                roots.append(args.cache_dir)
            if args.out:
                roots.extend([args.out, args.out.parent])
            cached = find_cached_week(roots, group, start, end)
            if cached:
                print(f'发现该群该周期已生成的记录，跳过微信采集：{cached}')
                if args.analyze:
                    from gemini_analysis import run_analysis
                    analysis_out = run_analysis(cached, args.model, **analysis_options)
                    print(f'微信文本及截图排版：{analysis_out.resolve()}')
                else:
                    print('记录已复用；添加 --analyze 可直接调用模型分析。')
                return
        out = args.out or Path('outputs') / datetime.now(tz).strftime('%Y%m%d-%H%M%S-%f')
        if out.exists():
            raise ValueError(f'输出目录已存在，请换一个路径：{out}')
        history = None
        if args.input:
            rows = json.loads(args.input.read_text(encoding='utf-8-sig'))
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise ValueError('输入应为消息对象组成的 JSON 数组')
            source = 'import_unverified'
        else:
            print('读取至起始日期之前；每轮保留原始快照，重复消息不按正文去重。')
            page_dir = out.with_name(out.name + '-pages')
            rows, history = capture(group, args.library, start, page_dir,
                                    args.batch, args.max_pages, args.page_timeout,
                                    **({'download_media': True} if args.media else {}))
            print(f'原始页及中断状态：{page_dir.resolve()}')
            source = 'history_fixed_packages'
        meta = write_outputs(out, rows, group, start, end, source, history)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        print(f'结果：{out.resolve()}')
        if history is not None and not history['boundary_reached']:
            parser.exit(2, '采集未覆盖起始日期，以上为部分结果；请检查 history.stop_reason。\n')
        if args.analyze:
            from gemini_analysis import run_analysis
            analysis_out = run_analysis(out, args.model, **analysis_options)
            print(f'微信文本及截图排版：{analysis_out.resolve()}')
    except (RuntimeError, ValueError, OSError, ImportError, KeyError) as exc:
        parser.exit(1, f'未完成：{exc}\n')


if __name__ == '__main__':
    main()
