"""Optional Playwright smoke test with synthetic reports; no model calls."""
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_app import App, handler_for
from gemini_analysis import render


def main():
    from playwright.sync_api import sync_playwright, expect
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=local) as tmp:
        app = App(Path(tmp))
        folder = app.data / 'demo-week'
        report = folder / 'analysis-demo'
        report.mkdir(parents=True)
        (folder / 'coverage.json').write_text(json.dumps({'group': '产品交流示例群', 'start': '2026-10-31T00:00:00+11:00',
            'end_exclusive': '2026-11-07T00:00:00+11:00', 'included': 1280, 'history': {'boundary_reached': True}}, ensure_ascii=False), encoding='utf-8')
        render(['这是一份合成数据周报，用于展示界面。本周讨论主要围绕产品定位、内容表达与用户反馈展开。',
                '成员在不同日期分享了各自的经验，并进一步讨论如何把建议转化为可执行的改进。资料作者的观点与群内共识需要分别理解。'], report)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        errors = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={'width': 1640, 'height': 1100}, device_scale_factor=1)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
                page.locator('#resultText').wait_for(state='visible')
                assert page.locator('#end').is_visible()
                assert page.locator('#start').get_attribute('min')
                assert page.locator('#end').get_attribute('max')
                assert '合成数据周报' in page.locator('#resultText').inner_text()
                page.locator('#group').fill('产品交流示例群')
                page.locator('#prompt').fill('自定义测试提示词：只写连续段落。')
                page.locator('#mode').select_option('analyze')
                page.locator('#run').select_option('demo-week')
                with patch.object(app, 'command', return_value=[sys.executable, '-u', '-c', 'print("合成任务完成")']):
                    page.locator('#startJob').click()
                    expect(page.locator('#status')).to_have_text('已完成', timeout=15000)
                assert '合成任务完成' in page.locator('#logs').inner_text()
                page.locator('#htmlTab').click()
                page.locator('#resultFrame').wait_for(state='visible')
                assert '合成数据周报' in page.frame_locator('#resultFrame').locator('main').inner_text()
                page.locator('#textTab').click()
                screenshots = ROOT / 'docs/assets'
                screenshots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshots / 'console.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, errors
                browser.close()
                print('Browser smoke passed: job, log, report tabs, prompt edit, mobile layout; no page errors.')
        finally:
            app.stop()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
