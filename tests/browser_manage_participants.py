"""Admin form -> trusted directory controller, using fictitious credentials only."""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import patch

from browser_talk_submission import FormBrowserFixture, TOKEN, SECOND_TOKEN, API, m
from test_participant_directory import ALICE, BOB, controller, D, install_directory

ADMIN_TOKEN = 'github_pat_ADMIN_FICTITIOUS_TEST_ONLY'
NEW_TOKEN = 'github_pat_NEW_FICTITIOUS_TEST_ONLY'


class AdminBrowserTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        source = Path(__file__).resolve().parents[1] / 'prototype/manage-participants.html'
        (self.directory / 'prototype/manage-participants.html').write_bytes(source.read_bytes())
        self.mode = 'automatic'
        self.lost = False
        self.retry_calls = 0
        self.controller_errors = []
        self.root_before = copy.deepcopy(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH))

    def route(self, route):
        request = route.request
        if not request.url.startswith(API + '/'):
            return super().route(route)
        url = urlsplit(request.url)
        self.requests.append({'method': request.method, 'url': request.url,
                              'headers': request.headers, 'body': request.post_data})
        if request.method == 'OPTIONS':
            route.fulfill(status=204, headers={'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST',
                'Access-Control-Allow-Headers': 'authorization,content-type,x-github-api-version'})
            return
        header = request.headers.get('authorization')
        self.assertIn(header, {'Bearer ' + ADMIN_TOKEN, 'Bearer ' + TOKEN})
        admin = header == 'Bearer ' + ADMIN_TOKEN
        owner = {'id': 1 if admin else 11, 'login': 'manager' if admin else 'member', 'type': 'User'}
        for key in (ADMIN_TOKEN, TOKEN, SECOND_TOKEN, NEW_TOKEN):
            self.assertNotIn(key, request.url)
            self.assertNotIn(key, request.post_data or '')
        root = '/repos/' + m.PRIVATE
        path = url.path
        if path == '/user':
            self.json_response(route, owner)
        elif path == root:
            self.json_response(route, {'full_name': m.PRIVATE, 'permissions': {'pull': True}})
        elif path == root + '/collaborators/' + owner['login'] + '/permission':
            self.json_response(route, {'permission': 'admin' if admin else 'read'})
        elif path == root + '/labels/' + D.LABEL:
            self.json_response(route, self.api.labels.get(D.LABEL, {}), 200 if D.LABEL in self.api.labels else 404)
        elif path == root + '/issues' and request.method == 'POST':
            self.assertTrue(admin)
            self.assertEqual(self.page.locator('#issued-token').input_value(), '')
            self.assertEqual(set(request.post_data_json), {'title', 'body'})
            self.posts += 1
            number = max(self.api.issues) + 1
            self.last_number = number
            self.api.issues[number] = {'number': number, **request.post_data_json, 'user':owner,
                                      'state':'open', 'locked':False, 'labels':[], 'created_at':'2026-11-12T12:00:00Z'}
            if self.mode == 'automatic': self.process_admin(number)
            if self.lost: route.abort('failed')
            else: self.json_response(route, {'number':number}, 201)
        elif path == root + '/issues':
            query = parse_qs(url.query)
            self.assertEqual(query['creator'], [owner['login']])
            self.json_response(route, [self.api.issue_record(issue) for issue in self.api.issues.values()
                                      if issue.get('user', {}).get('login') == owner['login']])
        elif path.startswith(root + '/issues/'):
            tail = path[len(root + '/issues/'):].split('/')
            number = int(tail[0])
            if len(tail) == 1:
                self.json_response(route, self.api.issue_record(self.api.issues[number]))
            elif tail[1] == 'comments':
                if request.method == 'POST':
                    self.assertEqual(request.post_data_json, {'body':'/retry-participants'})
                    self.retry_calls += 1
                    self.process_admin(number, 'issue_comment')
                    self.json_response(route, {'id':100000}, 201)
                else:
                    page = int(parse_qs(url.query).get('page', ['1'])[0])
                    self.json_response(route, self.api.comments.get(number, [])[(page-1)*100:page*100])
            else: raise AssertionError('Unexpected Issue subresource')
        else: raise AssertionError('Unexpected administration API route: ' + path)

    def process_admin(self, number, event_name='issues'):
        event = {'repository': {'full_name': m.PRIVATE}, 'sender': {'login':'manager'},
                 'action':'opened', 'issue':{'number':number}}
        if event_name == 'issue_comment': event['comment'] = {'body':'/retry-participants'}
        try: controller.run(self.api, event, event_name)
        except (D.DirectoryError, m.SetupError) as failure:
            self.controller_errors.append(str(failure))

    def open_admin(self, credential=ADMIN_TOKEN):
        self.page.goto(self.base + '/prototype/manage-participants.html')
        self.page.locator('#admin-token').fill(credential)
        self.page.get_by_role('button', name='Check administrator access').click()

    def checked(self):
        self.page.wait_for_function("() => document.getElementById('admin-identity').textContent === 'Administrator access confirmed.'")

    def save(self, action, name=None, credential=None, person=ALICE):
        self.page.locator('#operation').select_option(action)
        if action != 'add': self.page.locator('#person').select_option(person)
        if name is not None: self.page.locator('#person-name').fill(name)
        if credential is not None: self.page.locator('#issued-token').fill(credential)
        self.page.get_by_role('button', name='Save participant', exact=True).click()

    def confirmed(self):
        self.page.wait_for_function("() => document.getElementById('update-status').textContent === 'Participant update confirmed.'")

    def next_update(self):
        self.page.get_by_role('button', name='Another update', exact=True).click()

    def test_add_bootstraps_once_and_never_transmits_issued_password(self):
        self.api.issues.pop(900); self.api.labels.pop(D.LABEL)
        self.open_admin(); self.checked()
        self.assertIn('first participant', self.page.locator('#directory-status').inner_text())
        self.save('add', 'Alice Example', TOKEN); self.confirmed()
        root, data = D.load(self.api)
        self.assertEqual(len(data['members']), 1)
        self.assertEqual(data['members'][0]['name'], 'Alice Example')
        self.assertTrue(root['locked']); self.assertTrue(D.is_bot(root))
        self.assertEqual(self.page.locator('#participant-list').inner_text(), 'Alice Example')
        stored = json.dumps({'issues':self.api.issues, 'comments':self.api.comments, 'calls':self.api.calls})
        for value in (TOKEN, ADMIN_TOKEN): self.assertNotIn(value, stored)
        self.assertNotIn(hashlib.sha256(TOKEN.encode()).hexdigest(), self.page.locator('body').inner_text())
        self.assertEqual(self.page.evaluate('[localStorage.length, sessionStorage.length]'), [0,0])
        self.assertEqual(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH), self.root_before)
        self.assertEqual(self.posts, 1); self.assertFalse(self.errors)

    def test_read_credential_cannot_open_administration(self):
        self.open_admin(TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertTrue(self.page.locator('#management-fields').evaluate('node => node.disabled'))
        self.assertTrue(self.page.locator('#save-participant').is_disabled())
        self.assertEqual(self.posts, 0)

    def test_rename_reconciles_private_names_then_replace_preserves_person(self):
        from browser_participation import record
        self.api.comments[4] = [record(88)]
        original_author = copy.deepcopy(self.api.comments[4][0]['user'])
        self.open_admin(); self.checked()
        self.save('rename', 'Alice Corrected'); self.confirmed()
        self.assertIn('Yes — Alice Corrected', self.api.comments[4][0]['body'])
        self.assertEqual(self.api.comments[4][0]['user'], original_author)
        self.next_update(); self.save('replace', credential=NEW_TOKEN); self.confirmed()
        person = D.lookup(D.load(self.api)[1], hashlib.sha256(NEW_TOKEN.encode()).hexdigest())
        self.assertEqual(person['member_id'], ALICE)
        self.assertEqual(person['name'], 'Alice Corrected')
        self.assertFalse(D.lookup(D.load(self.api)[1], hashlib.sha256(TOKEN.encode()).hexdigest(), active=False)['active'])
        self.next_update(); self.save('disable'); self.confirmed()
        self.assertIn('Alice Corrected (inactive)', self.page.locator('#participant-list').inner_text())
        self.assertIn('Yes — Alice Corrected', self.api.comments[4][0]['body'])

    def test_unicode_name_and_comment_delimiters_render_as_text(self):
        name = 'Zoë Example --> <img src=x onerror=alert(1)> & Co.'
        self.open_admin(); self.checked(); self.save('rename', name); self.confirmed()
        self.assertIn(name, self.page.locator('#participant-list').inner_text())
        self.assertEqual(self.page.locator('#participant-list img').count(), 0)
        self.assertFalse(self.errors)

    def test_duplicate_fingerprint_fails_without_reassigning_existing_person(self):
        self.open_admin(); self.checked(); self.save('add', 'Imposter Example', TOKEN)
        self.page.wait_for_function("() => document.getElementById('update-status').textContent.includes('needs administrator attention')")
        data = D.load(self.api)[1]
        self.assertEqual(D.lookup(data, hashlib.sha256(TOKEN.encode()).hexdigest())['member_id'], ALICE)
        self.assertEqual(len(data['members']), 2)

    def test_issued_and_admin_passwords_cannot_be_saved_as_names(self):
        self.open_admin(); self.checked()
        for name in (TOKEN, ADMIN_TOKEN):
            self.save('add', name, NEW_TOKEN)
            self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('never enter a password')")
            self.assertEqual(self.page.locator('#issued-token').input_value(), '')
        self.save('add', 'Carol Example', ADMIN_TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('not the administrator')")
        self.assertEqual(self.posts, 0)

    def test_lost_response_recovers_by_request_id_without_second_post(self):
        self.lost = True
        self.open_admin(); self.checked(); self.save('add', 'Carol Example', NEW_TOKEN); self.confirmed()
        self.assertEqual(self.posts, 1)
        self.assertEqual(len(D.load(self.api)[1]['members']), 3)

    def test_explicit_retry_reconciles_original_request_without_duplicate_person(self):
        self.mode = 'fail'
        self.open_admin(); self.checked()
        self.save('add', 'Carol Example', NEW_TOKEN)
        self.page.wait_for_function("() => document.getElementById('update-status').textContent.startsWith('Update submitted.')")
        with patch.object(D, 'reconcile_records', side_effect=m.SetupError('GitHub returned HTTP 503.')):
            self.process_admin(self.last_number)
        self.page.get_by_role('button', name='Check update status').click()
        self.page.wait_for_function("() => !document.getElementById('retry-request').hidden")
        self.mode = 'automatic'
        self.page.get_by_role('button', name='Retry update', exact=True).click()
        self.page.get_by_role('button', name='Check update status').click(); self.confirmed()
        self.assertEqual(self.posts, 1); self.assertEqual(self.retry_calls, 1)
        self.assertEqual(len(D.load(self.api)[1]['members']), 3)

    def test_member_forged_status_cannot_report_success(self):
        self.mode = 'pending'
        self.open_admin(); self.checked(); self.save('rename', 'Alice Corrected')
        self.page.wait_for_function("() => document.getElementById('update-status').textContent.startsWith('Update submitted.')")
        data = D.parse_request(self.api.issues[self.last_number])
        value = {'schema_version':1, 'request_id':data['request_id'], 'state':'complete','member_id':ALICE,'revision':1}
        self.api.comments[self.last_number] = [{'id':88,'body':D.STATUS_MARKER + json.dumps(value) + ' -->', 'user':{'login':'member','type':'User'}}]
        self.page.get_by_role('button', name='Check update status').click()
        self.assertTrue(self.page.get_by_role('button', name='Another update').is_hidden())
        self.assertNotIn('confirmed', self.page.locator('#update-status').inner_text())

    def test_independent_or_fake_directory_is_rejected(self):
        original = copy.deepcopy(self.api.issues[900])
        for change in ({'user':{'login':'member','type':'User'}}, {'body':original['body'] + '\nindependent edit'}):
            self.api.issues[900] = original | change
            self.open_admin()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertTrue(self.page.locator('#save-participant').is_disabled())
        self.assertEqual(self.posts, 0)

    def test_password_change_invalidates_admin_and_pagehide_clears_fields(self):
        self.open_admin(); self.checked()
        self.page.locator('#issued-token').fill(TOKEN)
        self.page.locator('#admin-token').fill('changed')
        self.assertTrue(self.page.locator('#save-participant').is_disabled())
        self.page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        for field in ('admin-token','issued-token','person-name'):
            self.assertEqual(self.page.locator('#' + field).input_value(), '')
        self.assertEqual(self.page.locator('#participant-list').inner_text(), '')
        self.assertFalse(self.requests and any(request['method'] == 'POST' for request in self.requests))

    def test_mobile_layout_and_keyboard_access(self):
        self.page.set_viewport_size({'width':390,'height':844})
        self.open_admin(); self.checked()
        self.assertTrue(self.page.locator('#issued-token').is_visible())
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        self.page.locator('#person-name').focus(); self.page.keyboard.press('Tab')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'issued-token')
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
