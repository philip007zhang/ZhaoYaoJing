import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from gemini_analysis import run_analysis, render, get_api_key


class AnalysisTests(unittest.TestCase):
    def test_reads_saved_windows_user_key_without_process_refresh(self):
        fake_registry = MagicMock()
        fake_registry.QueryValueEx.return_value = ('test-placeholder', 1)
        with patch.dict('os.environ', {'GEMINI_API_KEY': ''}), \
                patch('gemini_analysis.os.name', 'nt'), \
                patch.dict('sys.modules', {'winreg': fake_registry}):
            self.assertEqual(get_api_key(), 'test-placeholder')
            fake_registry.QueryValueEx.assert_called_once()

    def fixture(self, folder, complete=True):
        (folder / 'coverage.json').write_text(json.dumps({'included': 1, 'history': {
            'boundary_reached': complete}, 'group': '测试群'}), encoding='utf-8')
        (folder / 'transcript.jsonl').write_text(json.dumps({
            'evidence_id': 'M00000001', 'sender': '测试成员', 'content': '建议先核对原始数据。'},
            ensure_ascii=False) + '\n', encoding='utf-8')
        (folder / 'activity.csv').write_text('sender,messages,characters,active_days\n测试成员,1,10,1\n', encoding='utf-8-sig')

    def test_full_analysis_and_wechat_render(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            self.fixture(folder)
            calls = []
            def fake(model, instruction, data):
                calls.append((model, instruction))
                if 'messages' in data:
                    return {'findings': [{'text': '成员建议核对数据', 'evidence': [
                        {'id': 'M00000001', 'quote': '先核对原始数据'}]}]}
                return {'paragraphs': ['本周测试成员提出核对数据的建议，原文为“先核对原始数据”（M00000001）。']}
            out = run_analysis(folder, 'gemini-4-argon', caller=fake)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all('最多10个' in instruction for _, instruction in calls))
            self.assertNotIn('M00000001', (out / 'wechat.txt').read_text('utf-8'))
            self.assertTrue((out / 'wechat-01.txt').exists())
            self.assertTrue((out / 'wechat.html').exists())

    def test_invalid_and_missing_citations_do_not_abort(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            self.fixture(folder)
            def fake(model, instruction, data):
                if 'messages' in data:
                    return {'findings': [{'text': '概括性分析', 'evidence': [
                        {'id': 'M00000001', 'quote': '并不存在的原文'}]}]}
                return {'paragraphs': ['本周讨论涉及数据核对（M99999999）。']}
            out = run_analysis(folder, 'gemini-4-argon', caller=fake)
            self.assertTrue((out / 'wechat.txt').exists())
            self.assertNotIn('M99999999', (out / 'wechat.txt').read_text('utf-8'))
            self.assertTrue(json.loads((out / 'citation_warnings.json').read_text('utf-8')))
            def synthesis_only(model, instruction, data):
                self.assertNotIn('messages', data)
                return {'paragraphs': ['本周主要讨论数据核对，供群友参考。']}
            resumed = run_analysis(folder, 'gemini-4-argon', caller=synthesis_only, resume_dir=out)
            self.assertTrue((resumed / 'wechat.txt').exists())

    def test_partial_does_not_call_model(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            self.fixture(folder, complete=False)
            def fake(*args):
                self.fail('partial input must not call model')
            with self.assertRaisesRegex(ValueError, '起始日期'):
                run_analysis(folder, 'gemini-4-argon', caller=fake)

    def test_custom_prompt_reaches_both_stages_and_saved_report(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            self.fixture(folder)
            custom = '自定义：特别关注未解决的问题。'
            seen = []
            def fake(model, instruction, data):
                seen.append(instruction)
                if 'messages' in data:
                    return {'findings': [{'text': '建议核对数据', 'evidence': []}]}
                return {'paragraphs': ['本周有成员建议核对数据，尚待进一步跟进。']}
            out = run_analysis(folder, 'gemini-4-argon', caller=fake, prompt_text=custom)
            self.assertEqual(len(seen), 2)
            self.assertTrue(all(instruction.startswith(custom) for instruction in seen))
            self.assertEqual((out / 'prompt.txt').read_text('utf-8'), custom)

    def test_render_escapes_html_and_supports_lists(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            render(['原文含有<script>，应显示为普通文字。'], folder)
            self.assertIn('&lt;script&gt;', (folder / 'wechat.html').read_text('utf-8'))
            render(['【待解决问题】', '- 需要核对数据（M00000001）\n- 明确时间（Message ID: M00000002）'], folder)
            text = (folder / 'wechat.txt').read_text('utf-8')
            self.assertNotIn('M00000001', text)
            self.assertNotIn('Message ID', text)
            self.assertIn('- 需要核对数据', text)
            page = (folder / 'wechat.html').read_text('utf-8')
            self.assertIn('<li>', page)
            self.assertIn('<h2>', page)

    def test_overlong_report_is_condensed_and_keeps_original(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            self.fixture(folder)
            def fake(model, instruction, data):
                if 'messages' in data:
                    return {'findings': [{'text': '核对数据', 'evidence': []}]}
                if 'paragraphs' in data:
                    return {'paragraphs': ['【待解决问题】', '• 先核对数据，再确定处理方案。']}
                return {'paragraphs': ['讨论内容。' * 300]}
            out = run_analysis(folder, 'gemini-4-argon', caller=fake)
            self.assertLess(len((out / 'wechat.txt').read_text('utf-8')), 1200)
            self.assertTrue((out / 'analysis-before-condensing.json').exists())


if __name__ == '__main__':
    unittest.main()
