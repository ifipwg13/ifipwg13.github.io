"""Optional browser regressions: python3 tests/browser_meetings.py.

Uses an already installed Playwright/Chromium; no production dependencies,
GitHub credentials, external requests, or private repository writes.
"""
import functools
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import threading
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preview', ROOT / 'scripts/preview_server.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class LocalSource:
    commit = 'a' * 40

    def read(self, path):
        return (ROOT / path).read_bytes()

    def page(self, path):
        return p.styled_preview(self.read(path), self.read('prototype/assets/style.css'), self.commit,
                                self.read('prototype/assets/meetings-list.js')), self.commit


class QuietFiles(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(sync_playwright and shutil.which('chromium'), 'Optional installed Playwright/Chromium required')
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads((ROOT / 'prototype/data/legacy-meetings.json').read_text())
        cls.sorter = (ROOT / 'prototype/assets/meetings-list.js').read_text()
        cls.static = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
            functools.partial(QuietFiles, directory=str(ROOT)))
        cls.preview = p.make_server(LocalSource(), host='127.0.0.1', port=0)
        for server in (cls.static, cls.preview):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=shutil.which('chromium'), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        for server in (cls.static, cls.preview):
            server.shutdown()
            server.server_close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1100, 'height': 950})
        self.addCleanup(self.context.close)
        self.external = []
        self.errors = []
        def route(request):
            if request.request.url.startswith('http://127.0.0.1:'):
                request.continue_()
            else:
                self.external.append(request.request.url)
                request.abort()
        self.context.route('**/*', route)
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def open(self, server, path='/prototype/'):
        response = self.page.goto(f'http://127.0.0.1:{server.server_port}' + path)
        self.assertEqual(response.status, 200)

    def test_home_members_meetings_and_detail_navigation_match_static_hosting(self):
        for server in (self.static, self.preview):
            base = f'http://127.0.0.1:{server.server_port}'
            for width in (1100, 375, 320):
                with self.subTest(preview=server is self.preview, width=width):
                    self.page.set_viewport_size({'width': width, 'height': 950})
                    self.open(server, '/')
                    self.assertEqual(self.page.locator('h1').inner_text(), 'Foundations of System Specification')
                    self.assertEqual(self.page.locator('.affiliation').inner_text(), 'An IFIP TC1 Working Group')
                    nav = self.page.get_by_role('navigation', name='Main navigation')
                    self.assertEqual(nav.get_by_role('link').all_text_contents(), ['Home', 'Members', 'Meetings'])
                    self.assertEqual(nav.locator('a').evaluate_all('links => links.map(a => a.pathname)'), ['/', '/members/', '/prototype/'])
                    self.assertEqual(nav.locator('[aria-current="page"]').inner_text(), 'Home')
                    colors = self.page.locator('h1').evaluate('node => [getComputedStyle(node).color, getComputedStyle(document.body).color]')
                    self.no_overflow()
                    nav.get_by_role('link', name='Members', exact=True).click()
                    self.assertEqual(self.page.url, base + '/members/')
                    self.assertEqual(self.page.locator('#members-heading').inner_text(), 'Members')
                    self.assertEqual(self.page.locator('#emeriti-heading').inner_text(), 'Emeriti')
                    self.assertEqual(self.page.locator('[aria-labelledby="members-heading"] li').count(), 34)
                    self.assertEqual(self.page.locator('[aria-labelledby="emeriti-heading"] li').count(), 36)
                    self.assertEqual(self.page.locator('.member-list a').count(), 0)
                    self.assertEqual(self.page.get_by_text('Cirstea, Corina (UK) Secretary', exact=True).count(), 1)
                    self.assertEqual(self.page.locator('h1').evaluate('node => [getComputedStyle(node).color, getComputedStyle(document.body).color]'), colors)
                    self.no_overflow()
                    self.page.get_by_role('navigation').get_by_role('link', name='Meetings', exact=True).click()
                    self.assertEqual(self.page.url, base + '/prototype/')
                    self.ordered_dates()
                    self.page.locator('.meeting-card').first.locator(':scope > a.button').click()
                    self.assertEqual(self.page.locator('h1').evaluate('node => [getComputedStyle(node).color, getComputedStyle(document.body).color]'), colors)
                    self.page.get_by_role('link', name='All meetings', exact=True).click()
                    self.assertEqual(self.page.url, base + '/prototype/')
                    self.page.get_by_role('navigation').get_by_role('link', name='Home', exact=True).click()
                    self.assertEqual(self.page.url, base + '/')
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def ordered_dates(self):
        values = self.page.locator('section[aria-label="Meetings"] > article').evaluate_all(
            'cards => cards.map(card => card.querySelector(".meeting-summary time").dateTime.slice(0, 10))')
        self.assertEqual(values, sorted(values, reverse=True))
        return values

    def no_overflow(self):
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def test_single_sorted_list_survives_interleaved_old_issue_meetings_and_repeated_sort(self):
        for server in (self.static, self.preview):
            with self.subTest(preview=server is self.preview):
                self.open(server)
                self.assertEqual(self.page.locator('section[aria-label="Meetings"]').count(), 1)
                self.assertEqual(self.page.locator('.legacy-meeting-card').count(), len(self.records))
                original = self.ordered_dates()
                self.assertEqual(len(original), len(self.records) + self.page.locator('.meeting-card').count())
                self.assertEqual(self.page.get_by_text('Past meetings', exact=True).count(), 0)
                self.page.evaluate('''() => {
                  const fixture = document.querySelector('article.meeting-card').cloneNode(true);
                  fixture.id = 'sort-fixture';
                  fixture.querySelector('time').dateTime = '2020-06-01';
                  document.querySelector('section[aria-label="Meetings"]').append(fixture);
                }''')
                for _ in range(3):
                    self.page.evaluate(self.sorter)
                    ordered = self.ordered_dates()
                    self.assertEqual(len(ordered), len(original) + 1)
                    self.assertEqual(self.page.locator('#sort-fixture').count(), 1)
                self.assertGreater(ordered.index('2020-06-01'), 0)
                self.assertLess(ordered.index('2020-06-01'), len(ordered) - 1)
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def test_card_actions_share_desktop_row_and_wrap_without_overflow_on_mobile(self):
        for width in (1100, 375, 320):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.open(self.preview)
            self.no_overflow()
            cards = self.page.locator('.meeting-card')
            for card in cards.all():
                actions = card.locator(':scope > .button, :scope > .organizer-controls .button')
                self.assertEqual(actions.all_text_contents(), ['View meeting', 'Archive', 'Hide'])
                boxes = [action.bounding_box() for action in actions.all()]
                if width == 1100:
                    self.assertLessEqual(max(box['y'] for box in boxes) - min(box['y'] for box in boxes), 1)
                elif boxes[1]['y'] > boxes[0]['y'] + 1:
                    self.assertGreaterEqual(boxes[1]['y'] - boxes[0]['y'] - boxes[0]['height'], 8)
                self.assertEqual(card.get_by_text('Manage meeting', exact=True).count(), 0)
            reference = cards.first.evaluate('node => [getComputedStyle(node).border, getComputedStyle(node).padding, getComputedStyle(node).font]')
            for card in self.page.locator('.legacy-meeting-card').all():
                self.assertEqual(card.locator('.button').all_text_contents(), ['View meeting'])
                self.assertEqual(card.locator('.organizer-controls, .talk-hide, button, [href*="github.com"]').count(), 0)
                self.assertEqual(card.evaluate('node => [getComputedStyle(node).border, getComputedStyle(node).padding, getComputedStyle(node).font]'), reference)
            if os.environ.get('MEETINGS_SCREENSHOTS'):
                directory = Path(os.environ['MEETINGS_SCREENSHOTS'])
                directory.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(directory / f'meetings-{width}.png'), full_page=True)
        self.assertFalse(self.errors)

    def test_every_historical_page_has_only_approved_content_and_exact_abstract_text(self):
        self.open(self.static)
        cards = self.page.locator('.legacy-meeting-card')
        links = [card.locator(':scope > a.button').get_attribute('href') for card in cards.all()]
        for record, link in zip(self.records, links):
            with self.subTest(meeting=record['name']):
                self.open(self.static, '/prototype/' + link)
                self.assertEqual(self.page.locator('h1').inner_text(), record['name'])
                self.assertEqual(self.page.locator('.meeting-summary time').first.get_attribute('datetime'), record['start_date'])
                self.assertEqual(self.page.locator('.meeting-summary time').last.get_attribute('datetime'), record['end_date'])
                self.assertEqual(self.page.locator('.meeting-summary p').last.inner_text(), 'Where: ' + record['location'])
                self.assertEqual(self.page.locator('.button, .organizer-controls, .talk-hide, [href*="github.com"]').count(), 0)
                rows = self.page.locator('.talk-list > li')
                self.assertEqual(rows.count(), len(record['talks']))
                for row, talk in zip(rows.all(), record['talks']):
                    self.assertEqual(row.locator('.talk-title').text_content(), talk['title'])
                    self.assertEqual(row.locator('.talk-authors').text_content(), talk['authors'])
                    self.assertEqual(row.locator('a').count(), 0)
                    disclosure = row.locator('.talk-abstract')
                    self.assertEqual(disclosure.count(), int(bool(talk['abstract'])))
                    if talk['abstract']:
                        self.assertIsNone(disclosure.get_attribute('open'))
                        self.assertEqual(disclosure.locator('.abstract-text').text_content(), talk['abstract'])
                self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def test_native_talk_and_abstract_disclosures_work_with_click_and_keyboard(self):
        for width in (1100, 375, 320):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.open(self.preview)
            self.assertTrue(self.page.get_by_label('Live preview', exact=True).is_visible())
            card = self.page.locator('.legacy-meeting-card').first
            overview = card.locator('details.talks-overview')
            abstract = overview.locator('details.talk-abstract').first
            self.assertFalse(abstract.is_visible())
            overview.locator(':scope > summary').click()
            text = abstract.locator('.abstract-text')
            self.assertFalse(text.is_visible())
            summary = abstract.locator('summary')
            summary.click()
            self.assertTrue(text.is_visible())
            summary.focus()
            self.page.keyboard.press('Enter')
            self.assertFalse(text.is_visible())
            self.page.keyboard.press('Space')
            self.assertTrue(text.is_visible())
            self.no_overflow()
            self.assertEqual(overview.locator('.talk-list a').count(), 0)
            view = card.locator(':scope > a.button')
            target = view.get_attribute('href')
            view.click()
            self.assertTrue(self.page.url.endswith('/prototype/' + target))
            self.assertEqual(self.page.locator('.talk-list > li .talk-authors').first.text_content(), self.records[0]['talks'][0]['authors'])
            self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def test_group_pages_and_legacy_abstracts_work_without_javascript(self):
        context = self.browser.new_context(java_script_enabled=False, viewport={'width': 375, 'height': 950})
        try:
            page = context.new_page()
            base = f'http://127.0.0.1:{self.static.server_port}'
            self.assertEqual(page.goto(base + '/').status, 200)
            page.get_by_role('navigation').get_by_role('link', name='Members', exact=True).click()
            self.assertEqual(page.locator('.member-list > li').count(), 70)
            page.get_by_role('navigation').get_by_role('link', name='Meetings', exact=True).click()
            page.locator('.legacy-meeting-card').first.locator(':scope > a.button').click()
            disclosure = page.locator('details.talk-abstract').first
            self.assertFalse(disclosure.locator('.abstract-text').is_visible())
            disclosure.locator('summary').click()
            self.assertTrue(disclosure.locator('.abstract-text').is_visible())
            self.assertEqual(page.locator('.talk-list > li .talk-authors').first.inner_text(), self.records[0]['talks'][0]['authors'])
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
