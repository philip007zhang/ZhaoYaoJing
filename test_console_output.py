import subprocess
import sys
import unittest


class ConsoleTests(unittest.TestCase):
    def test_chinese_progress_survives_western_console(self):
        script = "import sys; sys.stdout.reconfigure(encoding='cp1252'); from console_output import configure_console; configure_console(); print(chr(0x7fa4)+chr(0x804a))"
        result = subprocess.run([sys.executable, '-X', 'utf8=0', '-c', script], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode('utf-8').strip(), '群聊')


if __name__ == '__main__':
    unittest.main()
