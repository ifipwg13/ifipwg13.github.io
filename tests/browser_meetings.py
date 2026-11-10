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
    branch = p.BRANCH

    def read(self, path):
        return (ROOT / path).read_bytes()

    def page(self, path):
        return p.styled_preview(self.read(path), self.read('prototype/assets/style.css'), self.commit,
                                self.read('prototype/assets/meetings-list.js'), self.read(p.LOGO_PATH), self.branch), self.commit

    def synchronized(self):
        return LocalSource()


class ReviewSource(LocalSource):
    branch = 'feature/review-fixture'


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
        cls.review = p.make_server(ReviewSource(), host='127.0.0.1', port=0)
        for server in (cls.static, cls.preview, cls.review):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=shutil.which('chromium'), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        for server in (cls.static, cls.preview, cls.review):
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
                    self.assertEqual(self.page.locator('[aria-labelledby="chairs-heading"] li').all_text_contents(),
                                     ['Fabio Gadducci', 'Holger Schlingloff'])
                    self.assertEqual(self.page.locator('[aria-labelledby="past-chairs-heading"] li').all_text_contents(),
                                     ['Corina Cirstea', 'Markus Roggenbach', 'Lutz Schröder', 'Till Mossakowski',
                                      'José Luiz Fiadeiro', 'Peter D. Mosses', 'Hans-Jörg Kreowski'])
                    self.assertNotIn('Secretary', self.page.locator('body').inner_text())
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
                    self.assertEqual(self.page.get_by_text('Cirstea, Corina (UK)', exact=True).count(), 1)
                    roster = self.page.locator('.members-grid').inner_text()
                    self.assertNotIn('Secretary', roster)
                    self.assertNotIn('Chairman', roster)
                    self.assertEqual(self.page.locator('h1').evaluate('node => [getComputedStyle(node).color, getComputedStyle(document.body).color]'), colors)
                    self.no_overflow()
                    self.page.get_by_role('navigation').get_by_role('link', name='Meetings', exact=True).click()
                    self.assertEqual(self.page.url, base + '/prototype/')
                    self.ordered_dates()
                    self.page.locator('.meeting-card').first.locator(':scope > h3 > a').click()
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

    def test_home_ifip_links_have_exact_destinations_restrained_styling_and_keyboard_access(self):
        destination = 'https://www.ifip.org/technical-committees-and-working-groups/'
        self.context.route(destination, lambda route: route.fulfill(status=200, content_type='text/html', body='<title>IFIP destination fixture</title>'))
        selectors = ('.brand-logo', '.site-brand a', '.affiliation a')
        for server in (self.static, self.preview):
            for width in (1100, 375, 320):
                self.page.set_viewport_size({'width': width, 'height': 950})
                for selector in selectors:
                    with self.subTest(preview=server is self.preview, width=width, selector=selector):
                        self.open(server, '/')
                        logo, brand, tc1 = [self.page.locator(value) for value in selectors]
                        self.assertEqual(tc1.inner_text(), 'IFIP TC1')
                        self.assertEqual(brand.inner_text(), 'IFIP WG1.3')
                        self.assertEqual(logo.get_attribute('aria-label'), 'IFIP technical committees and working groups')
                        for link in (logo, brand):
                            self.assertEqual(link.evaluate('node => getComputedStyle(node).textDecorationLine'), 'none')
                            link.hover()
                            self.assertEqual(link.evaluate('node => getComputedStyle(node).textDecorationLine'), 'none')
                        self.assertEqual(brand.evaluate('node => getComputedStyle(node).color'), self.page.locator('h1').evaluate('node => getComputedStyle(node).color'))
                        self.assertIn('underline', tc1.evaluate('node => getComputedStyle(node).textDecorationLine'))
                        self.assertEqual(tc1.evaluate('node => getComputedStyle(node).color'), self.page.locator('.site-nav a[href="members/"]').evaluate('node => getComputedStyle(node).color'))
                        link = self.page.locator(selector)
                        self.assertEqual(link.get_attribute('href'), destination)
                        self.assertIsNone(link.get_attribute('target'))
                        self.page.keyboard.press('Tab')
                        link.focus()
                        self.assertTrue(link.evaluate('node => node.matches(":focus-visible") && getComputedStyle(node).outlineStyle === "solid" && parseFloat(getComputedStyle(node).outlineWidth) > 0'))
                        self.no_overflow()
                        if os.environ.get('MEETINGS_SCREENSHOTS') and selector == '.affiliation a':
                            directory = Path(os.environ['MEETINGS_SCREENSHOTS'])
                            directory.mkdir(parents=True, exist_ok=True)
                            self.page.screenshot(path=str(directory / f'home-{width}.png'), full_page=True)
                        self.page.keyboard.press('Enter')
                        self.page.wait_for_url(destination)
                        self.assertEqual(len(self.context.pages), 1)
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def test_review_toolbar_switches_to_synchronized_view_and_keeps_navigation(self):
        for width in (1100, 375, 320):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.open(self.review, '/')
            status = self.page.get_by_label('Preview status', exact=True)
            self.assertIn('Review snapshot', status.inner_text())
            self.assertIn('feature/review-fixture', status.inner_text())
            status.get_by_role('link', name='Switch to synchronized preview', exact=True).click()
            prefix = f'http://127.0.0.1:{self.review.server_port}' + p.SYNCHRONIZED_VIEW
            self.assertEqual(self.page.url, prefix)
            self.assertIn('Synchronized preview', self.page.get_by_label('Preview status', exact=True).inner_text())
            self.assertIn(p.BRANCH, self.page.get_by_label('Preview status', exact=True).inner_text())
            self.page.get_by_role('navigation').get_by_role('link', name='Members', exact=True).click()
            self.assertEqual(self.page.url, prefix + 'members/')
            self.assertEqual(self.page.locator('.member-list li').count(), 70)
            self.page.get_by_role('navigation').get_by_role('link', name='Meetings', exact=True).click()
            self.assertEqual(self.page.url, prefix + 'prototype/')
            self.ordered_dates()
            self.page.locator('.meeting-card').first.locator(':scope > h3 > a').click()
            self.assertIn(prefix + 'prototype/meetings/', self.page.url)
            self.page.get_by_role('link', name='All meetings', exact=True).click()
            self.assertEqual(self.page.url, prefix + 'prototype/')
            self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def no_overflow(self):
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def check_logo(self, server):
        logo = self.page.locator('.brand-logo img')
        self.assertEqual(logo.count(), 1)
        self.assertTrue(logo.evaluate('node => node.complete && node.naturalWidth === 75 && node.naturalHeight === 142'))
        if server is self.preview:
            self.assertTrue(logo.get_attribute('src').startswith('data:image/png;base64,'))
        for selector in ('.brand-logo', '.site-brand a'):
            self.assertEqual(self.page.locator(selector).evaluate('node => node.pathname'), '/')

    def test_compact_current_talks_keep_links_and_expand_full_width_without_hide_shortcuts(self):
        for server in (self.static, self.preview):
            for width in (1100, 375, 320):
                self.page.set_viewport_size({'width': width, 'height': 950})
                self.open(server)
                links = [card.locator(':scope > h3 > a').get_attribute('href') for card in self.page.locator('.meeting-card').all()]
                for link in links:
                    self.open(server, '/prototype/' + link)
                    self.check_logo(server)
                    self.assertEqual(self.page.locator('.talk-hide').count(), 0)
                    self.assertEqual(self.page.locator('.meeting-actions .button').count(), 2)
                    archived = self.page.get_by_label('Registration status', exact=True).count() > 0
                    if archived:
                        self.assertEqual(self.page.get_by_label('Registration status', exact=True).inner_text(),
                            'This meeting is archived, registration and talk submission are closed.')
                        self.assertTrue(self.page.get_by_role('button', name='Add talk', exact=True).is_disabled())
                    else:
                        self.assertEqual(self.page.get_by_role('link', name='Add talk', exact=True).count(), 1)
                        self.assertNotIn('awaits approval', self.page.locator('body').inner_text())
                    actions = self.page.locator('.meeting-actions')
                    self.assertEqual(actions.get_by_role('link', name='Hide', exact=True).count(), 0)
                    self.assertEqual(actions.get_by_role('button', name='Archive', exact=True).count(), 0)
                    self.assertEqual(actions.get_by_role('link', name='Archive', exact=True).count(), 0)
                    rows = self.page.locator('.public-talks li').all()
                    for row in rows:
                        self.assertEqual(row.locator('span.help').count(), 0)
                        title = row.locator('.talk-title')
                        self.assertEqual(row.locator('a').count(), 1)
                        self.assertTrue(title.get_attribute('href').startswith('https://github.com/ifipwg13/meetings/issues/'))
                        self.assertEqual(title.get_attribute('target'), '_blank')
                        self.assertIn('underline', row.locator('.talk-authors').evaluate('node => getComputedStyle(node).textDecorationLine'))
                    disclosures = [row for row in rows if row.locator('.talk-abstract').count()]
                    if disclosures:
                        row = min(disclosures, key=lambda r: len(r.locator('.talk-title').inner_text() + r.locator('.talk-authors').inner_text()))
                        disclosure = row.locator('.talk-abstract')
                        self.assertEqual(disclosure.evaluate("node => (node.previousSibling?.textContent || '').trim()"), '')
                        summary = disclosure.locator('summary')
                        content = disclosure.locator('.abstract-text')
                        self.assertFalse(content.is_visible())
                        if width == 1100:
                            self.assertLess(abs(row.locator('.talk-title').bounding_box()['y'] - summary.bounding_box()['y']), 2)
                            author = row.locator('.talk-authors').bounding_box()
                            self.assertGreaterEqual(summary.bounding_box()['x'] - author['x'] - author['width'], 3)
                        summary.click()
                        self.assertTrue(content.is_visible())
                        self.assertGreater(content.bounding_box()['y'], row.locator('.talk-title').bounding_box()['y'])
                        self.assertGreaterEqual(content.bounding_box()['width'], row.bounding_box()['width'] - 2)
                        summary.focus(); self.page.keyboard.press('Enter')
                        self.assertFalse(content.is_visible())
                    self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    @unittest.skipUnless((ROOT.parent / 'meetings/tests/test_meeting_setup.py').exists(),
                         'Requires the sibling private checkout for offline lifecycle integration')
    def test_creation_and_talk_updates_work_without_setup_pr_or_fresh_listings(self):
        spec = importlib.util.spec_from_file_location('creation_browser_fixture', ROOT.parent / 'meetings/tests/test_meeting_setup.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        setup = fixture.m
        class LaggedAPI(fixture.FakeGitHub):
            def api(self, method, path, data=None, missing_ok=False):
                if method == 'GET' and (path.startswith(f'repos/{setup.PRIVATE}/issues?')
                        or path == f'repos/{setup.PRIVATE}/contents/meeting-config?ref=main'):
                    return []
                return super().api(method, path, data, missing_ok)
        api = LaggedAPI()
        before, generated = (ROOT / 'prototype/index.html').read_text().split('<!-- generated-meetings:start -->', 1)
        _, after = generated.split('<!-- generated-meetings:end -->', 1)
        api.branch_files(setup.PUBLIC, setup.PREVIEW_BRANCH)['prototype/index.html'] = (
            before + '<!-- generated-meetings:start --><!-- generated-meetings:end -->' + after)
        setup.prepare(api, setup.authorize(api, api.request(4), 'issues'))
        self.assertEqual(api.prs, {})

        class CreatedSource(LocalSource):
            def read(self, path):
                if path == 'prototype/index.html' or path.startswith('prototype/meetings/'):
                    content = api.branch_files(setup.PUBLIC, setup.PREVIEW_BRANCH).get(path)
                    if content is None:
                        raise FileNotFoundError
                    return content.encode()
                return super().read(path)
        server = p.make_server(CreatedSource(), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for offset, width in enumerate((1100, 375, 320)):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.open(server)
            self.page.locator('.meeting-card h3 a').click()
            self.assertEqual(self.page.get_by_role('link', name='Add talk', exact=True).count(), 1)
            self.assertNotIn('awaits approval', self.page.locator('body').inner_text())
            number = 7 + offset
            api.issues[number] = {'number': number, 'title': f'New talk {number}', 'state': 'open',
                'labels': ['talk', 'meeting:meeting-4'],
                'body': '### Authors\n\nExample presenter\n\n### Abstract\n\nOriginal abstract'}
            event = {'repository': {'full_name': setup.PRIVATE}, 'sender': {'login': 'member'},
                     'action': 'opened', 'issue': {'number': number}}
            setup.prepare(api, setup.authorize(api, event, 'issues'))
            self.page.reload()
            self.assertEqual(self.page.locator('.public-talks li').count(), offset + 1)
            row = self.page.locator(f'[data-talk-number="{number}"]')
            self.assertEqual(row.locator('.talk-title').inner_text(), f'New talk {number}')
            api.issues[number].update(title=f'Edited talk {number}', body='### Authors\n\nUpdated presenter\n\n### Abstract\n\nUpdated abstract')
            event['action'] = 'edited'
            setup.prepare(api, setup.authorize(api, event, 'issues'))
            self.page.reload()
            row = self.page.locator(f'[data-talk-number="{number}"]')
            self.assertEqual(row.locator('.talk-authors').inner_text(), 'Updated presenter')
            row.get_by_text('Abstract', exact=True).click()
            self.assertEqual(row.locator('.abstract-text').inner_text(), 'Updated abstract')
            self.no_overflow()
        self.assertEqual(api.prs, {})
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    @unittest.skipUnless((ROOT.parent / 'meetings/tests/test_meeting_setup.py').exists(),
                         'Requires the sibling private checkout for offline lifecycle integration')
    def test_meeting_issue_edits_replace_all_public_fields_and_survive_reactivation(self):
        spec = importlib.util.spec_from_file_location('meeting_edit_fixture', ROOT.parent / 'meetings/tests/test_meeting_setup.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        setup, api = fixture.m, fixture.FakeGitHub()
        before, generated = (ROOT / 'prototype/index.html').read_text().split('<!-- generated-meetings:start -->', 1)
        _, after = generated.split('<!-- generated-meetings:end -->', 1)
        api.branch_files(setup.PUBLIC, setup.PREVIEW_BRANCH)['prototype/index.html'] = (
            before + '<!-- generated-meetings:start --><!-- generated-meetings:end -->' + after)
        api.issues[4].update(title='Original fictitious meeting',
            body='### Start date\n\n1-3-27\n\n### End date\n\n4-3-2027\n\n### Location\n\nOriginal place\n\n### Description\n\nOriginal description')
        def run(action='edited', label=None):
            event = {'repository': {'full_name': setup.PRIVATE}, 'sender': {'login': 'manager'},
                     'action': action, 'issue': {'number': 4}}
            if label:
                event['label'] = {'name': label}
            setup.prepare(api, setup.authorize(api, event, 'issues'))
        run('opened')
        class EditedSource(LocalSource):
            def read(self, path):
                if path == 'prototype/index.html' or path.startswith('prototype/meetings/'):
                    content = api.branch_files(setup.PUBLIC, setup.PREVIEW_BRANCH).get(path)
                    if content is None:
                        raise FileNotFoundError
                    return content.encode()
                return super().read(path)
        server = p.make_server(EditedSource(), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.open(server)
        self.assertEqual(self.page.locator('[aria-labelledby="meeting-4-title"] .meeting-summary time').all_text_contents(),
                         ['01-03-2027', '04-03-2027'])
        for width in (1100, 375, 320):
            self.page.set_viewport_size({'width': width, 'height': 950})
            api.issues[4].update(title='[meeting 4] Updated meeting',
                body=f'### Start date\n\n2-1-29\n\n### End date\n\n5-1-2029\n\n### Location\n\nUpdated place\n\n### Description\n\nFresh description {width}')
            run()
            self.open(server)
            card = self.page.locator('[aria-labelledby="meeting-4-title"]')
            self.assertEqual(card.locator('h3').inner_text(), 'Updated meeting')
            self.assertEqual(card.locator('.meeting-summary time').all_text_contents(), ['02-01-2029', '05-01-2029'])
            self.assertIn('Where: Updated place', card.inner_text())
            self.assertEqual(card.locator('.meeting-description').inner_text(), f'Fresh description {width}')
            card.locator('h3 a').click()
            self.assertEqual(self.page.locator('h1').inner_text(), 'Updated meeting')
            self.assertEqual(self.page.locator('.meeting-description').inner_text(), f'Fresh description {width}')
            api.issues[4]['labels'].append('archived')
            run('labeled', 'archived')
            api.issues[4]['body'] = api.issues[4]['body'].replace(f'Fresh description {width}', f'Historical correction {width}')
            run()
            self.page.reload()
            self.assertEqual(self.page.locator('.meeting-description').inner_text(), f'Historical correction {width}')
            self.assertTrue(self.page.get_by_role('button', name='Add talk', exact=True).is_disabled())
            api.issues[4]['labels'].remove('archived')
            run('unlabeled', 'archived')
            self.page.reload()
            self.assertEqual(self.page.locator('.meeting-description').inner_text(), f'Historical correction {width}')
            self.assertEqual(self.page.get_by_role('link', name='Add talk', exact=True).count(), 1)
            self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    @unittest.skipUnless((ROOT.parent / 'meetings/tests/test_meeting_setup.py').exists(),
                         'Requires the sibling private checkout for offline lifecycle integration')
    def test_label_restoration_updates_live_cards_and_details_without_changing_talk_states(self):
        spec = importlib.util.spec_from_file_location('lifecycle_browser_fixture', ROOT.parent / 'meetings/tests/test_meeting_setup.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        setup, api = fixture.m, fixture.FakeGitHub()
        # Keep the actual page shell, assets, sorter, and historical region;
        # replace only its Issue-backed cards with the fictitious meeting.
        before, generated = (ROOT / 'prototype/index.html').read_text().split('<!-- generated-meetings:start -->', 1)
        _, after = generated.split('<!-- generated-meetings:end -->', 1)
        api.branch_files(setup.PUBLIC, setup.PREVIEW_BRANCH)['prototype/index.html'] = (
            before + '<!-- generated-meetings:start --><!-- generated-meetings:end -->' + after)
        setup.prepare(api, setup.authorize(api, api.request(4), 'issues'))
        for number, state in [(7, 'open'), (8, 'closed'), (9, 'open')]:
            api.issues[number] = {'number': number, 'title': f'Example talk {number}', 'state': state,
                'labels': ['talk', 'meeting:meeting-4'] + ([setup.TALK_HIDDEN] if number == 9 else []),
                'body': '### Authors\n\nExample presenter\n\n### Abstract\n\nExample abstract'}

        def event(action, label=None, command=None):
            value = {'repository': {'full_name': setup.PRIVATE}, 'sender': {'login': 'manager'},
                     'issue': {'number': 4}, 'action': action}
            if label:
                value['label'] = {'name': label}
            if command:
                value['comment'] = {'body': command}
            setup.prepare(api, setup.authorize(api, value, 'issue_comment' if command else 'issues'))

        class LifecycleSource(LocalSource):
            def read(self, path):
                if path == 'prototype/index.html' or path.startswith('prototype/meetings/'):
                    content = api.branch_files(setup.PUBLIC, setup.PREVIEW_BRANCH).get(path)
                    if content is None:
                        raise FileNotFoundError
                    return content.encode()
                return super().read(path)

        server = p.make_server(LifecycleSource(), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for width in (1100, 375, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 950})
                event('created', command='/archive-meeting')
                self.open(server)
                self.assertNotIn('Archived —', self.page.locator('.meeting-card').inner_text())
                self.page.locator('.meeting-card h3 a').click()
                self.assertEqual(self.page.get_by_label('Registration status').inner_text(),
                    'This meeting is archived, registration and talk submission are closed.')
                self.assertTrue(self.page.get_by_role('button', name='Add talk', exact=True).is_disabled())
                self.assertEqual(self.page.locator('.public-talks li').count(), 2)
                self.assertEqual(self.page.locator('.public-talks li span.help').count(), 0)

                event('created', command='/hide-meeting')
                self.assertEqual(self.page.reload().status, 404)
                api.issues[4]['labels'] = [label for label in api.issues[4]['labels'] if label not in {'hidden', 'archived'}]
                event('unlabeled', label='hidden')  # The event that previously re-added archived.
                self.assertEqual(self.page.reload().status, 200)
                self.assertEqual(self.page.get_by_label('Registration status').count(), 0)
                self.assertEqual(self.page.get_by_role('link', name='Participation', exact=True).count(), 1)
                self.assertEqual(self.page.get_by_role('link', name='Add talk', exact=True).count(), 1)
                self.assertEqual([api.issues[number]['state'] for number in (7, 8, 9)], ['open', 'closed', 'open'])
                self.assertEqual(self.page.locator('.public-talks li').count(), 2)
                self.assertEqual(self.page.locator('[data-talk-number="9"]').count(), 0)
                self.no_overflow()
                self.page.get_by_role('link', name='All meetings', exact=True).click()
                self.assertNotIn('Archived —', self.page.locator('.meeting-card').inner_text())
                self.assertEqual(self.page.locator('.meeting-card .button').count(), 0)
                self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

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

    def test_cards_use_meeting_names_and_have_no_redundant_buttons_on_desktop_or_mobile(self):
        for width in (1100, 375, 320):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.open(self.preview)
            self.no_overflow()
            cards = self.page.locator('.meeting-card')
            for card in cards.all():
                self.assertEqual(card.locator('.button, button, .organizer-controls').count(), 0)
                self.assertEqual(card.locator(':scope > h3 > a').count(), 1)
                self.assertTrue(card.locator(':scope > h3 > a').get_attribute('href').startswith('meetings/'))
                self.assertEqual(card.get_by_text('Manage meeting', exact=True).count(), 0)
            reference = cards.first.evaluate('node => [getComputedStyle(node).border, getComputedStyle(node).padding, getComputedStyle(node).font]')
            for card in self.page.locator('.legacy-meeting-card').all():
                self.assertEqual(card.locator('.button').count(), 0)
                self.assertEqual(card.locator(':scope > h3 > a').count(), 1)
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
        links = [card.locator(':scope > h3 > a').get_attribute('href') for card in cards.all()]
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
                    for name in ['.talk-title', '.talk-authors']:
                        self.assertIn('underline', row.locator(name).evaluate('node => getComputedStyle(node).textDecorationLine'))
                    disclosure = row.locator('.talk-abstract')
                    self.assertEqual(disclosure.count(), int(bool(talk['abstract'])))
                    if talk['abstract']:
                        self.assertEqual(disclosure.evaluate("node => (node.previousSibling?.textContent || '').trim()"), '')
                        self.assertIsNone(disclosure.get_attribute('open'))
                        self.assertEqual(disclosure.locator('.abstract-text').text_content(), talk['abstract'])
                self.no_overflow()
        self.assertFalse(self.external)
        self.assertFalse(self.errors)

    def test_native_talk_and_abstract_disclosures_work_with_click_and_keyboard(self):
        for width in (1100, 375, 320):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.open(self.preview)
            self.assertTrue(self.page.get_by_label('Preview status', exact=True).is_visible())
            card = self.page.locator('.legacy-meeting-card').first
            overview = card.locator('details.talks-overview')
            abstract = overview.locator('details.talk-abstract').first
            self.assertFalse(abstract.is_visible())
            overview.locator(':scope > summary').click()
            for control in overview.locator('details.talk-abstract > summary').all():
                # Inline summaries expose separate arrow/text fragments. They
                # must share a visual line, even when the whole control wraps.
                self.assertEqual(control.evaluate('node => new Set(Array.from(node.getClientRects()).filter(r => r.width > 0).map(r => Math.round(r.y))).size'), 1)
            text = abstract.locator('.abstract-text')
            self.assertFalse(text.is_visible())
            summary = abstract.locator('summary')
            row = overview.locator('.talk-list > li').first
            title = row.locator('.talk-title')
            if width == 1100:
                self.assertLess(abs(title.bounding_box()['y'] - summary.bounding_box()['y']), 2)
                author = row.locator('.talk-authors').bounding_box()
                self.assertGreaterEqual(summary.bounding_box()['x'] - author['x'] - author['width'], 3)
            title.click()
            row.locator('.talk-authors').click()
            self.assertFalse(text.is_visible())
            self.assertEqual(title.evaluate('node => node.tagName'), 'SPAN')
            self.assertIsNone(title.get_attribute('role'))
            self.assertIsNone(title.get_attribute('tabindex'))
            summary.click()
            self.assertTrue(text.is_visible())
            self.assertGreaterEqual(text.bounding_box()['width'], row.bounding_box()['width'] - 2)
            summary.focus()
            self.page.keyboard.press('Enter')
            self.assertFalse(text.is_visible())
            self.page.keyboard.press('Space')
            self.assertTrue(text.is_visible())
            self.no_overflow()
            self.assertEqual(overview.locator('.talk-list a').count(), 0)
            view = card.locator(':scope > h3 > a')
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
            page.locator('.legacy-meeting-card').first.locator(':scope > h3 > a').click()
            disclosure = page.locator('details.talk-abstract').first
            self.assertFalse(disclosure.locator('.abstract-text').is_visible())
            disclosure.locator('summary').click()
            self.assertTrue(disclosure.locator('.abstract-text').is_visible())
            self.assertEqual(page.locator('.talk-list > li .talk-authors').first.inner_text(), self.records[0]['talks'][0]['authors'])
            page.goto(f'http://127.0.0.1:{self.review.server_port}/')
            status = page.get_by_label('Preview status', exact=True)
            self.assertIn('Review snapshot', status.inner_text())
            status.get_by_role('link', name='Switch to synchronized preview', exact=True).click()
            self.assertIn('Synchronized preview', page.get_by_label('Preview status', exact=True).inner_text())
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
