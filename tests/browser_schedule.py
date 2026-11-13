"""Real preview + browser -> trusted batch handler -> verified public programme.

Fictitious data/credentials only. Both repositories must be checked out.
"""
import copy
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import unittest

from browser_talk_submission import FormBrowserFixture, TOKEN, API, ROOT, m, DETAILS
from test_meeting_schedule_editor import ScheduleGitHub
from test_web_talks import proposal

ADMIN = 'github_pat_FICTITIOUS_SCHEDULE_ADMIN_ONLY'


class ScheduleBrowserTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        self.api = ScheduleGitHub()
        files = self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
        files['prototype/index.html'] = files['prototype/index.html'].replace('<html><body>',
            '<html><head><link rel="stylesheet" href="assets/style.css"></head><body>')
        self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)['prototype/schedule.html'] = (ROOT / 'prototype/schedule.html').read_text()
        m.prepare(self.api,m.authorize(self.api,self.api.request(4,DETAILS | {'end_date':'2027-02-14'}),'issues'))
        m.prepare(self.api,m.authorize(self.api,self.api.request(10,DETAILS | {'name':'Another meeting'}),'issues'))
        for number, ident in [(7,'meeting-4'),(8,'meeting-4'),(12,'meeting-10')]:
            self.api.issues[number] = proposal(number,ident,date='12-2-27',time='9:00')
            self.api.issues[number]['title'] = m.issue_prefix(ident) + ' Fictitious talk ' + str(number)
            self.api.issues[number]['labels'] = ['talk','meeting:' + ident,m.web.FORMAT_LABEL]
            self.api.comments[number] = [{'body':'PRIVATE DISCUSSION CANARY'}]
        m.sync_preview(self.api,maintain_private=False)
        self.flush_pages()
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        self.mode = 'automatic'
        self.lost = False
        self.auth_error = None
        self.post_error = None
        self.last_event = None
        self.workflow_errors = []

    def route(self, route):
        request = route.request
        if not request.url.startswith(API + '/'):
            return super().route(route)
        url = urlsplit(request.url)
        self.requests.append({'method':request.method,'url':request.url,'headers':request.headers,'body':request.post_data})
        if request.method == 'OPTIONS':
            route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET, POST',
                'Access-Control-Allow-Headers':'authorization,content-type,x-github-api-version'}); return
        self.assertEqual(request.method in {'GET','POST'},True)
        self.assertIn(request.headers.get('authorization'),{'Bearer ' + ADMIN,'Bearer ' + TOKEN})
        owner = {'login':'manager' if request.headers['authorization'] == 'Bearer ' + ADMIN else 'member', 'id':1,'type':'User'}
        for key in (ADMIN,TOKEN):
            self.assertNotIn(key,request.url); self.assertNotIn(key,request.post_data or '')
        root = '/repos/' + m.PRIVATE
        path = url.path
        if self.auth_error:
            self.json_response(route,{'message':'PRIVATE SERVICE ERROR CANARY'},self.auth_error)
        elif path == '/user': self.json_response(route,owner)
        elif path == root: self.json_response(route,{'full_name':m.PRIVATE,'permissions':{'pull':True}})
        elif path == root + '/collaborators/' + owner['login'] + '/permission':
            self.json_response(route,{'permission':self.api.permissions[owner['login']]})
        elif path == root + '/issues':
            self.assertEqual(request.method,'GET')
            selected = parse_qs(url.query)['labels'][0].split(',')
            records = [self.api.issue_record(issue) for issue in self.api.issues.values() if all(label in m.label_names(issue) for label in selected)]
            page = int(parse_qs(url.query).get('page',['1'])[0])
            self.json_response(route,records[(page-1)*100:page*100])
        elif path.startswith(root + '/issues/'):
            tail = path[len(root + '/issues/'):].split('/')
            number = int(tail[0])
            if len(tail) == 1:
                self.assertEqual(request.method,'GET')
                issue = self.api.issues.get(number)
                self.json_response(route,self.api.issue_record(issue) if issue else {},200 if issue else 404)
            elif tail[1] == 'comments' and request.method == 'POST':
                self.posts += 1
                if self.post_error: self.json_response(route,{},self.post_error); return
                result = self.api.api('POST','repos/' + m.PRIVATE + '/issues/' + str(number) + '/comments',request.post_data_json)
                self.api.comments[number][-1]['user'] = owner
                result['user'] = owner
                self.last_event = {'repository':{'full_name':m.PRIVATE},'sender':owner,'action':'created',
                                   'issue':{'number':number},'comment':result}
                if self.mode != 'pending': self.process_batch()
                if self.lost: route.abort('failed')
                else: self.json_response(route,result,201)
            elif tail[1] == 'comments':
                comments = copy.deepcopy(self.api.comments.get(number,[]))
                for comment in comments:
                    if not comment['body'].startswith(m.scheduler.STATUS): continue
                    data = json.loads(comment['body'][len(m.scheduler.STATUS):comment['body'].index(' -->')])
                    if 'revision' in data: data['revision'] = 'b'*40
                    comment['body'] = m.scheduler.STATUS + json.dumps(data) + ' -->\nStatus'
                page = int(parse_qs(url.query).get('page',['1'])[0])
                self.json_response(route,comments[(page-1)*100:page*100])
            else: raise AssertionError('Unexpected Issue subresource')
        else: raise AssertionError('Unexpected API path: ' + path)

    def process_batch(self):
        try:
            request = m.authorize(self.api,self.last_event,'issue_comment')
            if self.mode == 'sync-failure':
                with patch.object(m,'verify_synced_meetings',side_effect=m.SetupError('Fictitious sync failure')):
                    m.prepare(self.api,request,reader=self.api)
            else: m.prepare(self.api,request,reader=self.api)
        except m.SetupError as failure: self.workflow_errors.append(str(failure))
        self.flush_pages()

    def open_editor(self, ident='meeting-4', credential=ADMIN):
        self.page.goto(self.base + '/prototype/schedule.html?meeting=' + ident)
        self.page.wait_for_function("() => !document.getElementById('admin-fields').disabled")
        self.page.locator('#admin-token').fill(credential)
        self.page.get_by_role('button',name='Check credentials',exact=True).click()

    def ready(self): self.page.wait_for_function("() => !document.getElementById('save-schedule').disabled")
    def field(self, number, column): return self.page.locator(f'tr[data-talk-number="{number}"] td:nth-child({column}) input')
    def save(self): self.page.get_by_role('button',name='Save changes',exact=True).click()
    def done(self): self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Schedule synchronized.')")

    def test_real_navigation_one_password_multiple_changes_correct_meeting_and_public_order(self):
        self.page.goto(self.base + '/prototype/meetings/meeting-4/')
        group = self.page.locator('.meeting-actions')
        self.assertEqual(group.inner_text().splitlines(),['Participation','Add talk','Schedule'])
        boxes = [group.get_by_role('link',name=name,exact=True).bounding_box() for name in ['Participation','Add talk','Schedule']]
        self.assertLess(max(box['y'] for box in boxes) - min(box['y'] for box in boxes),2)
        self.page.get_by_role('link',name='Schedule',exact=True).click()
        self.page.locator('#admin-token').fill(ADMIN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click(); self.ready()
        self.assertEqual(self.page.locator('select').count(),0)
        self.assertEqual(self.page.locator('#schedule-rows tr').count(),2)
        before = copy.deepcopy(self.api.issues[12])
        self.field(7,2).fill('13-2-27'); self.field(7,3).fill('15:30')
        self.field(8,3).fill('8:00'); self.save(); self.done()
        self.assertEqual(self.posts,1)
        self.assertEqual(self.page.locator('#admin-token').input_value(),ADMIN)
        self.assertFalse(any('/contents/' in r['url'] or r['method'] == 'PATCH' for r in self.requests))
        self.assertEqual(self.api.issues[12],before)
        self.page.get_by_role('link',name='Return to meeting',exact=True).click()
        self.assertEqual(self.page.locator('li[data-talk-number]').evaluate_all('(items) => items.map(item => item.dataset.talkNumber)'),['8','7'])
        self.assertIn('15:30',self.page.locator('li[data-talk-number="7"]').inner_text())
        self.assertFalse(self.errors); self.assertFalse(self.external); self.assertFalse(self.workflow_errors)

    def test_member_and_demoted_administrator_cannot_save(self):
        self.open_editor(credential=TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertEqual(self.page.locator('#schedule-rows tr').count(),0); self.assertEqual(self.posts,0)
        self.open_editor(); self.ready(); self.field(7,3).fill('10:00')
        self.api.permissions['manager'] = 'read'; self.save()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertEqual(self.posts,0)

    def test_invalid_or_legacy_link_never_selects_another_meeting(self):
        for ident in ['meeting-999','legacy-20230424-7d8089f21b9c','../../main','']:
            self.page.goto(self.base + '/prototype/schedule.html?meeting=' + ident)
            self.page.wait_for_function("() => !document.getElementById('form-status').textContent.includes('could not start')")
            self.assertIsNotNone(self.page.locator('#admin-fields').get_attribute('disabled'))
            self.assertTrue(self.page.locator('#save-schedule').is_disabled())
        self.assertEqual(self.requests,[])

    def test_single_day_defaults_are_not_written_and_new_edit_needs_no_password_reentry(self):
        self.api.issues[12] = proposal(12,'meeting-10')
        self.api.issues[12]['labels'] = ['talk','meeting:meeting-10']
        before = self.api.issues[12]['body']
        self.open_editor('meeting-10'); self.ready()
        self.assertTrue(self.field(12,2).get_attribute('readonly') is not None)
        self.assertEqual(self.field(12,3).input_value(),'09:00')
        self.save(); self.page.wait_for_function("() => document.getElementById('submission-status').textContent === 'No scheduling changes to save.'")
        self.assertEqual(self.posts,0); self.assertEqual(self.api.issues[12]['body'],before)
        self.field(12,3).fill('10:00'); self.save(); self.done()
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.assertEqual(self.field(12,3).input_value(),'10:00')
        self.field(12,3).fill('11:00'); self.save(); self.done()
        self.assertEqual(self.posts,2)

    def test_validation_and_hidden_meeting_change_prevent_submission(self):
        self.open_editor(); self.ready()
        for column, value in [(2,'29-2-27'),(2,'15-2-27'),(3,'24:00')]:
            self.field(7,2).fill('12-2-27'); self.field(7,3).fill('09:00')
            self.field(7,column).fill(value); self.save()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertEqual(self.posts,0)
        self.field(7,3).fill('10:00'); self.api.issues[4]['labels'].append('hidden'); self.save()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('hidden or unavailable')")
        self.assertEqual(self.posts,0)

    def test_lost_post_response_recovers_by_get_without_duplicate_and_ignores_spoofed_receipts(self):
        self.mode = 'pending'; self.lost = True
        self.open_editor(); self.ready(); self.field(7,3).fill('10:10'); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Request submitted.')")
        self.assertEqual(self.posts,1)
        data = m.scheduler.parse(self.last_event['comment']['body'],m.web)
        fake = dict(schema_version=1, request_id=data['request_id'], comment_id=self.last_event['comment']['id'],
                    request_hash=m.scheduler.digest(self.last_event['comment']['body']), meeting_id='meeting-4',state='synchronized',
                    results=[{'number':7,'state':'saved'}],revision='b'*40)
        self.api.comments[4].append({'body':m.scheduler.STATUS + json.dumps(fake) + ' -->','user':{'login':'member','type':'User'}})
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.assertNotIn('Schedule synchronized',self.page.locator('#submission-status').inner_text())
        self.process_batch(); self.page.get_by_role('button',name='Check progress',exact=True).click(); self.done()
        self.assertEqual(self.posts,1)

    def test_concurrent_edit_partial_success_and_retry_only_remaining_change(self):
        self.open_editor(); self.ready(); self.field(7,3).fill('11:00'); self.field(8,3).fill('12:00')
        self.api.issues[7]['body'] = self.api.issues[7]['body'].replace('A fictitious abstract.','A newer administrator abstract.')
        self.save(); self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Some changes')")
        self.assertEqual(self.page.locator('tr[data-talk-number="7"] .schedule-result').inner_text(),'Changed elsewhere — reload')
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'09:00')
        self.assertEqual(m.web.parse(self.api.issues[8])['time'],'12:00')
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.field(7,3).fill('11:00'); self.save(); self.done()
        data = m.scheduler.parse(self.last_event['comment']['body'],m.web)
        self.assertEqual([row['number'] for row in data['changes']],[7])
        self.assertIn('A newer administrator abstract.',self.api.issues[7]['body'])

    def test_archived_hidden_native_and_invalid_schedule_repair_preserve_visibility(self):
        self.api.issues[7].update(body='### Authors\n\nA. Example\n\n### Talk time\n\nINVALID\n\n### Abstract\n\nHistorical abstract\n\n### Internal notes\n\nPRIVATE CANARY', labels=['talk','meeting:meeting-4','talk-hidden'])
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'archive'}); self.flush_pages()
        self.page.goto(self.base + '/prototype/meetings/meeting-4/')
        self.assertTrue(self.page.get_by_role('button',name='Add talk',exact=True).is_disabled())
        self.page.get_by_role('link',name='Schedule',exact=True).click()
        self.page.locator('#admin-token').fill(ADMIN); self.page.get_by_role('button',name='Check credentials',exact=True).click(); self.ready()
        self.field(7,3).fill('11:00'); self.save(); self.done()
        public = self.api.file(m.PUBLIC,'prototype/meetings/meeting-4/index.html',m.PREVIEW_BRANCH)
        self.assertNotIn('Historical abstract',public); self.assertNotIn('PRIVATE CANARY',public)
        self.assertIn('archived',m.label_names(self.api.issues[4]))
        self.assertIn('talk-hidden',m.label_names(self.api.issues[7]))

    def test_sync_failure_does_not_claim_success(self):
        self.mode = 'sync-failure'; self.open_editor(); self.ready(); self.field(7,3).fill('10:00'); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Scheduling needs attention.')")
        self.assertNotIn('Schedule synchronized',self.page.locator('#submission-status').inner_text())
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'10:00')

    def test_older_registration_layout_with_escaped_dates_is_supported(self):
        manifest = m.load_manifest(self.api,'meeting-4','main')
        self.api.issues[4]['body'] = m.registration_body('meeting-4',manifest['meeting'])
        self.open_editor(); self.ready(); self.field(7,3).fill('10:00'); self.save(); self.done()
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'10:00')

    def test_pagination_loads_all_talks_and_leaves_bad_unchanged_slots_out_of_a_save(self):
        for number in range(100,201):
            self.api.issues[number] = proposal(number,date='12-2-27',time='09:00')
            self.api.issues[number]['labels'] = ['talk','meeting:meeting-4']
        self.open_editor(); self.ready()
        self.assertEqual(self.page.locator('#schedule-rows tr').count(),103)
        self.assertTrue(any('page=2' in request['url'] and '/issues?' in request['url'] for request in self.requests))
        # Use the original two-talk fixture for the processing part: the REST
        # model's shared Issue-list fake is intentionally not paginated.
        for number in range(100,201): del self.api.issues[number]
        self.api.issues[8]['body'] = self.api.issues[8]['body'].replace('9:00','INVALID')
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.field(7,3).fill('11:15'); self.save(); self.done()
        self.assertEqual([row['number'] for row in m.scheduler.parse(self.last_event['comment']['body'],m.web)['changes']],[7])

    def test_credential_change_exit_reload_and_mobile_layout(self):
        self.open_editor(); self.ready(); self.field(7,3).fill('10:00')
        self.page.locator('#admin-token').evaluate("node => {node.value='changed-without-event';}")
        self.save(); self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Check administrator credentials')")
        self.assertEqual(self.posts,0)
        self.assertEqual(self.page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length'),0)
        self.page.reload(); self.page.wait_for_function("() => !document.getElementById('admin-fields').disabled")
        self.assertEqual(self.page.locator('#admin-token').input_value(),'')
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.locator('#admin-token').fill(ADMIN); self.page.get_by_role('button',name='Check credentials',exact=True).click(); self.ready()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.assertEqual(self.page.locator('#schedule-rows tr').count(),2)
        self.assertNotIn('PRIVATE DISCUSSION CANARY',self.page.content())


if __name__ == '__main__': unittest.main()
