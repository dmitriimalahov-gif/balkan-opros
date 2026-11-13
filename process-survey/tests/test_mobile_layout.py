#!/usr/bin/env python3
"""Регрессионные проверки мобильного экрана опроса."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MobileLayoutRegressionTest(unittest.TestCase):
    def test_fullscreen_iframe_uses_dynamic_mobile_viewport(self):
        page = (ROOT / 'pages' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('overflow:hidden;overscroll-behavior:none', page)
        self.assertIn('#app{position:absolute;', page)
        self.assertIn('height:100dvh', page)
        self.assertNotIn('#app{position:fixed;', page)
        self.assertIn("f.allow = 'clipboard-write; microphone';", page)

    def test_chat_avoids_animated_scroll_and_touch_autofocus(self):
        page = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function focusAnswer()', page)
        self.assertIn('navigator.maxTouchPoints > 0', page)
        self.assertIn("behavior: 'auto'", page)
        self.assertNotIn("behavior: 'smooth'", page)
        self.assertEqual(page.count(".focus({ preventScroll: true })"), 1)
    def test_mobile_composer_preserves_question_visibility(self):
        page = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('.composer{position:relative;bottom:auto;max-height:52dvh;overflow-y:auto', page)
        self.assertIn("log.lastElementChild.scrollIntoView({ block: 'start', behavior: 'auto' });", page)


if __name__ == '__main__':
    unittest.main(verbosity=2)
