"""Administrator backup flow with real private handlers and fictitious credentials."""
import copy
import json
import unittest
from unittest.mock import patch

import browser_group_admin as home
from browser_talk_submission import ROOT, TOKEN, m
from test_site_backup import b, r, MemoryReleases


class BackupBrowserTests(home.GroupAdminBrowserTests):
    def setUp(self):
        super().setUp()
        self.releases = MemoryReleases()
        files = self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH)
        files['prototype/index.html'] = files['prototype/index.html'].replace('<!-- generated-meetings:end -->',
            '<!-- generated-meetings:end --><!-- legacy-meetings:start --><!-- legacy-meetings:end -->')
        self.flush_pages()
        self.backup_requests = 0
        self.backup_outcome = None

    def process_update(self):
        if not (self.last_event['comment'].get('body') or '').startswith(b.MARKER):
            return super().process_update()
        self.backup_requests += 1
        try:
            request = b.authorize(self.api, self.last_event, 'issue_comment')
            files = self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH)
            public = {k: v.encode() if isinstance(v, str) else v for k, v in files.items()}
            public['prototype/assets/style.css'] = (ROOT / 'prototype/assets/style.css').read_bytes()
            public['prototype/assets/ifip-logo.png'] = (ROOT / 'prototype/assets/ifip-logo.png').read_bytes()
            private = {'.github/group-admin.json': b'{"schema_version":1,"issue_number":82}',
                       '.github/site-publication.json': b'{"schema_version":1,"mode":"live"}'}
            snapshot = {'request_id': request['request_id'], 'created_utc': '2026-11-17T12:00:00+00:00',
                        'public_revision': 'a' * 40, 'private_revision': 'b' * 40}
            def sources(root, revision): return public if str(root) == '/fictitious-public' else private
            with patch.object(r, 'git_files', side_effect=sources), patch.object(b, 'deployed_files'):
                b.run(self.api, request, snapshot, '/fictitious-public', b.ROOT, self.releases)
            self.backup_outcome = b.previous(self.api, request)
        except (m.SetupError, r.BackupError) as error:
            self.workflow_errors.append(type(error).__name__)
            if 'request' in locals(): b.status(self.api, request, 'failed')

    def backup_done(self):
        self.page.wait_for_function("() => document.getElementById('backup-status').textContent.startsWith('Backup ready')")

    def test_button_waits_for_admin_and_has_requested_order_and_private_download(self):
        self.page.goto(self.base + '/prototype/admin.html')
        self.assertFalse(self.page.get_by_role('button', name='Backup', exact=True).is_visible())
        self.open_admin(); self.ready()
        actions = self.page.locator('.actions button:visible').all_text_contents()
        self.assertEqual(actions, ['Save changes', 'Reload content', 'Backup'])
        before = copy.deepcopy(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH))
        self.page.get_by_role('button', name='Backup', exact=True).click(); self.backup_done()
        link = self.page.get_by_role('link', name='Download ZIP', exact=True)
        self.assertTrue(link.is_visible()); self.assertEqual(link.get_attribute('href'), b.DOWNLOAD)
        self.assertEqual(self.backup_requests, 1)
        self.assertEqual(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH), before)
        self.assertFalse(any('/releases' in item['url'] for item in self.requests))
        self.assertFalse(self.workflow_errors)

    def test_unsaved_home_changes_require_save_before_backup(self):
        self.open_admin(); self.ready()
        self.page.locator('#aims').fill('Changed but unsaved.')
        self.assertTrue(self.page.get_by_role('button', name='Backup', exact=True).is_disabled())
        self.assertIn('Save Home changes', self.page.locator('#backup-status').inner_text())
        self.assertEqual(self.posts, 0)
        self.page.get_by_role('button', name='Reload content', exact=True).click(); self.ready()
        self.assertTrue(self.page.get_by_role('button', name='Backup', exact=True).is_enabled())

    def test_home_save_confirmation_enables_backup_without_retyping_password(self):
        self.open_admin(); self.ready()
        self.page.locator('#members').fill('A fictitious changed member')
        self.save(); self.done()
        self.page.get_by_role('button', name='Backup', exact=True).click(); self.backup_done()
        self.assertEqual(self.page.locator('#admin-token').input_value(), home.ADMIN)
        self.assertEqual(self.backup_requests, 1)

    def test_home_conflict_requires_reload_before_backup(self):
        self.open_admin(); self.ready()
        self.page.locator('#members').fill('Unsaved stale edit')
        files = self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH)
        people, version, content = m.profile.parse_profile(files[m.profile.DATA_PATH])
        people['past_chairs'].append('Newer fictitious correction')
        files[m.profile.DATA_PATH] = m.profile.document(people, version + 1, content)
        files['index.html'] = m.profile.render(files['index.html'], people, version + 1, content)
        self.flush_pages(); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Home changed elsewhere.')")
        self.assertTrue(self.page.get_by_role('button', name='Backup', exact=True).is_disabled())
        self.assertEqual(self.backup_requests, 0)
        self.page.get_by_role('button', name='Reload content', exact=True).click(); self.ready()
        self.assertTrue(self.page.get_by_role('button', name='Backup', exact=True).is_enabled())

    def test_member_and_revoked_admin_cannot_submit_backup(self):
        self.open_admin(credential=TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.length > 0")
        self.assertFalse(self.page.get_by_role('button', name='Backup', exact=True).is_visible())
        self.assertEqual(self.posts, 0)
        self.open_admin(); self.ready()
        self.api.permissions['manager'] = 'read'
        self.page.get_by_role('button', name='Backup', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.length > 0")
        self.assertEqual(self.posts, 0)
        self.assertFalse(self.page.get_by_role('button', name='Backup', exact=True).is_visible())

    def test_lost_post_response_and_slow_job_recover_without_duplicate_request(self):
        self.open_admin(); self.ready(); self.mode = 'pending'; self.lost = True
        self.page.get_by_role('button', name='Backup', exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('check-status').disabled && !document.getElementById('check-status').hidden")
        self.assertEqual(self.posts, 1)
        self.assertTrue(self.page.get_by_role('button', name='Backup', exact=True).is_disabled())
        self.process_update()
        self.page.get_by_role('button', name='Check progress', exact=True).click(); self.backup_done()
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.backup_requests, 1)

    def test_failed_upload_keeps_previous_file_and_shows_no_download(self):
        self.open_admin(); self.ready(); self.releases.fault = 'upload'
        self.page.get_by_role('button', name='Backup', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('backup-status').textContent.startsWith('Backup could not')")
        self.assertEqual(self.releases.files[1]['content'], b'Previous good backup')
        self.assertFalse(self.page.get_by_role('link', name='Download ZIP', exact=True).is_visible())

    def test_forged_or_unsafe_receipt_cannot_supply_download_url(self):
        self.open_admin(); self.ready(); self.mode = 'pending'
        self.page.get_by_role('button', name='Backup', exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('check-status').disabled")
        self.process_update()
        number = m.profile.control_number()
        receipt = next(c for c in self.api.comments[number] if c['body'].startswith(b.STATUS))
        receipt['body'] = receipt['body'].replace(b.DOWNLOAD, 'https://example.invalid/unsafe.zip')
        self.page.get_by_role('button', name='Check progress', exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('check-status').disabled")
        self.assertFalse(self.page.get_by_role('link', name='Download ZIP', exact=True).is_visible())

    def test_credential_change_clears_download_and_mobile_controls_wrap(self):
        self.page.set_viewport_size({'width': 390, 'height': 850})
        self.open_admin(); self.ready()
        self.page.get_by_role('button', name='Backup', exact=True).click(); self.backup_done()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('#admin-token').fill(TOKEN)
        self.assertFalse(self.page.get_by_role('button', name='Backup', exact=True).is_visible())
        self.assertFalse(self.page.get_by_role('link', name='Download ZIP', exact=True).is_visible())
        self.assertIsNone(self.page.locator('#backup-download').get_attribute('href'))
        self.assertEqual(self.page.evaluate('localStorage.length + sessionStorage.length'), 0)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(BackupBrowserTests(name) for name in BackupBrowserTests.__dict__ if name.startswith('test_'))


if __name__ == '__main__': unittest.main()
