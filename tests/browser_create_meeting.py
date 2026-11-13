"""Website form -> trusted meeting workflow -> preview, fictitious data only."""
import copy
import json
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import patch

from browser_talk_submission import FormBrowserFixture, TOKEN, API, m, ROOT
ADMIN_TOKEN = 'github_pat_ADMIN_FICTITIOUS_TEST_ONLY'


class MeetingCreationBrowserTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        for name in ('prototype/create-meeting.html','index.html','members/index.html'):
            target = self.directory / name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        # Exercise the real navigation, with only fictitious generated meetings.
        files = self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
        start, end = '<!-- generated-meetings:start -->','<!-- generated-meetings:end -->'
        region = files['prototype/index.html'].split(start)[1].split(end)[0]
        actual = (ROOT / 'prototype/index.html').read_text()
        files['prototype/index.html'] = actual.split(start)[0] + start + region + end + actual.split(end)[1]
        self.flush_pages()
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        self.mode = 'automatic'
        self.lost = False
        self.auth_status = None
        self.deny_post = False
        self.workflow_errors = []

    def route(self, route):
        request = route.request
        if not request.url.startswith(API + '/'):
            return super().route(route)
        url = urlsplit(request.url)
        self.requests.append({'method':request.method,'url':request.url,'headers':request.headers,'body':request.post_data})
        if request.method == 'OPTIONS':
            route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET, POST',
                'Access-Control-Allow-Headers':'authorization,content-type,x-github-api-version'})
            return
        header = request.headers.get('authorization')
        self.assertIn(header, {'Bearer ' + ADMIN_TOKEN,'Bearer ' + TOKEN})
        owner = {'login':'manager' if header == 'Bearer ' + ADMIN_TOKEN else 'member','id':1 if header == 'Bearer ' + ADMIN_TOKEN else 11,'type':'User'}
        for key in (ADMIN_TOKEN,TOKEN):
            self.assertNotIn(key,request.url); self.assertNotIn(key,request.post_data or '')
        root = '/repos/' + m.PRIVATE
        path = url.path
        if self.auth_status:
            self.json_response(route, {'message':'PRIVATE SERVICE ERROR CANARY'}, self.auth_status)
        elif path == '/user': self.json_response(route,owner)
        elif path == root: self.json_response(route,{'full_name':m.PRIVATE,'permissions':{'pull':True}})
        elif path == root + '/collaborators/' + owner['login'] + '/permission':
            self.json_response(route,{'permission':self.api.permissions[owner['login']]})
        elif path == root + '/issues' and request.method == 'POST':
            self.posts += 1
            self.assertEqual(set(request.post_data_json), {'title','body'})
            if self.deny_post:
                self.json_response(route, {'message':'PRIVATE DENIAL CANARY'},403); return
            number = max(self.api.issues) + 1
            self.last_number = number
            self.api.issues[number] = {'number':number,**request.post_data_json,'user':owner,'labels':[],
                'state':'open','locked':False,'created_at':'2026-11-12T12:00:00Z'}
            if self.mode != 'pending': self.process_meeting(number)
            if self.lost: route.abort('failed')
            else: self.json_response(route,{'number':number},201)
        elif path == root + '/issues':
            creator = parse_qs(url.query)['creator'][0]
            self.json_response(route,[self.api.issue_record(issue) for issue in self.api.issues.values() if issue.get('user',{}).get('login') == creator])
        elif path.startswith(root + '/issues/'):
            tail = path[len(root + '/issues/'):].split('/')
            number = int(tail[0])
            self.assertEqual(request.method,'GET')
            if len(tail) == 1: self.json_response(route,self.api.issue_record(self.api.issues[number]))
            elif tail[1] == 'comments':
                rows = copy.deepcopy(self.api.comments.get(number,[]))
                for row in rows:
                    if not row['body'].startswith(m.MEETING_STATUS): continue
                    data = json.loads(row['body'][len(m.MEETING_STATUS):row['body'].index(' -->')])
                    if 'revision' in data: data['revision'] = 'b'*40  # REST fixture uses symbolic commit IDs.
                    row['body'] = m.MEETING_STATUS + json.dumps(data) + ' -->\nStatus'
                page = int(parse_qs(url.query).get('page',['1'])[0])
                self.json_response(route,rows[(page-1)*100:page*100])
            else: raise AssertionError('Unexpected Issue subresource')
        else: raise AssertionError('Unexpected website API path: ' + path)

    def process_meeting(self, number, edited=False):
        event = {'repository':{'full_name':m.PRIVATE},'sender':{'login':'manager'},
                 'action':'edited' if edited else 'opened','issue':{'number':number}}
        try:
            request = m.authorize(self.api,event,'issues')
            if self.mode == 'fail':
                with patch.object(m,'verify_synced_meetings',side_effect=m.SetupError('Fictitious verification failure')):
                    m.prepare(self.api,request,reader=self.api)
            else: m.prepare(self.api,request,reader=self.api)
        except m.SetupError as failure:
            self.workflow_errors.append(str(failure))
            m.meeting_status(self.api,self.api.issues[number],'needs-attention')
        self.flush_pages()

    def open_creation(self, credential=ADMIN_TOKEN, check=True):
        self.page.goto(self.base + '/prototype/create-meeting.html')
        if check:
            self.page.locator('#admin-token').fill(credential)
            self.page.get_by_role('button',name='Check credentials',exact=True).click()

    def checked(self):
        self.page.wait_for_function("() => document.getElementById('admin-identity').textContent === 'Administrator access confirmed.'")

    def fill_meeting(self, name='Fictitious website meeting', start='1-3-28', end='4-3-28', location='Madrid', description='A public description.\n\nAnother paragraph.'):
        for selector, value in [('meeting-name',name),('start-date',start),('end-date',end),('location',location),('description',description)]:
            self.page.locator('#' + selector).fill(value)

    def create(self): self.page.get_by_role('button',name='Create meeting',exact=True).click()

    def ready(self): self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting ready.')")

    def test_navigation_creation_and_correct_public_meeting_after_sync(self):
        self.page.goto(self.base + '/')
        self.assertEqual(self.page.get_by_role('link',name='Manage Participants',exact=True).count(),0)
        self.page.get_by_role('navigation').get_by_role('link',name='Meetings',exact=True).click()
        self.page.get_by_role('link',name='Create meeting',exact=True).click()
        self.assertTrue(self.page.url.endswith('/prototype/create-meeting.html'))
        self.page.locator('#admin-token').fill(ADMIN_TOKEN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click(); self.checked()
        before = set(self.api.issues)
        self.fill_meeting(); self.create(); self.ready()
        number = self.last_number
        self.assertEqual(set(self.api.issues) - before, {number})
        self.assertEqual(self.api.issues[number]['title'],f'[meeting {number}] Fictitious website meeting')
        self.assertEqual(self.posts,1)
        self.assertFalse(self.workflow_errors)
        self.page.get_by_role('link',name='Open meeting',exact=True).click()
        self.assertEqual(self.page.locator('h1').inner_text(),'Fictitious website meeting')
        self.assertIn('01-03-2028',self.page.locator('.meeting-summary').inner_text())
        self.assertIn('04-03-2028',self.page.locator('.meeting-summary').inner_text())
        self.assertIn('Another paragraph.',self.page.locator('.meeting-description').inner_text())
        self.assertTrue(self.page.get_by_role('link',name='Add talk',exact=True).is_visible())
        self.assertTrue(self.page.get_by_role('link',name='Participation',exact=True).is_visible())
        self.assertFalse(self.errors); self.assertFalse(self.external)

    def test_administrator_needs_no_directory_association_or_contents_api(self):
        self.api.issues.pop(900, None); self.api.labels.pop('participant-directory', None)
        self.open_creation(); self.checked(); self.fill_meeting(end='',description=''); self.create(); self.ready()
        details = m.load_manifest(self.api,'meeting-' + str(self.last_number),'main')['meeting']
        self.assertNotIn('end_date',details); self.assertEqual(details['description'],'')
        self.assertEqual((details['start'],details['end'],details['timezone']),('00:01','23:59','Europe/Berlin'))
        self.assertFalse(any('/contents/' in r['url'] or '/labels/' in r['url'] for r in self.requests))

    def test_read_credentials_cannot_submit_from_form(self):
        self.open_creation(TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertTrue(self.page.locator('#create-meeting').is_disabled()); self.assertEqual(self.posts,0)

    def test_end_date_defaults_to_start_preserves_explicit_range_and_blank_means_same_day(self):
        self.open_creation(); self.checked()
        self.assertEqual(self.page.locator('label[for="end-date"]').inner_text(),'End date')
        self.page.locator('#start-date').fill('1-3-28')
        self.assertEqual(self.page.locator('#end-date').input_value(),'1-3-28')
        self.page.locator('#start-date').fill('2-3-28')
        self.assertEqual(self.page.locator('#end-date').input_value(),'2-3-28')
        self.page.locator('#end-date').fill('5-3-28')
        self.page.locator('#start-date').fill('3-3-28')
        self.assertEqual(self.page.locator('#end-date').input_value(),'5-3-28')
        self.page.locator('#end-date').fill('')
        self.page.locator('#meeting-name').fill('Same day default')
        self.page.locator('#location').fill('Fictitious room')
        self.create(); self.ready()
        issue = self.api.issues[self.last_number]
        self.assertIn('### End date\n\n03-03-2028',issue['body'])
        details = m.load_manifest(self.api,'meeting-' + str(self.last_number),'main')['meeting']
        self.assertEqual(details['date'],'2028-03-03')
        self.assertNotIn('end_date',details)

    def test_non_admin_roles_and_forced_submit_never_send_an_issue_post(self):
        before = set(self.api.issues)
        for role in ('read','triage','write','maintain'):
            self.api.permissions['member'] = role
            self.open_creation(TOKEN)
            self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
            self.fill_meeting()
            self.page.locator('#talk-form').evaluate("form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            self.assertEqual(self.posts,0)
        self.assertEqual(set(self.api.issues),before)

    def test_silent_admin_password_replacement_with_member_password_is_rejected_before_post(self):
        self.open_creation(); self.checked(); self.fill_meeting()
        self.page.locator('#admin-token').evaluate('(node, value) => {node.value=value}',TOKEN)
        self.create()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Check the administrator credentials')")
        self.assertEqual(self.posts,0)

    def test_role_is_rechecked_before_post_so_revoked_admin_cannot_create_even_an_issue(self):
        self.open_creation(); self.checked(); self.fill_meeting()
        before = set(self.api.issues)
        self.api.permissions['manager'] = 'read'
        self.create()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent === 'The meeting was not accepted.'")
        self.assertEqual(self.posts,0)
        self.assertEqual(set(self.api.issues),before)
        self.assertTrue(self.page.locator('#create-meeting').is_disabled())

    def test_expired_and_write_denied_tokens_show_safe_errors(self):
        self.auth_status = 401; self.open_creation()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('rejected')")
        self.assertNotIn('PRIVATE SERVICE ERROR CANARY',self.page.locator('body').inner_text())
        self.auth_status = None; self.open_creation(); self.checked(); self.fill_meeting(); self.deny_post = True; self.create()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent === 'The meeting was not accepted.'")
        self.assertNotIn('PRIVATE DENIAL CANARY',self.page.locator('body').inner_text())
        self.assertTrue(self.page.locator('#create-meeting').is_disabled())

    def test_invalid_dates_required_fields_and_password_paste_are_not_posted(self):
        self.open_creation(); self.checked()
        for changes in ({'start':'31-2-28'},{'end':'28-2-28'},{'name':' '},{'location':' '},
                        {'name':'[meeting 50] Mistake'},{'description':'### Location\nOther place'}, {'description':ADMIN_TOKEN}):
            self.fill_meeting(**changes); self.create()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertEqual(self.posts,0)

    def test_lost_post_response_recovers_prepared_issue_by_uuid_without_duplicates(self):
        self.lost = True; self.open_creation(); self.checked(); self.fill_meeting(); self.create(); self.ready()
        self.assertEqual(self.posts,1)
        self.assertTrue(any('creator=manager' in r['url'] for r in self.requests))
        self.assertTrue(self.page.locator('#create-meeting').is_disabled())

    def test_queued_creation_and_manual_status_check_wait_for_trusted_confirmation(self):
        self.mode = 'pending'; self.open_creation(); self.checked(); self.fill_meeting(); self.create()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Submitted.')")
        self.assertTrue(self.page.locator('#meeting-link').is_hidden())
        self.mode = 'automatic'; self.process_meeting(self.last_number)
        self.page.get_by_role('button',name='Check creation status',exact=True).click(); self.ready()
        self.assertEqual(self.posts,1)

    def test_public_verification_failure_then_admin_edit_reuses_original_issue(self):
        self.mode = 'fail'; self.open_creation(); self.checked(); self.fill_meeting(); self.create()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('needs attention')")
        self.assertTrue(self.page.locator('#meeting-link').is_hidden())
        number = self.last_number
        self.api.issues[number]['body'] = self.api.issues[number]['body'].replace('A public description.','Corrected description.')
        self.mode = 'automatic'; self.process_meeting(number,edited=True)
        self.page.get_by_role('button',name='Check creation status',exact=True).click(); self.ready()
        self.assertEqual(self.posts,1)
        self.assertIn('Corrected description.',self.api.file(m.PUBLIC,f'prototype/meetings/meeting-{number}/index.html',m.PREVIEW_BRANCH))

    def test_member_forged_ready_comment_does_not_publish_status(self):
        self.mode = 'pending'; self.open_creation(); self.checked(); self.fill_meeting(); self.create()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Submitted.')")
        number = self.last_number
        data = {'schema_version':1,'submission_id':m.meeting_submission(self.api.issues[number]),'state':'ready','revision':'b'*40,'meeting_id':f'meeting-{number}'}
        self.api.comments[number] = [{'id':500,'user':{'login':'github-actions[bot]','type':'User'},'body':m.MEETING_STATUS + json.dumps(data) + ' -->'}]
        self.page.get_by_role('button',name='Check creation status',exact=True).click()
        self.assertTrue(self.page.locator('#meeting-link').is_hidden()); self.assertEqual(self.posts,1)

    def test_double_click_privacy_password_change_and_pagehide(self):
        self.open_creation(); self.checked(); self.fill_meeting()
        self.page.locator('#create-meeting').evaluate('node => { node.click(); node.click(); }'); self.ready()
        self.assertEqual(self.posts,1)
        for text in (self.page.content(),json.dumps(self.api.issues),json.dumps(self.api.comments)):
            self.assertNotIn(ADMIN_TOKEN,text)
        self.assertEqual(self.page.evaluate('[localStorage.length,sessionStorage.length]'),[0,0])
        self.page.locator('#admin-token').fill('changed')
        self.assertTrue(self.page.locator('#check-status').is_disabled())
        self.page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        self.assertEqual(self.page.locator('#admin-token').input_value(),'')

    def test_mobile_layout_keyboard_and_no_js_native_submission(self):
        self.page.set_viewport_size({'width':320,'height':800}); self.open_creation(); self.checked()
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        self.page.locator('#start-date').focus(); self.page.keyboard.press('Tab')
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'end-date')
        context = self.browser.new_context(java_script_enabled=False)
        self.addCleanup(context.close); context.route('**/*',self.route)
        page = context.new_page(); page.goto(self.base + '/prototype/create-meeting.html')
        self.assertTrue(page.locator('#meeting-fields').evaluate('node => node.disabled'))
        self.assertTrue(page.locator('#admin-fields').evaluate('node => node.disabled'))
        self.assertIsNone(page.locator('#admin-token').get_attribute('name'))
        page.evaluate('HTMLFormElement.prototype.submit.call(document.getElementById("talk-form"))')
        self.assertEqual(self.posts,0)


if __name__ == '__main__':
    unittest.main()
