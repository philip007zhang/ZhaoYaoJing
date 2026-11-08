"""Loopback-only browser control panel. No third-party web dependencies."""
import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from console_output import configure_console

configure_console()

ROOT = Path(__file__).resolve().parent


class App:
    def __init__(self, data_dir):
        self.data = Path(data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.process = None
        self.state = {'status': 'idle', 'logs': [], 'exit_code': None}
        self.logs = deque(maxlen=1500)

    def inside(self, value):
        path = (self.data / value).resolve()
        if not path.is_relative_to(self.data):
            raise ValueError('路径不在本地数据目录内')
        return path

    def runs(self):
        result = []
        for meta in sorted(self.data.glob('*/coverage.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                info = json.loads(meta.read_text('utf-8'))
                reports = [str(p.relative_to(self.data)).replace('\\', '/') for p in
                           sorted(meta.parent.glob('analysis-*/wechat.txt'), reverse=True)]
                packages = [str(p.relative_to(self.data)).replace('\\', '/') for p in
                            sorted(meta.parent.glob('analysis-*'), reverse=True) if list(p.glob('chunk-*.json'))]
                result.append({'id': meta.parent.name, 'group': info.get('group'),
                               'start': info.get('start'), 'included': info.get('included'),
                               'complete': bool((info.get('history') or {}).get('boundary_reached')),
                               'reports': reports, 'packages': packages})
            except (OSError, ValueError, AttributeError):
                continue
        return result

    def command(self, body, prompt_file):
        mode = body.get('mode', 'scan_analyze')
        model = str(body.get('model', 'gemini-4-argon')).strip()
        if not model or len(model) > 150:
            raise ValueError('请输入模型 ID')
        common = ['--model', model, '--prompt-file', str(prompt_file)]
        if body.get('media'):
            common.append('--media')
        if mode in ('analyze', 'resume'):
            folder = self.inside(str(body.get('run', '')))
            if not (folder / 'coverage.json').is_file():
                raise ValueError('请先选择已有采集记录')
            cmd = [sys.executable, '-X', 'utf8', str(ROOT / 'gemini_analysis.py'), str(folder)] + common
            if body.get('partial'):
                cmd.append('--allow-partial')
            if mode == 'resume':
                resume = self.inside(str(body.get('resume', '')))
                if resume.parent != folder or not (resume / 'evidence.sqlite3').is_file():
                    raise ValueError('请选择属于该采集记录的分析分片目录')
                cmd.extend(['--resume-analysis', str(resume)])
            return cmd
        if mode not in ('scan', 'scan_analyze'):
            raise ValueError('任务类型无效')
        group = str(body.get('group', '')).strip()
        if not group:
            raise ValueError('请输入群名')
        date = datetime.strptime(str(body.get('start', '')), '%Y-%m-%d')
        if date.weekday() != 5:
            raise ValueError('起始日期必须为周六')
        batch, pages, timeout = (int(body.get('batch', 100)), int(body.get('pages', 1000)), int(body.get('timeout', 120)))
        if not 1 <= batch <= 1000 or not 1 <= pages <= 10000 or not 1 <= timeout <= 600:
            raise ValueError('批量、轮数或超时超出允许范围')
        output = self.data / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        cmd = [sys.executable, '-X', 'utf8', str(ROOT / 'weekly_chat.py'), '--group', group,
               '--start', date.strftime('%Y-%m-%d'), '--out', str(output), '--cache-dir', str(self.data),
               '--batch', str(batch), '--max-pages', str(pages), '--page-timeout', str(timeout)] + common
        if mode == 'scan_analyze':
            cmd.append('--analyze')
        if body.get('force'):
            cmd.append('--force-collect')
        return cmd

    def start(self, body):
        with self.lock:
            if self.state['status'] in ('running', 'stopping'):
                raise ValueError('已有任务运行中，请等待结束或停止任务')
            prompt = str(body.get('prompt', '')).strip()
            if not prompt or len(prompt) > 20000:
                raise ValueError('提示词不能为空，且最多20000字')
            local = ROOT / '.local'
            local.mkdir(exist_ok=True)
            prompt_file = local / (uuid.uuid4().hex + '.txt')
            cmd = self.command(body, prompt_file)
            prompt_file.write_text(prompt, encoding='utf-8')
            env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding='utf-8', errors='replace', creationflags=creationflags)
            self.logs.clear()
            self.state = {'status': 'running', 'exit_code': None}
            threading.Thread(target=self.consume, args=(self.process,), daemon=True).start()

    def consume(self, process):
        for line in process.stdout:
            with self.lock:
                self.logs.append(line.rstrip())
        code = process.wait()
        process.stdout.close()
        with self.lock:
            stopped = self.state['status'] == 'stopping'
            self.state = {'status': 'stopped' if stopped else ('complete' if code == 0 else 'failed'), 'exit_code': code}

    def stop(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.state['status'] = 'stopping'
                self.process.terminate()


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, status=200, mime='application/json; charset=utf-8'):
            data = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value.encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(data)

        def local_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.local_host():
                return self.send({'error': '本服务仅限本机访问'}, 403)
            parsed = urlsplit(self.path)
            try:
                if parsed.path == '/':
                    page = (ROOT / 'web/index.html').read_text('utf-8').replace('__TOKEN__', app.token)
                    return self.send(page, mime='text/html; charset=utf-8')
                if parsed.path in ('/app.js', '/style.css'):
                    mime = 'text/javascript' if parsed.path.endswith('.js') else 'text/css'
                    return self.send((ROOT / 'web' / parsed.path[1:]).read_text('utf-8'), mime=mime + '; charset=utf-8')
                if parsed.path == '/api/config':
                    from gemini_analysis import PROMPT, get_api_key
                    from weekly_chat import week, ZoneInfo
                    return self.send({'prompt': PROMPT, 'key_configured': bool(get_api_key()),
                                      'start': week(datetime.now(ZoneInfo('Australia/Sydney')))[0].date().isoformat()})
                if parsed.path == '/api/status':
                    with app.lock:
                        return self.send(dict(app.state, logs=list(app.logs)))
                if parsed.path == '/api/runs':
                    return self.send(app.runs())
                if parsed.path == '/api/result':
                    path = app.inside(parse_qs(parsed.query).get('path', [''])[0])
                    if not re_allowed_result(path):
                        raise ValueError('文件类型不允许展示')
                    return self.send(path.read_text('utf-8'), mime=('text/html' if path.suffix == '.html' else 'text/plain') + '; charset=utf-8')
                return self.send({'error': '未找到'}, 404)
            except (OSError, ValueError) as exc:
                return self.send({'error': str(exc)}, 400)

        def do_POST(self):
            if not self.local_host() or self.headers.get('X-Local-Token') != app.token:
                return self.send({'error': '请求未授权，请刷新本机页面'}, 403)
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 100000:
                    raise ValueError('请求大小无效')
                body = json.loads(self.rfile.read(size))
                if self.path == '/api/start':
                    app.start(body)
                elif self.path == '/api/stop':
                    app.stop()
                elif self.path == '/api/key':
                    key = str(body.get('key', '')).strip()
                    if not key or len(key) > 1024:
                        raise ValueError('密钥为空或格式无效')
                    os.environ['GEMINI_API_KEY'] = key
                else:
                    return self.send({'error': '未找到'}, 404)
                return self.send({'ok': True})
            except (OSError, ValueError, TypeError) as exc:
                return self.send({'error': str(exc)}, 400)
    return Handler


def re_allowed_result(path):
    return path.name in ('wechat.txt', 'wechat.html') and path.parent.name.startswith('analysis-') and path.is_file()


def main():
    parser = argparse.ArgumentParser(description='照妖镜本地控制台')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'outputs')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    app = App(args.data_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(app))
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'照妖镜本地界面：{url}', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        server.server_close()


if __name__ == '__main__':
    main()
