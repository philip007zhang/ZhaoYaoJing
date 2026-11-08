import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from local_app import App, handler_for


class LocalAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.app = App(Path(self.tmp.name) / 'outputs')

    def tearDown(self):
        self.app.stop()
        self.tmp.cleanup()

    def test_commands_include_prompt_media_and_cache_without_shell(self):
        prompt = Path(self.tmp.name) / 'prompt.txt'
        cmd = self.app.command({'mode': 'scan_analyze', 'group': '测试群', 'start': '2026-10-31',
                                'media': True, 'force': True}, prompt)
        self.assertIn('--prompt-file', cmd)
        self.assertIn('--cache-dir', cmd)
        self.assertIn('--analyze', cmd)
        self.assertIn('--media', cmd)
        self.assertIn('--force-collect', cmd)
        self.assertEqual(cmd[cmd.index('--group') + 1], '测试群')

    def test_paths_and_resume_are_confined_to_selected_run(self):
        with self.assertRaises(ValueError):
            self.app.inside('../outside')
        folder = self.app.data / 'run'
        folder.mkdir()
        (folder / 'coverage.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.app.command({'mode': 'resume', 'run': 'run', 'resume': '../other'}, Path('p'))

    def test_sunday_cannot_start_scan(self):
        with self.assertRaisesRegex(ValueError, '周六'):
            self.app.command({'group': '测试', 'start': '2026-11-01'}, Path('p'))

    def test_single_worker_rejects_second_job(self):
        self.app.state['status'] = 'running'
        with self.assertRaisesRegex(ValueError, '已有任务'):
            self.app.start({'prompt': '测试'})

    def test_report_catalog_does_not_return_chat_body(self):
        folder = self.app.data / 'run'
        folder.mkdir()
        (folder / 'coverage.json').write_text(json.dumps({'group': '合成群', 'included': 1,
                                                        'history': {'boundary_reached': True}}), encoding='utf-8')
        report = folder / 'analysis-test'
        report.mkdir()
        (report / 'wechat.txt').write_text('私人正文', encoding='utf-8')
        result = self.app.runs()
        self.assertEqual(result[0]['reports'], ['run/analysis-test/wechat.txt'])
        self.assertNotIn('私人正文', json.dumps(result))

    def test_http_host_csrf_and_result_traversal(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            try:
                connection.request(method, path, body, headers or {})
                response = connection.getresponse()
                return response.status, response.read().decode('utf-8')
            finally:
                connection.close()
        try:
            status, page = request('GET', '/')
            self.assertEqual(status, 200)
            self.assertIn(self.app.token, page)
            self.assertEqual(request('GET', '/api/status', headers={'Host': 'evil.test'})[0], 403)
            self.assertEqual(request('POST', '/api/stop', '{}')[0], 403)
            self.assertEqual(request('GET', '/api/result?path=../secret.txt')[0], 400)
            self.assertEqual(request('POST', '/api/stop', '{}', {'X-Local-Token': self.app.token})[0], 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
