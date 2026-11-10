"""The served HTML must contain the current script with its exact CSP hash."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_talk_form', ROOT / 'scripts/build_talk_form.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class TalkFormBuildTests(unittest.TestCase):
    def setUp(self):
        self.page = (ROOT / 'prototype/submit-talk.html').read_text()
        self.javascript = (ROOT / 'prototype/assets/talk-submission.js').read_text()

    def test_served_form_contains_current_script_and_needs_no_script_fetch(self):
        self.assertEqual(self.page, build.render(self.page, self.javascript))
        self.assertNotRegex(self.page, r'<script\b[^>]*\bsrc=')
        self.assertEqual(self.page.count('<script>'), 1)
        changed = self.javascript + '\n// A source update must change both HTML and policy.\n'
        self.assertNotEqual(self.page, build.render(self.page, changed))

    def test_policy_hash_matches_the_actual_script_without_allowing_arbitrary_inline_code(self):
        source = re.search(r'<script>(.*?)</script>', self.page, re.DOTALL)[1]
        digest = base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()
        policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', self.page)[1]
        script_policy = next(item for item in policy.split(';') if 'script-src' in item)
        self.assertIn("'sha256-" + digest + "'", script_policy)
        self.assertNotIn('unsafe-inline', script_policy)
        self.assertNotIn('unsafe-eval', script_policy)
        self.assertIn("form-action 'none'", policy)

    def test_unmarked_page_or_missing_script_policy_is_rejected(self):
        for page in (self.page.replace(build.START, ''), self.page.replace(build.END, ''),
                     self.page.replace("script-src 'self'", "script-src 'none'")):
            with self.subTest(page=page[:40]), self.assertRaises(ValueError):
                build.render(page, self.javascript)

    def test_script_cannot_break_out_of_its_html_element(self):
        with self.assertRaises(ValueError):
            build.render(self.page, 'const bad = "</ScRiPt><script>";')


if __name__ == '__main__':
    unittest.main()
