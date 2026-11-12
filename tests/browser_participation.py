"""Read-role attendance comments through the real preview; fictitious keys only.

The modeled API deliberately treats both issued passwords as the same account.
Direct API use cannot enforce separation between people; tests document that.
"""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import unittest

from browser_talk_submission import FormBrowserFixture, TOKEN, SECOND_TOKEN, API, m, preview
from shared_member_fixtures import ALICE, BOB, attendance_body, install_retired_directory

OTHER_TOKEN = SECOND_TOKEN
MARKER = '<!-- wg13-participation '


def record(number, username='alice', credential=TOKEN, owner=11, ident='meeting-4', version=2):
    name = 'Bob Example' if username in ('bob','other-person') else 'Alice Example'
    return {'id':number, 'user':{'id':owner, 'login':'member' if owner==11 else 'other-private-user'},
            'body':attendance_body(ident,name,hashlib.sha256(credential.encode()).hexdigest(),version,BOB if name.startswith('Bob') else ALICE)}


class ParticipationBrowserTests(FormBrowserFixture):
    def test_removed_headings_and_prompt_do_not_return_after_credential_changes(self):
        self.open_participation()
        text = 'Check your credentials to see your current participation status.'
        self.assertEqual(self.page.locator('#credential-fields legend').count(),0)
        self.assertNotIn(text,self.page.locator('body').inner_text())
        self.check()
        self.assertIn('not registered',self.page.locator('#participation-status').inner_text().lower())
        self.page.locator('#github-token').fill('')
        self.assertEqual(self.page.locator('#participation-status').inner_text(),'')
        self.assertNotIn(text,self.page.locator('body').inner_text())
        self.assertTrue(self.page.locator('#participant-name').is_visible())

    def setUp(self):
        super().setUp()
        self.api.comments[4] = [
            {'id': 100, 'body': 'PRIVATE UNRELATED COMMENT', 'user': {'id': 11, 'login': 'member'}},
            record(101, 'other-person', owner=22),
        ]
        self.reactions = {4: []}
        self.mutations = []
        self.lost = False
        self.lock_on_write = False
        self.auth_error = None
        self.deny_mutations = False
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        self.public_before = copy.deepcopy(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH))
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
        self.assertIn(request.headers.get('authorization'), {'Bearer ' + TOKEN, 'Bearer ' + OTHER_TOKEN})
        for key in (TOKEN, OTHER_TOKEN):
            self.assertNotIn(key, request.url)
            self.assertNotIn(key, request.post_data or '')
        owner = {'id': 11, 'login': 'member'}  # Both issued passwords act as this Read account.
        path = url.path
        root = '/repos/' + m.PRIVATE
        if self.auth_error:
            self.json_response(route, {'message': 'PRIVATE ERROR RESPONSE'}, self.auth_error)
        elif path == '/user':
            self.json_response(route, owner)
        elif path == root:
            self.json_response(route, {'full_name': m.PRIVATE, 'permissions': {'pull': True, 'push': False, 'admin': False}})
        elif path.startswith(root + '/issues/comments/'):
            self.assertEqual(request.method, 'DELETE')
            number = int(path.rsplit('/', 1)[1])
            self.mutations.append((request.method, path, None))
            found = next(((issue, comment) for issue, comments in self.api.comments.items() for comment in comments if comment.get('id') == number), None)
            if not found:
                self.json_response(route, {}, 404)
                return
            issue_number, comment = found
            # Read members can delete comments authored by their own account.
            # There is deliberately no server-side per-person ownership.
            if self.deny_mutations or comment['user']['id'] != owner['id'] or self.api.issues[issue_number].get('locked'):
                self.json_response(route, {}, 403)
                return
            self.api.comments[issue_number].remove(comment)
            if self.lost: route.abort('failed')
            else: route.fulfill(status=204, headers={'Access-Control-Allow-Origin': '*'})
        elif path.startswith(root + '/issues/'):
            tail = path[len(root + '/issues/'):].split('/')
            number = int(tail[0])
            issue = self.api.issues.get(number)
            if issue is None:
                self.json_response(route, {}, 404)
                return
            if len(tail) == 1:
                self.json_response(route, self.api.issue_record(issue))
            elif tail[1] == 'reactions':
                self.assertEqual(request.method, 'GET')  # Existing reactions are never mutated.
                self.assertEqual(parse_qs(url.query).get('content'), ['+1'])
                self.json_response(route, self.reactions.get(number, [])[:1])
            elif tail[1] == 'comments':
                comments = self.api.comments.setdefault(number, [])
                if request.method == 'GET':
                    query = parse_qs(url.query)
                    page = int(query.get('page', ['1'])[0])
                    self.json_response(route, comments[(page - 1) * 100:page * 100])
                elif request.method == 'POST':
                    self.mutations.append((request.method, path, request.post_data_json))
                    if self.lock_on_write: issue['locked'] = True
                    if self.deny_mutations or issue.get('locked'):
                        self.json_response(route, {}, 403)
                        return
                    self.assertEqual(set(request.post_data_json), {'body'})
                    number_id = max([2000] + [c.get('id', 0) for rows in self.api.comments.values() for c in rows]) + 1
                    comment = {'id': number_id, 'body': request.post_data_json['body'], 'user': owner}
                    comments.append(comment)
                    if self.lost: route.abort('failed')
                    else: self.json_response(route, comment, 201)
                else: raise AssertionError('Unexpected comment operation')
            else: raise AssertionError('Unexpected Issue subresource')
        else: raise AssertionError('Unexpected API route: ' + path)

    def open_participation(self, ident='meeting-4', ready=True):
        self.page.goto(self.base + '/prototype/participation.html?meeting=' + ident)
        if ready:
            self.page.wait_for_function("() => !document.getElementById('participation-fields').disabled")
            self.page.locator('#participant-name').fill('Alice Example')

    def check(self, credential=TOKEN, name='Alice Example'):
        self.page.locator('#participant-name').fill(name)
        self.page.locator('#github-token').fill(credential)
        self.page.get_by_role('button', name='Check credentials', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('identity').textContent === 'Credentials accepted.'")

    def choose(self, action):
        self.page.get_by_role('radio', name=action, exact=True).check()
        self.page.get_by_role('button', name='Submit', exact=True).click()

    def confirmed(self, registered):
        expected = 'Registration confirmed.' if registered else 'Unregistration confirmed.'
        self.page.wait_for_function('(text) => document.getElementById("submission-status").textContent === text', arg=expected)

    def test_register_unregister_idempotence_privacy_and_read_role(self):
        saved = copy.deepcopy(self.api.comments[4])
        self.page.goto(self.base + '/prototype/meetings/meeting-4/')
        self.page.get_by_role('link', name='Participation', exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('participation-fields').disabled")
        self.check()
        self.assertIn('not registered', self.page.locator('#participation-status').inner_text())
        self.choose('Register'); self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)
        data = json.loads(self.api.comments[4][-1]['body'].split(MARKER)[1][:-4])
        self.assertNotIn('member_id',data)
        self.assertEqual(data['schema_version'],3)
        self.assertEqual(data['name'], 'Alice Example')
        self.assertEqual(data['credential_fingerprint'], hashlib.sha256(TOKEN.encode()).hexdigest())
        self.choose('Register'); self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)
        self.choose('Unregister'); self.confirmed(False)
        self.choose('Unregister'); self.confirmed(False)
        self.assertEqual([method for method, _, _ in self.mutations], ['POST', 'DELETE'])
        self.assertEqual(self.api.comments[4], saved)
        self.assertEqual(self.api.permissions['member'], 'read')
        self.assertEqual(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH), self.public_before)
        self.assertNotIn('PRIVATE UNRELATED COMMENT', self.page.content())
        self.assertNotIn(TOKEN, self.page.content())
        self.assertEqual(self.page.evaluate('[localStorage.length, sessionStorage.length]'), [0, 0])
        self.assertFalse(self.errors)

    def test_two_names_using_the_same_password_remain_distinct_in_normal_form_use(self):
        self.open_participation(); self.check(); self.choose('Register'); self.confirmed(True)
        alice = copy.deepcopy(self.api.comments[4][-1])
        self.check(TOKEN,'Bob Example'); self.choose('Register'); self.confirmed(True)
        bob = copy.deepcopy(self.api.comments[4][-1])
        self.assertEqual(alice['user'], bob['user'])
        self.assertNotEqual(alice['body'], bob['body'])
        self.check(TOKEN); self.choose('Unregister'); self.confirmed(False)
        self.assertIn(bob, self.api.comments[4])
        self.assertNotIn(alice, self.api.comments[4])

    def test_a_replacement_password_for_same_person_can_remove_existing_registration(self):
        self.api.comments[4].append(record(999))
        self.open_participation(); self.check(OTHER_TOKEN)
        self.assertIn('currently registered', self.page.locator('#participation-status').inner_text())
        self.choose('Unregister'); self.confirmed(False)
        self.assertTrue(self.mutations[0][1].endswith('/999'))

    def test_legacy_reactions_remain_untouched_and_are_flagged_for_reconciliation(self):
        self.reactions[4] = [{'id': 91, 'content': '+1', 'user': {'id': 11, 'login': 'member'}}]
        self.open_participation(); self.check()
        self.assertTrue(self.page.locator('#legacy-attendance').is_visible())
        self.assertIn('organizer confirmation', self.page.locator('#participation-status').inner_text())
        self.choose('Register'); self.confirmed(True)
        self.choose('Unregister'); self.confirmed(False)
        self.assertEqual(len(self.reactions[4]), 1)
        self.assertFalse(any('/reactions' in path for _, path, _ in self.mutations))

    def test_lost_register_and_delete_responses_are_recovered_without_repeating_writes(self):
        self.open_participation(); self.check(); self.lost = True
        for action, desired in [('Register', True), ('Unregister', False)]:
            self.choose(action)
            self.page.wait_for_function("() => !document.getElementById('check-status').hidden")
            before = len(self.mutations)
            self.page.get_by_role('button', name='Check participation status').click()
            self.confirmed(desired)
            self.assertEqual(len(self.mutations), before)
        self.assertEqual(len(self.mutations), 2)

    def test_double_click_sends_one_comment(self):
        self.open_participation(); self.check()
        self.page.get_by_role('radio', name='Register', exact=True).check()
        self.page.locator('#talk-form').evaluate('form => { form.requestSubmit(); form.requestSubmit(); }')
        self.confirmed(True)
        self.assertEqual(len(self.mutations), 1)

    def test_pending_operation_requires_original_name_and_password_even_for_same_account(self):
        self.open_participation(); self.check(); self.lost = True
        self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('check-status').hidden")
        self.page.locator('#github-token').fill(OTHER_TOKEN)
        self.page.get_by_role('button', name='Check credentials', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('original name and password')")
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.assertEqual(len(self.mutations), 1)
        self.check(); self.page.get_by_role('button', name='Check participation status').click(); self.confirmed(True)

    def test_pagination_ignores_unrelated_comments_and_same_label_by_different_author(self):
        self.api.comments[4] = [{'id': n + 1, 'body': 'PRIVATE UNRELATED', 'user': {'id': 11}} for n in range(100)]
        self.api.comments[4] += [record(998, owner=22), record(999)]
        self.open_participation(); self.check(); self.choose('Unregister'); self.confirmed(False)
        self.assertTrue(self.mutations[0][1].endswith('/999'))
        self.assertEqual(len(self.api.comments[4]), 101)
        self.assertTrue(any('page=2' in r['url'] for r in self.requests))

    def test_malformed_or_wrong_meeting_records_are_not_deleted(self):
        bad = record(990); bad['body'] = bad['body'].replace('"schema_version":2', '"schema_version":9')
        wrong = record(991, ident='meeting-10')
        invalid_hash = record(992); invalid_hash['body'] = invalid_hash['body'].replace(hashlib.sha256(TOKEN.encode()).hexdigest(), 'not-a-fingerprint')
        self.api.comments[4] += [bad, wrong, invalid_hash]
        saved = copy.deepcopy(self.api.comments[4])
        self.open_participation(); self.check(); self.choose('Unregister'); self.confirmed(False)
        self.assertEqual(self.api.comments[4], saved)
        self.assertFalse(self.mutations)

    def test_duplicate_participant_comments_require_organizer_review(self):
        self.api.comments[4] += [record(998), record(999)]
        self.open_participation()
        self.page.locator('#github-token').fill(TOKEN)
        self.page.get_by_role('button', name='Check credentials', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('More than one')")
        self.assertFalse(self.mutations)
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())

    def test_colliding_legacy_names_with_different_person_ids_are_preserved_for_review(self):
        self.api.comments[4] += [record(998),record(999)]
        self.api.comments[4][-1]['body'] = attendance_body('meeting-4','ALICE EXAMPLE',version=2,member_id=BOB)
        saved = copy.deepcopy(self.api.comments[4])
        self.open_participation(); self.page.locator('#github-token').fill(TOKEN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('More than one')")
        self.assertEqual(self.api.comments[4],saved); self.assertFalse(self.mutations)

    def test_name_normalization_prevents_duplicate_registration_and_allows_unregister(self):
        self.open_participation(); self.check(TOKEN,'  Alice   Example ')
        self.choose('Register'); self.confirmed(True)
        self.check(TOKEN,'ALICE example'); self.choose('Register'); self.confirmed(True)
        self.assertEqual(len(self.mutations),1)
        self.choose('Unregister'); self.confirmed(False)
        self.assertEqual(len(self.mutations),2)

    def test_retired_directory_is_not_consulted_and_legacy_username_records_stay_readable(self):
        install_retired_directory(self.api)
        saved = copy.deepcopy(self.api.issues[900])
        self.api.comments[4].append({'id':999,'user':{'id':11,'login':'member'},'body':attendance_body('meeting-4','old-alice',version=1)})
        self.open_participation(); self.check(OTHER_TOKEN,'OLD-ALICE'); self.choose('Unregister'); self.confirmed(False)
        self.assertEqual(self.api.issues[900],saved)
        self.assertFalse(any('participant-directory' in r['url'] or '/issues/900' in r['url'] for r in self.requests))
        self.assertTrue(self.mutations[0][1].endswith('/999'))

    def test_name_required_and_changing_it_invalidates_checked_access(self):
        self.open_participation(); self.page.locator('#participant-name').fill('')
        self.page.locator('#github-token').fill(TOKEN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Enter your name')")
        self.assertFalse(self.mutations)
        self.check(); self.page.locator('#participant-name').fill('Bob Example')
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())

    def test_silent_name_autofill_is_detected_before_a_mutation(self):
        self.open_participation(); self.check()
        self.page.get_by_role('radio',name='Register',exact=True).check()
        self.page.locator('#participant-name').evaluate("node => {node.value='Bob Example';}")
        self.page.get_by_role('button',name='Submit',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Check your credentials')")
        self.assertFalse(self.mutations)

    def test_accents_and_html_delimiters_are_private_plain_text_and_fingerprint_is_hidden(self):
        self.open_participation(); self.check(TOKEN,'Rene\u0301 <Example> --> & Co.')
        self.choose('Register'); self.confirmed(True)
        body = self.api.comments[4][-1]['body']
        self.assertIn('René',body)
        self.assertNotIn('<Example>',body)
        self.assertNotIn(hashlib.sha256(TOKEN.encode()).hexdigest(),self.page.locator('body').inner_text())
        self.choose('Unregister'); self.confirmed(False)

    def test_shared_account_direct_api_access_is_not_per_person_authorization(self):
        self.api.comments[4].append(record(999, 'bob', OTHER_TOKEN))
        self.open_participation(); self.check()
        self.choose('Unregister'); self.confirmed(False)
        self.assertFalse(self.mutations)  # Normal form targets Alice, not Bob.
        status = self.page.evaluate("async ({url,key}) => (await fetch(url, {method:'DELETE',headers:{Authorization:'Bearer '+key,'X-GitHub-Api-Version':'2022-11-28'}})).status", {'url':API+'/repos/'+m.PRIVATE+'/issues/comments/999','key':TOKEN})
        self.assertEqual(status,204)  # Direct API still sees the shared author.
        self.assertTrue(self.mutations[-1][1].endswith('/999'))

    def test_registration_number_comes_from_metadata_not_meeting_counter(self):
        self.api.issues[20] = copy.deepcopy(self.api.issues[4]) | {'number': 20}
        self.api.issues[4]['labels'] = []
        config = m.load_manifest(self.api, 'meeting-4', 'main') | {'registration_number': 20}
        self.api.branch_files(m.PRIVATE, 'main')[m.manifest_path('meeting-4')] = json.dumps(config)
        m.sync_preview(self.api, maintain_private=False, include_ids=['meeting-4']); self.flush_pages()
        self.open_participation(); self.check(); self.choose('Register'); self.confirmed(True)
        self.assertTrue(self.mutations[0][1].endswith('/issues/20/comments'))
        self.assertEqual(len(self.api.comments[4]), 2)

    def test_wrong_registration_labels_prevent_changes(self):
        self.api.issues[4]['labels'] = ['talk', 'meeting:meeting-10']
        self.open_participation()
        self.page.locator('#github-token').fill(TOKEN)
        self.page.get_by_role('button', name='Check credentials', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('could not be verified')")
        self.assertFalse(self.mutations)

    def test_private_archive_wins_over_stale_public_page(self):
        self.open_participation(); self.check(); self.api.issues[4]['labels'].append('archived')
        self.choose('Register')
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('closed')")
        self.assertFalse(self.mutations)
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())

    def test_lock_race_never_claims_success(self):
        self.open_participation(); self.check(); self.lock_on_write = True; self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
        self.assertEqual(self.page.locator('#submission-status').inner_text(), 'The participation change was not confirmed.')
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.assertEqual(len(self.api.comments[4]), 2)

    def test_expired_and_insufficient_credentials_never_echo_private_responses(self):
        self.open_participation()
        for status in (401, 403, 404):
            self.auth_error = status
            self.page.locator('#github-token').fill(TOKEN)
            self.page.get_by_role('button', name='Check credentials', exact=True).click()
            self.page.wait_for_function("() => !document.getElementById('check-token').disabled && !document.getElementById('form-error').hidden")
            self.assertTrue(self.page.locator('#submit-participation').is_disabled())
            self.assertNotIn('PRIVATE ERROR RESPONSE', self.page.content())
        self.assertFalse(self.mutations)

    def test_read_access_does_not_prove_write_scope(self):
        self.open_participation(); self.check(); self.deny_mutations = True; self.choose('Register')
        self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
        self.assertEqual(self.page.locator('#submission-status').inner_text(), 'The participation change was not confirmed.')
        self.assertEqual(len(self.api.comments[4]), 2)

    def test_old_preview_allowlist_and_desktop_mobile_layout(self):
        original = preview.resource_path
        def old_allowlist(url):
            path = original(url)
            if path.endswith('.js') and not path.endswith('/meetings-list.js'): raise FileNotFoundError
            return path
        scripts = []
        self.page.on('request', lambda r: scripts.append(r.url) if r.url.endswith('.js') else None)
        with patch.object(preview, 'resource_path', side_effect=old_allowlist):
            for width in (1100, 375, 320):
                self.page.set_viewport_size({'width': width, 'height': 950}); self.open_participation()
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.check(); self.choose('Register'); self.confirmed(True)
        self.assertFalse(scripts)
        text = self.page.locator('body').inner_text()
        for unwanted in ('GitHub', 'token', 'repository', 'Personal access', 'Clear token'):
            self.assertNotIn(unwanted, text)

    def test_metadata_failure_can_be_retried_without_writes(self):
        self.context.route('**/prototype/index.html', lambda route: route.fulfill(status=503, body='PRIVATE ERROR CANARY'))
        self.open_participation(ready=False)
        self.page.wait_for_function("() => !document.getElementById('retry-meetings').hidden")
        self.assertTrue(self.page.locator('#github-token').is_disabled())
        self.assertNotIn('PRIVATE ERROR CANARY', self.page.content())
        self.context.unroute('**/prototype/index.html'); self.page.get_by_role('button', name='Retry loading').click()
        self.page.wait_for_function("() => !document.getElementById('participation-fields').disabled")
        self.assertFalse(self.mutations)

    def test_archived_hidden_and_invalid_contexts_are_disabled(self):
        m.manage_meeting(self.api, {'number': 4, 'id': 'meeting-4', 'action': 'archive'}); self.flush_pages()
        for ident in ('meeting-4', 'meeting-999', 'legacy-20200101-000000000000', ''):
            self.open_participation(ident, ready=False)
            self.page.wait_for_function("() => !document.getElementById('form-status').textContent.startsWith('Loading')")
            self.assertTrue(self.page.locator('#github-token').is_disabled())
        self.assertFalse(self.mutations)

    def test_no_javascript_native_submit_and_page_exit_do_not_leak_credentials(self):
        context = self.browser.new_context(java_script_enabled=False); self.addCleanup(context.close)
        page = context.new_page(); page.goto(self.base + '/prototype/participation.html?meeting=meeting-4')
        self.assertTrue(page.locator('#github-token').is_disabled())
        self.open_participation(); self.check()
        self.page.locator('#talk-form').evaluate('form => form.submit()')
        self.assertFalse(self.mutations)
        self.assertNotIn(TOKEN, self.page.url)
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        self.assertEqual(self.page.locator('#github-token').input_value(), '')
        self.assertEqual(self.page.locator('#participant-name').input_value(), '')
        self.assertTrue(self.page.locator('#submit-participation').is_disabled())
        self.assertEqual(self.page.locator('#clear-token').count(), 0)


if __name__ == '__main__':
    unittest.main()
