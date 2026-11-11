"""Fictitious Read-account reaction tests through the real preview handler.

GitHub authorization is modeled here; real Read-account/Firefox acceptance is
documented separately and must not be claimed from the simulated API.
"""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import unittest

from browser_talk_submission import FormBrowserFixture, TOKEN, API, m, preview

OTHER_TOKEN = 'github_pat_OTHER_FICTITIOUS_TEST_ONLY'


class ParticipationBrowserTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        self.reactions = {4: [
            {'id': 100, 'content': '+1', 'user': {'id': 22, 'login': 'PRIVATE-OTHER-CANARY'}},
            {'id': 101, 'content': 'heart', 'user': {'id': 11, 'login': 'member'}},
        ]}
        self.mutations = []
        self.lost = False
        self.lock_on_write = False
        self.auth_error = None
        self.deny_mutations = False
        self.registration = 4
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        public = self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH)
        self.public_before = copy.deepcopy(public)
        source = Path(__file__).resolve().parents[1] / 'prototype/participation.html'
        (self.directory / 'prototype/participation.html').write_bytes(source.read_bytes())

    def route(self, route):
        request = route.request
        if not request.url.startswith(API + '/'):
            return super().route(route)
        url = urlsplit(request.url)
        self.requests.append({'method': request.method, 'url': request.url, 'headers': request.headers, 'body': request.post_data})
        if request.method == 'OPTIONS':
            route.fulfill(status=204, headers={'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, DELETE',
                          'Access-Control-Allow-Headers': 'authorization,content-type,x-github-api-version'})
            return
        authorization = request.headers.get('authorization')
        self.assertIn(authorization, {'Bearer ' + TOKEN, 'Bearer ' + OTHER_TOKEN})
        for token in (TOKEN, OTHER_TOKEN):
            self.assertNotIn(token, request.url)
            self.assertNotIn(token, request.post_data or '')
        owner = {'id': 11, 'login': 'member'} if authorization == 'Bearer ' + TOKEN else {'id': 22, 'login': 'member-two'}
        path = url.path
        if self.auth_error:
            self.json_response(route, {'message': 'Do not echo this private response'}, self.auth_error)
        elif path == '/user':
            self.json_response(route, owner)
        elif path == '/repos/' + m.PRIVATE:
            self.json_response(route, {'full_name': m.PRIVATE, 'permissions': {'pull': True, 'push': False, 'admin': False}})
        elif '/issues/' in path:
            tail = path.split('/issues/', 1)[1].split('/')
            number = int(tail[0])
            issue = self.api.issues.get(number)
            if issue is None:
                self.json_response(route, {}, 404)
                return
            if len(tail) == 1:
                self.json_response(route, self.api.issue_record(issue))
                return
            self.assertEqual(tail[1], 'reactions')
            records = self.reactions.setdefault(number, [])
            if request.method == 'GET':
                query = parse_qs(url.query)
                self.assertEqual(query.get('content'), ['+1'])
                filtered = [record for record in records if record['content'] == '+1']
                page = int(query.get('page', ['1'])[0])
                self.json_response(route, filtered[(page - 1) * 100:page * 100])
                return
            self.mutations.append((request.method, path, request.post_data_json))
            if self.deny_mutations:
                self.json_response(route, {}, 403)
                return
            if self.lock_on_write:
                issue['locked'] = True
            if issue.get('locked'):
                self.json_response(route, {}, 403)
                return
            if request.method == 'POST':
                self.assertEqual(request.post_data_json, {'content': '+1'})
                existing = next((record for record in records if record['user']['id'] == owner['id'] and record['content'] == '+1'), None)
                if existing:
                    self.json_response(route, existing, 200)
                    return
                reaction = {'id': 1000 + len(records), 'content': '+1', 'user': owner}
                records.append(reaction)
                if self.lost: route.abort('failed')
                else: self.json_response(route, reaction, 201)
            elif request.method == 'DELETE':
                reaction = next((record for record in records if record['id'] == int(tail[2])), None)
                if reaction is None:
                    self.json_response(route, {}, 404)
                    return
                # Fail loudly if the application ever targets someone else's ID.
                self.assertEqual(reaction['user']['id'], owner['id'])
                self.assertEqual(reaction['content'], '+1')
                records.remove(reaction)
                if self.lost: route.abort('failed')
                else: route.fulfill(status=204, headers={'Access-Control-Allow-Origin': '*'})
            else:
                raise AssertionError('Unexpected mutation')
        else:
            raise AssertionError('Unexpected API route: ' + path)

    def open_participation(self, ident='meeting-4', ready=True):
        self.page.goto(self.base + '/prototype/participation.html?meeting=' + ident)
        if ready:
            self.page.wait_for_function("() => !document.getElementById('participation-fields').disabled")

    def check(self, credential=TOKEN):
        self.page.locator('#github-token').fill(credential)
        self.page.get_by_role('button', name='Check token', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('identity').textContent.startsWith('Submitting as')")

    def choose(self, action):
        self.page.get_by_role('radio', name=action, exact=True).check()
        self.page.get_by_role('button', name='Submit', exact=True).click()

    def confirmed(self, registered):
        expected = 'Registration confirmed.' if registered else 'Unregistration confirmed.'
        self.page.wait_for_function('(text) => document.getElementById("submission-status").textContent === text', arg=expected)

    def test_register_unregister_idempotence_privacy_and_read_role(self):
        self.page.goto(self.base + '/prototype/meetings/meeting-4/')
        self.page.get_by_role('link', name='Participation', exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('participation-fields').disabled")
        self.assertEqual(self.page.locator('#meeting-name').inner_text(), 'Demo Meeting 002')
        self.check()
        self.assertIn('not registered', self.page.locator('#participation-status').inner_text())
        self.choose('Register')
        self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)
        self.choose('Register')
        self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)
        self.choose('Unregister')
        self.confirmed(False)
        self.assertEqual([method for method, _, _ in self.mutations], ['POST', 'DELETE'])
        self.choose('Unregister')
        self.confirmed(False)
        self.assertEqual(len(self.mutations), 2)
        self.assertEqual([record['id'] for record in self.reactions[4]], [100, 101])
        self.assertNotIn('PRIVATE-OTHER-CANARY', self.page.content())
        self.assertNotIn(TOKEN, self.page.content())
        self.assertEqual(self.page.evaluate('[localStorage.length, sessionStorage.length]'), [0, 0])
        self.assertEqual(self.api.permissions['member'], 'read')
        self.assertEqual(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH), self.public_before)
        self.assertFalse(self.errors)

    def test_legacy_preview_allowlist_and_mobile_layout(self):
        original = preview.resource_path
        def old_allowlist(url):
            path = original(url)
            if path.endswith('.js') and not path.endswith('/meetings-list.js'): raise FileNotFoundError
            return path
        scripts = []
        self.page.on('request', lambda request: scripts.append(request.url) if request.url.endswith('.js') else None)
        with patch.object(preview, 'resource_path', side_effect=old_allowlist):
            for width in (1100, 375, 320):
                self.page.set_viewport_size({'width': width, 'height': 950})
                self.open_participation()
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.check()
            self.choose('Register')
            self.confirmed(True)
        self.assertFalse(scripts)

    def test_lost_register_or_delete_responses_are_checked_without_repeating_writes(self):
        self.open_participation()
        self.check()
        self.lost = True
        self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('check-status').hidden")
        self.assertEqual(len(self.mutations), 1)
        self.page.get_by_role('button', name='Check participation status').click()
        self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)
        self.choose('Unregister')
        self.page.wait_for_function("() => !document.getElementById('check-status').hidden")
        self.page.get_by_role('button', name='Check participation status').click()
        self.confirmed(False)
        self.assertEqual(len(self.mutations), 2)

    def test_double_click_sends_one_mutation(self):
        self.open_participation()
        self.check()
        self.page.get_by_role('radio', name='Register', exact=True).check()
        self.page.locator('#talk-form').evaluate('form => { form.requestSubmit(); form.requestSubmit(); }')
        self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)

    def test_changing_token_cannot_reuse_previous_users_reaction(self):
        self.reactions[4].append({'id': 102, 'content': '+1', 'user': {'id': 11, 'login': 'member'}})
        self.open_participation()
        self.check()
        self.page.get_by_role('radio', name='Unregister', exact=True).check()
        self.page.locator('#github-token').fill(OTHER_TOKEN)
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.page.get_by_role('button', name='Check token', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('identity').textContent.includes('member-two')")
        self.page.get_by_role('button', name='Submit', exact=True).click()
        self.confirmed(False)
        self.assertEqual(self.mutations[0][1].split('/')[-1], '100')
        self.assertIn(102, [record['id'] for record in self.reactions[4]])

    def test_pending_operation_requires_original_account(self):
        self.open_participation()
        self.check()
        self.lost = True
        self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('check-status').hidden")
        self.page.locator('#github-token').fill(OTHER_TOKEN)
        self.page.get_by_role('button', name='Check token', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('original account')")
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.assertEqual(len(self.mutations), 1)

    def test_pagination_matches_user_id_not_display_name(self):
        self.reactions[4] = [{'id': i + 1, 'content': '+1', 'user': {'id': 100 + i, 'login': 'member'}} for i in range(100)]
        self.reactions[4].append({'id': 999, 'content': '+1', 'user': {'id': 11, 'login': 'renamed-user'}})
        self.open_participation()
        self.check()
        self.assertIn('currently registered', self.page.locator('#participation-status').inner_text())
        self.choose('Unregister')
        self.confirmed(False)
        self.assertTrue(self.mutations[0][1].endswith('/999'))
        self.assertEqual(len(self.reactions[4]), 100)
        self.assertTrue(any('page=2' in request['url'] for request in self.requests))

    def test_registration_number_comes_from_metadata_not_meeting_counter(self):
        self.api.issues[20] = copy.deepcopy(self.api.issues[4]) | {'number': 20}
        self.api.issues[4]['labels'] = []
        config = m.load_manifest(self.api, 'meeting-4', 'main') | {'registration_number': 20}
        self.api.branch_files(m.PRIVATE, 'main')[m.manifest_path('meeting-4')] = json.dumps(config)
        m.sync_preview(self.api, maintain_private=False, include_ids=['meeting-4'])
        self.flush_pages()
        self.open_participation()
        self.check()
        self.choose('Register')
        self.confirmed(True)
        self.assertTrue(self.mutations[0][1].endswith('/issues/20/reactions'))
        self.assertEqual([record['id'] for record in self.reactions[4]], [100, 101])

    def test_wrong_registration_labels_cannot_change_a_talk_or_another_meeting(self):
        self.api.issues[4]['labels'] = ['talk', 'meeting:meeting-10']
        self.open_participation()
        self.page.locator('#github-token').fill(TOKEN)
        self.page.get_by_role('button', name='Check token', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('could not be verified')")
        self.assertEqual(self.mutations, [])

    def test_private_archive_wins_over_stale_public_page(self):
        self.open_participation()
        self.check()
        self.api.issues[4]['labels'].append('archived')
        self.choose('Register')
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('closed')")
        self.assertEqual(self.mutations, [])
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())

    def test_lock_race_never_claims_success(self):
        self.open_participation()
        self.check()
        self.lock_on_write = True
        self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
        self.assertEqual(self.page.locator('#submission-status').inner_text(), 'The participation change was not confirmed.')
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.assertEqual([record['id'] for record in self.reactions[4]], [100, 101])

    def test_expired_or_insufficient_token_never_writes_or_echoes_private_response(self):
        self.open_participation()
        for status in (401, 403, 404):
            self.auth_error = status
            self.page.locator('#github-token').fill(TOKEN)
            self.page.get_by_role('button', name='Check token', exact=True).click()
            self.page.wait_for_function("() => !document.getElementById('check-token').disabled && !document.getElementById('form-error').hidden")
            self.assertTrue(self.page.locator('#submit-participation').is_disabled())
            self.assertNotIn('Do not echo', self.page.content())
        self.assertEqual(self.mutations, [])

    def test_readable_repository_does_not_imply_token_has_issue_write_permission(self):
        self.open_participation()
        self.check()
        self.deny_mutations = True
        self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
        self.assertEqual(self.page.locator('#submission-status').inner_text(), 'The participation change was not confirmed.')
        self.assertEqual([record['id'] for record in self.reactions[4]], [100, 101])

    def test_failed_metadata_request_can_be_retried_without_identity_or_writes(self):
        self.context.route('**/prototype/index.html', lambda route: route.fulfill(status=503, body='PRIVATE ERROR CANARY'))
        self.open_participation(ready=False)
        self.page.wait_for_function("() => !document.getElementById('retry-meetings').hidden")
        self.assertTrue(self.page.locator('#github-token').is_disabled())
        self.assertNotIn('PRIVATE ERROR CANARY', self.page.content())
        self.context.unroute('**/prototype/index.html')
        self.page.get_by_role('button', name='Retry loading').click()
        self.page.wait_for_function("() => !document.getElementById('participation-fields').disabled")
        self.assertEqual(self.page.locator('#meeting-name').inner_text(), 'Demo Meeting 002')
        self.assertEqual(self.mutations, [])

    def test_hidden_archived_and_missing_context_are_disabled(self):
        m.manage_meeting(self.api, {'number': 4, 'id': 'meeting-4', 'action': 'archive'})
        self.flush_pages()
        for ident in ('meeting-4', 'meeting-999', 'legacy-20200101-000000000000', ''):
            self.open_participation(ident, ready=False)
            self.page.wait_for_function("() => !document.getElementById('form-status').textContent.startsWith('Loading')")
            self.assertTrue(self.page.locator('#github-token').is_disabled())
        self.assertEqual(self.mutations, [])

    def test_native_submit_and_no_javascript_cannot_leak_token(self):
        context = self.browser.new_context(java_script_enabled=False)
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(self.base + '/prototype/participation.html?meeting=meeting-4')
        self.assertTrue(page.locator('#github-token').is_disabled())
        self.open_participation()
        self.check()
        self.page.locator('#talk-form').evaluate('form => form.submit()')
        self.assertEqual(self.mutations, [])
        self.assertNotIn(TOKEN, self.page.url)

    def test_clear_token_removes_identity_status_and_disables_submission(self):
        self.open_participation()
        self.check()
        self.page.get_by_role('radio', name='Register', exact=True).check()
        self.page.get_by_role('button', name='Clear token', exact=True).click()
        self.assertEqual(self.page.locator('#github-token').input_value(), '')
        self.assertNotIn('currently registered', self.page.locator('#participation-status').inner_text())
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.assertEqual(self.mutations, [])


if __name__ == '__main__':
    unittest.main()
