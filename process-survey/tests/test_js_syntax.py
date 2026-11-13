#!/usr/bin/env python3
"""Синтаксическая проверка JavaScript в собранной странице опроса."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class JavaScriptSyntaxTest(unittest.TestCase):
    def test_built_page_javascript(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js не установлен')
        page = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        scripts = re.findall(r'<script(?:\s[^>]*)?>([\s\S]*?)</script>', page)
        self.assertTrue(scripts)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'survey.js'
            target.write_text('\n;\n'.join(scripts), encoding='utf-8')
            subprocess.run([node, '--check', str(target)], check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
