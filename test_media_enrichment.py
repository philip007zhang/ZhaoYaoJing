import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from media_enrichment import enrich, Page, links, public_url


class MediaTests(unittest.TestCase):
    def test_page_removes_scripts_and_discovers_video(self):
        parser = Page()
        parser.feed('<p>正文</p><script>坏指令</script><video src="/clip.mp4"></video>')
        self.assertEqual(parser.text, ['正文'])
        self.assertEqual(parser.videos, ['/clip.mp4'])

    def test_no_private_urls(self):
        with patch('socket.getaddrinfo', return_value=[(0, 0, 0, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                public_url('http://localhost/a')
        self.assertEqual(links({'content': 'https://example.com/a https://example.com/a'}), ['https://example.com/a'])

    def test_web_video_cache_and_message_identity(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp) / 'week'
            folder.mkdir()
            row = {'evidence_id': 'M00000001', 'type': 'link', 'sender': '甲',
                   'content': 'https://example.com/article'}
            (folder / 'transcript.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
            calls = []
            def fetch(url):
                if url.endswith('.mp4'):
                    return b'fake-test-video', 'video/mp4', url, 'utf-8'
                return ('<p>' + '网页内容。' * 50 + '</p><video src="/a.mp4"></video>').encode(), 'text/html', url, 'utf-8'
            def fake(model, prompt, data, **kwargs):
                calls.append(kwargs)
                return {'summary': '测试资料主题', 'topics': ['主题'], 'evidence': [], 'limitations': []}
            output = enrich(folder, 'test-model', caller=fake, fetcher=fetch)
            rows = [json.loads(line) for line in output.read_text('utf-8').splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['evidence_id'], row['evidence_id'])
            self.assertEqual(len(rows[0]['media_enrichment']), 2)
            self.assertIn('inlineData', calls[1]['media_parts'][0])
            enrich(folder, 'test-model', caller=fake, fetcher=fetch)
            self.assertEqual(len(calls), 2)

    def test_missing_video_is_explicit_and_does_not_invent_text(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp) / 'week'
            folder.mkdir()
            (folder / 'transcript.jsonl').write_text(json.dumps({'type': 'video', 'content': '[视频]'}) + '\n', encoding='utf-8')
            result = enrich(folder, 'test-model', caller=lambda *args: self.fail('must not call model'))
            row = json.loads(result.read_text('utf-8'))
            self.assertEqual(row['media_enrichment'][0]['reason'], 'video_not_downloaded')
            self.assertNotIn('interpretation', row['media_enrichment'][0])


if __name__ == '__main__':
    unittest.main()
