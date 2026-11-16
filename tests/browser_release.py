"""Static launch candidate plus a Read-account submission into simulated live main.

No live GitHub mutations; all API requests use fictitious data and credentials.
"""
import copy
import functools
import http.server
import json
import threading
import unittest
from urllib.parse import urljoin
from unittest.mock import patch

from browser_talk_submission import FormBrowserFixture, ROOT, TOKEN, QuietFiles, m
from test_talk_slides import example_pdf


class LiveSubmissionTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        self.api.branch_files(m.PUBLIC, 'main').update(copy.deepcopy(self.api.branch_files(m.PUBLIC, 'prototype/meeting-management')))
        self.preview_before = copy.deepcopy(self.api.branch_files(m.PUBLIC, 'prototype/meeting-management'))
        self.api.public_pr.update(state='closed', draft=False, merged=True)
        self.site_branch = 'main'
        config = self.directory / 'private-publication.json'
        config.write_text(json.dumps({'schema_version': 1, 'mode': 'live'}))
        patched = patch.object(m, 'PUBLICATION_CONFIG', config)
        patched.start()
        self.addCleanup(patched.stop)

    def test_read_member_can_submit_pdf_and_abstract_to_live_main_without_preview(self):
        self.open_form()
        self.credentials(TOKEN)
        self.fill_talk('Fictitious release contribution', 'A. Example', 'Fictitious release abstract.')
        pdf = example_pdf()
        self.page.locator('#slides').set_input_files({'name': 'example.pdf', 'mimeType': 'application/pdf', 'buffer': pdf})
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.wait_published()
        self.assertIn('website update may take a few minutes', self.page.locator('#submission-status').inner_text())
        self.assertEqual(self.api.permissions['member'], 'read')
        self.assertEqual(self.api.branch_files(m.PUBLIC, 'prototype/meeting-management'), self.preview_before)
        self.page.locator('#meeting-link').click()
        self.assertNotIn('/__preview/', self.page.url)
        self.assertEqual(self.page.locator('[aria-label="Preview status"]').count(), 0)
        talk = self.page.locator('li', has_text='Fictitious release contribution')
        talk.locator('summary').click()
        self.assertIn('Fictitious release abstract.', talk.inner_text())
        response = self.page.request.get(urljoin(self.page.url, talk.locator('a.talk-title').get_attribute('href')))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body(), pdf)
        self.assertFalse(self.errors)


class StaticCandidateTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietFiles, directory=str(ROOT)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def test_static_pages_navigation_forms_and_slides_at_desktop_and_mobile_sizes(self):
        legacy = next((ROOT / 'prototype/legacy-meetings').glob('*/index.html'))
        current = next((ROOT / 'prototype/meetings').glob('*/index.html'))
        paths = ['/', '/prototype/', '/' + str(legacy.parent.relative_to(ROOT)) + '/',
                 '/' + str(current.parent.relative_to(ROOT)) + '/',
                 '/prototype/admin.html', '/prototype/create-meeting.html',
                 '/prototype/submit-talk.html?meeting=' + current.parent.name,
                 '/prototype/participation.html?meeting=' + current.parent.name,
                 '/prototype/schedule.html?meeting=' + current.parent.name]
        for width in (1280, 390):
            self.page.set_viewport_size({'width': width, 'height': 950})
            for path in paths:
                with self.subTest(width=width, path=path):
                    self.assertEqual(self.page.goto(self.base + path).status, 200)
                    self.assertEqual(self.page.locator('[aria-label="Preview status"]').count(), 0)
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                    self.assertEqual(self.page.locator('a[href*="/__preview/"]').count(), 0)
                    self.assertTrue(self.page.locator('nav').first.is_visible())
        for slide in (ROOT / 'prototype/slides').rglob('*.*'):
            response = self.page.request.get(self.base + '/' + str(slide.relative_to(ROOT)))
            self.assertEqual(response.status, 200, str(slide))
            self.assertEqual(response.body(), slide.read_bytes(), str(slide))
        self.assertFalse(self.errors)
        self.assertFalse(self.external)


if __name__ == '__main__':
    unittest.main()
