"""Real preview + browser -> trusted batch handler -> verified public programme.

Fictitious data/credentials only. Both repositories must be checked out.
"""
import copy
import json
import re
import uuid
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
        self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)['prototype/participation.html'] = (ROOT / 'prototype/participation.html').read_text()
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
        self.reactions = []
        self.reaction_error = None
        self.hold_registration_read = False
        self.held_registration_route = None

    def route(self, route):
        request = route.request
        if not request.url.startswith(API + '/'):
            return super().route(route)
        url = urlsplit(request.url)
        self.requests.append({'method':request.method,'url':request.url,'headers':request.headers,'body':request.post_data})
        if request.method == 'OPTIONS':
            route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET, POST',
                'Access-Control-Allow-Headers':'authorization,content-type,x-github-api-version'}); return
        self.assertEqual(request.method in {'GET','POST','DELETE'},True)
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
        elif path.startswith(root + '/issues/comments/') and request.method=='DELETE':
            number=int(path.rsplit('/',1)[-1])
            for comments in self.api.comments.values():
                found=next((comment for comment in comments if comment.get('id')==number and comment.get('user',{}).get('login')==owner['login'] and comment.get('user',{}).get('id')==owner['id']),None)
                if found is not None:
                    comments.remove(found)
                    route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*'});return
            self.json_response(route,{},404)
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
                if self.mode != 'pending' and result['body'].startswith(m.scheduler.MARKER): self.process_batch()
                if self.lost: route.abort('failed')
                else: self.json_response(route,result,201)
            elif tail[1] == 'reactions':
                self.json_response(route,self.reactions if not self.reaction_error else {},self.reaction_error or 200)
            elif tail[1] == 'comments':
                if self.hold_registration_read:
                    self.hold_registration_read=False;self.held_registration_route=route;return
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
    def hidden_field(self, number): return self.page.locator(f'tr[data-talk-number="{number}"] input[type="checkbox"]')
    def save(self): self.page.get_by_role('button',name='Save changes',exact=True).click()
    def done(self): self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Schedule synchronized.')")
    def notes_ready(self): self.page.wait_for_function("() => !document.getElementById('meeting-notes').disabled")
    def notes_done(self): self.page.wait_for_function("() => document.getElementById('submission-status').textContent === 'Notes saved.'")
    def stored_notes(self): return m.scheduler.notes.current(m,self.api,'meeting-4',4)
    def seed_notes(self,value):
        return self.api.api('POST',f'repos/{m.PRIVATE}/issues/4/comments',
            {'body':m.scheduler.notes.document('meeting-4',str(uuid.uuid4()),value)})

    def attendance(self,name,number=1001,ident='meeting-4',schema=3,owner=50):
        data={'schema_version':schema,'meeting_id':ident,'credential_fingerprint':'f'*64}
        if schema==1:
            data['username']=name
            body='Yes\n\nParticipant: '+name+'\n\n'
        else:
            data['name']=name
            if schema==2:data['member_id']='11111111-1111-4111-8111-111111111111'
            label=name.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            label=re.sub(r'[\\`*_{}\[\]()#+.!|>\-]',lambda match:'\\'+match[0],label)
            body='Yes — '+label+'\n\n'
        metadata=json.dumps(data,ensure_ascii=True,separators=(',',':'))
        if schema!=1:
            for before,after in [('<','\\u003c'),('>','\\u003e'),('&','\\u0026')]:metadata=metadata.replace(before,after)
        return {'id':number,'body':body+'<!-- wg13-participation '+metadata+' -->',
                'user':{'id':owner,'login':'fictitious-member-'+str(owner),'type':'User'}}

    def registered(self,text):
        self.page.wait_for_function('(text)=>document.getElementById("registered-people").textContent.includes(text)',arg=text)
        self.assertEqual(self.page.locator('#registered-people strong').inner_text(),'Registered:')
        self.assertEqual(self.page.locator('#meeting-notes-row strong').inner_text(),'Notes:')
        self.assertEqual(self.page.locator('#meeting-dates strong').inner_text(),'When:')
        self.assertEqual(self.page.locator('#registered-people').evaluate('node=>node.nextElementSibling.id'),'meeting-notes-row')

    def test_real_navigation_one_password_multiple_changes_correct_meeting_and_public_order(self):
        self.page.goto(self.base + '/prototype/meetings/meeting-4/')
        group = self.page.locator('.meeting-actions')
        self.assertEqual(group.inner_text().splitlines(),['Participation','Add talk','Schedule'])
        boxes = [group.get_by_role('link',name=name,exact=True).bounding_box() for name in ['Participation','Add talk','Schedule']]
        self.assertLess(max(box['y'] for box in boxes) - min(box['y'] for box in boxes),2)
        self.page.get_by_role('link',name='Schedule',exact=True).click()
        self.page.locator('#admin-token').fill(ADMIN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click(); self.ready()
        self.assertEqual(self.page.get_by_role('columnheader',name='Hidden',exact=True).evaluate(
            'node=>{const range=document.createRange();range.selectNodeContents(node);return range.getClientRects().length;}'),1)
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

    def test_hide_restore_without_password_reentry_and_private_record_preserved(self):
        original = copy.deepcopy(self.api.issues[7])
        self.open_editor(); self.ready()
        self.assertFalse(self.hidden_field(7).is_checked())
        self.hidden_field(7).check()
        self.assertEqual(self.page.locator('tr[data-talk-number="7"] .schedule-result').inner_text(),'Will hide on save')
        self.save(); self.done()
        self.assertIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))
        self.assertEqual(self.page.locator('#schedule-rows tr').count(),2)
        public = self.page.request.get(self.base+'/prototype/meetings/meeting-4/').text()
        self.assertNotIn('data-talk-number="7"',public); self.assertIn('data-talk-number="8"',public)
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.assertTrue(self.hidden_field(7).is_checked())
        self.hidden_field(7).uncheck(); self.save(); self.done()
        self.assertEqual(self.api.issues[7],original)
        self.assertEqual(self.page.locator('#admin-token').input_value(),ADMIN)
        self.assertEqual(self.posts,2)
        public = self.page.request.get(self.base+'/prototype/meetings/meeting-4/').text()
        self.assertIn('data-talk-number="7"',public)
        self.assertFalse(any('/labels' in request['url'] or request['method'] in {'PATCH','DELETE'} for request in self.requests))
        self.assertFalse(self.errors); self.assertFalse(self.workflow_errors)

    def test_mixed_visibility_and_scheduling_changes_and_time_only_keeps_talk_hidden(self):
        self.open_editor(); self.ready(); self.hidden_field(7).check(); self.field(8,3).fill('10:00')
        self.save(); self.done()
        rows = m.scheduler.parse(self.last_event['comment']['body'],m.web)['changes']
        self.assertNotIn('date',rows[0]); self.assertNotIn('hidden',rows[1])
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.field(7,3).fill('11:00'); self.save(); self.done()
        row = m.scheduler.parse(self.last_event['comment']['body'],m.web)['changes'][0]
        self.assertNotIn('hidden',row)
        self.assertIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.hidden_field(7).uncheck(); self.save(); self.done()
        self.page.get_by_role('link',name='Return to meeting',exact=True).click()
        self.assertEqual(self.page.locator('li[data-talk-number]').evaluate_all('(items)=>items.map(item=>item.dataset.talkNumber)'),['8','7'])
        self.assertIn('11:00',self.page.locator('li[data-talk-number="7"]').inner_text())

    def test_checkbox_cancel_before_save_is_not_a_visibility_request(self):
        self.open_editor(); self.ready(); self.hidden_field(7).check(); self.hidden_field(7).uncheck(); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent === 'No scheduling changes to save.'")
        self.assertEqual(self.posts,0)
        self.assertNotIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))

    def test_hide_only_malformed_talk_is_allowed_and_restore_does_not_claim_publication(self):
        self.api.issues[7]['body'] = m.web.MARKER+'\nMalformed proposal'
        original = self.api.issues[7]['body']
        self.open_editor(); self.ready()
        self.assertTrue(self.field(7,3).is_disabled()); self.assertTrue(self.hidden_field(7).is_enabled())
        self.hidden_field(7).check(); self.save(); self.done()
        self.assertEqual(self.api.issues[7]['body'],original)
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.hidden_field(7).uncheck(); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Some changes need attention.')")
        self.assertIn('Restored; Not published',self.page.locator('tr[data-talk-number="7"] .schedule-result').inner_text())
        self.assertNotIn('Schedule synchronized',self.page.locator('#submission-status').inner_text())
        self.assertNotIn('data-talk-number="7"',self.api.file(m.PUBLIC,'prototype/meetings/meeting-4/index.html',m.PREVIEW_BRANCH))

    def test_archived_visibility_changes_keep_registration_closed(self):
        self.api.issues[7]['labels'].append(m.TALK_HIDDEN)
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'archive'}); self.flush_pages()
        registration = copy.deepcopy(self.api.issues[4])
        self.open_editor(); self.ready()
        self.assertTrue(self.hidden_field(7).is_checked()); self.assertFalse(self.hidden_field(8).is_checked())
        self.hidden_field(7).uncheck(); self.hidden_field(8).check(); self.save(); self.done()
        self.assertEqual(self.api.issues[4],registration)
        public = self.api.file(m.PUBLIC,'prototype/meetings/meeting-4/index.html',m.PREVIEW_BRANCH)
        self.assertIn('data-talk-number="7"',public); self.assertNotIn('data-talk-number="8"',public)
        self.assertNotIn('submit-talk.html?',public)

    def test_concurrent_visibility_change_is_reported_without_overwriting(self):
        self.mode='pending'; self.open_editor(); self.ready(); self.hidden_field(7).check(); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Request submitted.')")
        self.api.issues[7]['labels'].append(m.TALK_HIDDEN)  # Another administrator acted first.
        self.api.calls.clear(); self.process_batch()
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Some changes')")
        self.assertIn('Visibility: Changed elsewhere',self.page.locator('tr[data-talk-number="7"] .schedule-result').inner_text())
        self.assertFalse(any(method in {'POST','DELETE'} and '/issues/7/labels' in path for method,path,_ in self.api.calls))

    def test_failed_scheduling_correction_keeps_restoration_hidden_until_retry(self):
        self.api.issues[7]['labels'].append(m.TALK_HIDDEN)
        self.open_editor(); self.ready(); self.hidden_field(7).uncheck(); self.field(7,3).fill('14:00')
        real_api = self.api.api
        def failed(method,path,data=None,missing_ok=False):
            if method == 'PATCH' and path.endswith('/issues/7'): raise m.SetupError('Fictitious write failure')
            return real_api(method,path,data,missing_ok)
        with patch.object(self.api,'api',side_effect=failed):
            self.save(); self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Some changes')")
        self.assertIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))
        self.assertNotIn('Restored',self.page.locator('tr[data-talk-number="7"] .schedule-result').inner_text())
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.hidden_field(7).uncheck(); self.field(7,3).fill('14:00'); self.save(); self.done()
        self.assertNotIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))

    def test_keyboard_mobile_and_lost_request_response_recover_without_duplicate(self):
        self.lost=True; self.open_editor(); self.ready()
        self.page.set_viewport_size({'width':390,'height':844})
        self.hidden_field(7).focus(); self.page.keyboard.press('Space'); self.save(); self.done()
        self.assertEqual(self.posts,1)
        self.assertIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.assertEqual(self.page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length'),0)
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.hidden_field(7).uncheck(); self.save(); self.done()
        self.assertEqual(self.posts,2)

    def test_slides_disappear_and_return_with_visibility(self):
        from test_talk_slides import stage, example_pdf
        reference = stage(self.api)
        self.api.issues[7] = proposal(slides=reference,date='12-2-27',time='09:00')
        self.api.issues[7]['labels'] = ['talk','meeting:meeting-4',m.web.FORMAT_LABEL]
        m.sync_preview(self.api,maintain_private=False); self.flush_pages()
        slide=next(talk['slides']['path'] for talk in m.public_talks(self.api,'meeting-4') if talk['number']==7)
        self.open_editor(); self.ready(); self.hidden_field(7).check(); self.save(); self.done()
        self.assertEqual(self.page.request.get(self.base+'/'+slide).status,404)
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.hidden_field(7).uncheck(); self.save(); self.done()
        response=self.page.request.get(self.base+'/'+slide)
        self.assertEqual(response.status,200); self.assertEqual(response.body(),example_pdf())

    def test_retry_after_later_admin_restore_reports_current_visibility_without_rehiding(self):
        self.mode='sync-failure'; self.open_editor(); self.ready(); self.hidden_field(7).check(); self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Scheduling needs attention.')")
        self.assertIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))
        self.api.issues[7]['labels'].remove(m.TALK_HIDDEN)
        self.mode='automatic'; self.process_batch()
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Some changes')")
        self.assertEqual(self.page.locator('tr[data-talk-number="7"] .schedule-result').inner_text(),'Visibility changed elsewhere — reload')
        self.assertNotIn(m.TALK_HIDDEN,m.label_names(self.api.issues[7]))
        self.page.get_by_role('button',name='Reload talks',exact=True).click(); self.ready()
        self.assertFalse(self.hidden_field(7).is_checked())

    def test_notes_are_loaded_only_after_admin_verification_and_cleared_on_exit(self):
        value='PRIVATE NOTES CANARY — Café, Grüße, 日本語.\nAnother line.'
        self.seed_notes(value)
        context=self.browser.new_context(java_script_enabled=False)
        try:
            page=context.new_page();page.goto(self.base+'/prototype/schedule.html?meeting=meeting-4')
            self.assertFalse(page.locator('#meeting-notes').is_visible())
            self.assertFalse(page.locator('#archive-meeting').is_visible())
            self.assertEqual(page.locator('#meeting-notes').input_value(),'')
        finally:context.close()
        self.page.goto(self.base+'/prototype/schedule.html?meeting=meeting-4')
        self.page.wait_for_function("() => !document.getElementById('admin-fields').disabled")
        self.assertFalse(self.page.locator('#meeting-notes').is_visible())
        self.assertNotIn(value,self.page.content())
        self.assertFalse(any('/comments?' in request['url'] for request in self.requests))
        self.open_editor(credential=TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertFalse(self.page.locator('#meeting-notes').is_visible())
        self.open_editor();self.ready();self.notes_ready()
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),value)
        self.page.locator('#admin-token').fill('')
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),'')
        self.assertFalse(self.page.locator('#meeting-notes').is_visible())
        self.open_editor();self.ready();self.notes_ready()
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),'')
        self.assertEqual(self.page.evaluate('[localStorage.length,sessionStorage.length]'),[0,0])
        self.assertEqual(self.posts,0)

    def test_notes_only_save_reload_edit_clear_for_a_meeting_without_talks(self):
        for number in (7,8):del self.api.issues[number]
        m.sync_preview(self.api,maintain_private=False);self.flush_pages()
        public=copy.deepcopy(self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH))
        self.open_editor();self.ready();self.notes_ready()
        for value in ('Café\n\n日本語 — Grüße.','A correction.',''):
            self.page.locator('#meeting-notes').fill(value);self.save();self.notes_done()
            self.assertEqual(self.stored_notes()['text'],value)
            self.assertEqual(self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH),public)
            self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.notes_ready()
            self.assertEqual(self.page.locator('#meeting-notes').input_value(),value)
        self.assertEqual(self.posts,3)
        self.assertFalse(self.errors);self.assertFalse(self.workflow_errors)

    def test_notes_and_talk_changes_must_be_saved_before_archiving_then_remain_editable(self):
        self.api.issues[7]['labels'].append('talk-hidden')
        self.api.comments[4].append(self.attendance('Alice PRIVATE MEMBER'))
        self.open_editor();self.ready();self.notes_ready()
        self.registered('Alice PRIVATE MEMBER')
        self.page.locator('#meeting-notes').fill('PRIVATE NOTES CANARY — Grüße.\nRoom arrangements.')
        self.field(8,3).fill('11:15')
        for name in ('Hide Meeting','Archive Meeting'):
            button=self.page.get_by_role('button',name=name,exact=True)
            self.assertTrue(button.is_disabled());button.dispatch_event('click')
        self.assertEqual(self.posts,0)
        self.save();self.done()
        self.assertEqual(m.web.parse(self.api.issues[8])['time'],'11:15')
        self.assertEqual(self.page.locator('#admin-token').input_value(),ADMIN)
        self.page.get_by_role('button',name='Archive Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting archived.')")
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())
        self.assertTrue(self.api.issues[4]['locked']);self.assertEqual(self.api.issues[4]['state'],'closed')
        self.assertNotIn('hidden',m.label_names(self.api.issues[4]))
        page=self.api.file(m.PUBLIC,'prototype/meetings/meeting-4/index.html',m.PREVIEW_BRANCH)
        self.assertIn('This meeting is archived',page)
        self.assertNotIn('data-talk-number="7"',page);self.assertIn('data-talk-number="8"',page)
        self.assertNotIn('PRIVATE NOTES CANARY',page)
        self.assertNotIn('participation.html?',page);self.assertNotIn('submit-talk.html?',page)
        self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.notes_ready()
        self.assertIn('Room arrangements.',self.page.locator('#meeting-notes').input_value())
        self.page.locator('#meeting-notes').fill('An archived correction.')
        self.save();self.notes_done()
        self.assertEqual(self.stored_notes()['text'],'An archived correction.')
        self.assertEqual(m.registration_status(self.api.issues[4]),'archived')
        self.assertFalse(any('/labels' in request['url'] or request['method'] in {'PATCH','DELETE'} for request in self.requests))
        self.assertFalse(self.errors);self.assertFalse(self.workflow_errors)

    def test_stale_notes_do_not_overwrite_a_later_correction_and_report_partial_results(self):
        self.open_editor();self.ready();self.notes_ready()
        self.seed_notes('A newer private correction.')
        self.page.locator('#meeting-notes').fill('An older tab edit.')
        self.field(7,3).fill('11:15');self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Some changes')")
        self.assertEqual(self.stored_notes()['text'],'A newer private correction.')
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'11:15')
        self.assertIn('not confirmed',self.page.locator('#notes-status').inner_text())
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())
        self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.notes_ready()
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),'A newer private correction.')

    def test_broken_notes_do_not_load_as_empty_or_block_independent_talk_corrections(self):
        body=m.scheduler.notes.MARKER+'\nPRIVATE BROKEN NOTES CANARY'
        self.api.api('POST',f'repos/{m.PRIVATE}/issues/4/comments',{'body':body})
        self.open_editor();self.ready()
        self.page.wait_for_function("() => document.getElementById('notes-status').textContent.includes('administrator review')")
        self.assertTrue(self.page.locator('#meeting-notes').is_disabled())
        self.assertNotIn('PRIVATE BROKEN NOTES CANARY',self.page.content())
        self.field(7,3).fill('11:15');self.save();self.done()
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'11:15')
        data=m.scheduler.parse(self.last_event['comment']['body'],m.web)
        self.assertNotIn('notes',data)
        self.assertIn(body,[comment['body'] for comment in self.api.comments[4]])
        self.assertTrue(self.page.locator('#hide-meeting').is_disabled())
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())

    def test_notes_unicode_boundary_markup_and_invalid_input_are_handled_as_text(self):
        self.open_editor();self.ready();self.notes_ready()
        for value in ('x'*10001,'bad\x01text',ADMIN):
            self.page.locator('#meeting-notes').fill(value);self.save()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertEqual(self.posts,0)
        for value in ('😀'*10000,'<script>alert("private")</script>\nRene\u0301 & Müller'):
            self.page.locator('#meeting-notes').fill(value);self.save();self.notes_done()
            self.assertEqual(self.stored_notes()['text'],m.scheduler.notes.text(value))
            self.assertTrue(self.page.locator('#archive-meeting').is_enabled())
            self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.notes_ready()
            self.assertEqual(self.page.locator('#meeting-notes').input_value(),m.scheduler.notes.text(value))
            self.assertEqual(self.page.locator('#meeting-notes-row script').count(),0)
        self.assertFalse(self.errors);self.assertFalse(self.workflow_errors)

    def test_uncertain_notes_post_and_member_forged_receipt_never_duplicate_or_confirm_early(self):
        self.mode='pending';self.lost=True;self.open_editor();self.ready();self.notes_ready()
        self.page.locator('#meeting-notes').fill('PRIVATE NOTES CANARY — one request.')
        self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Request submitted.')")
        data=m.scheduler.parse(self.last_event['comment']['body'],m.web)
        target=m.scheduler.notes.document('meeting-4',data['request_id'],data['notes']['text'])
        fake=dict(schema_version=1,request_id=data['request_id'],comment_id=self.last_event['comment']['id'],
            request_hash=m.scheduler.digest(self.last_event['comment']['body']),meeting_id='meeting-4',state='saved',results=[],
            notes={'state':'saved','after_hash':m.scheduler.digest(target)})
        self.api.comments[4].append({'body':m.scheduler.STATUS+json.dumps(fake)+' -->','user':{'login':'member','type':'User'}})
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.assertNotEqual(self.page.locator('#submission-status').inner_text(),'Notes saved.')
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())
        self.process_batch();self.page.get_by_role('button',name='Check progress',exact=True).click();self.notes_done()
        self.assertEqual(self.posts,1)
        self.assertEqual(sum(comment['body'].startswith(m.scheduler.notes.MARKER) for comment in self.api.comments[4]),1)

    def test_notes_read_failure_can_be_retried_without_saving_an_empty_value(self):
        self.seed_notes('PRIVATE NOTES CANARY — retained.')
        self.hold_registration_read=True;self.open_editor();self.ready()
        self.assertTrue(self.page.locator('#meeting-notes').is_disabled())
        self.json_response(self.held_registration_route,{'message':'PRIVATE NOTES ERROR CANARY'},500)
        self.page.wait_for_function("() => document.getElementById('notes-status').textContent.includes('could not be loaded')")
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())
        self.assertNotIn('PRIVATE NOTES ERROR CANARY',self.page.content())
        self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.notes_ready()
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),'PRIVATE NOTES CANARY — retained.')
        self.assertEqual(self.posts,0)

    def test_archive_denies_revoked_role_and_clears_loaded_private_notes(self):
        self.seed_notes('PRIVATE NOTES CANARY — protected.')
        self.open_editor();self.ready();self.notes_ready()
        self.api.permissions['manager']='read'
        self.page.get_by_role('button',name='Archive Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertFalse(self.page.locator('#archive-meeting').is_visible())
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),'')
        self.assertEqual(self.posts,0)
        self.assertNotIn('archived',m.label_names(self.api.issues[4]))

    def test_archiving_failure_and_later_reactivation_are_not_overridden_by_retry(self):
        self.mode='sync-failure';self.open_editor();self.ready();self.notes_ready()
        self.page.get_by_role('button',name='Archive Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting archiving is not confirmed.')")
        self.assertEqual(self.posts,1);self.assertIn('archived',m.label_names(self.api.issues[4]))
        self.api.issues[4]['labels'].remove('archived')
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'reactivate'});self.flush_pages()
        self.mode='automatic';self.process_batch()
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('Archiving was not applied again')")
        self.assertEqual(m.registration_status(self.api.issues[4]),'active')
        self.assertEqual(self.posts,1)

    def test_archive_without_talks_works_with_keyboard_on_mobile(self):
        for number in (7,8):del self.api.issues[number]
        self.page.set_viewport_size({'width':375,'height':950})
        self.open_editor();self.ready();self.notes_ready()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),375)
        self.page.get_by_role('button',name='Archive Meeting',exact=True).focus();self.page.keyboard.press('Enter')
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting archived.')")
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())
        self.assertEqual(m.registration_status(self.api.issues[4]),'archived')
        self.assertEqual(self.posts,1)
        self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.notes_ready()
        self.assertTrue(self.page.locator('#archive-meeting').is_disabled())

    def test_notes_survive_hiding_and_restoring_the_meeting(self):
        self.seed_notes('PRIVATE NOTES CANARY — keep through restoration.')
        before=self.stored_notes()
        self.open_editor();self.ready();self.notes_ready()
        self.page.get_by_role('button',name='Hide Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertEqual(self.stored_notes(),before)
        self.api.issues[4]['labels'].remove('hidden')
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'sync'})
        self.api.issues[4]['labels'].remove('archived')
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'reactivate'});self.flush_pages()
        self.open_editor();self.ready();self.notes_ready()
        self.assertEqual(self.page.locator('#meeting-notes').input_value(),before['text'])

    def test_all_four_actions_appear_together_only_after_admin_verification(self):
        self.page.goto(self.base+'/prototype/schedule.html?meeting=meeting-4')
        self.page.wait_for_function("() => !document.getElementById('admin-fields').disabled")
        for id in ('save-schedule','reload-talks','hide-meeting','archive-meeting'):self.assertFalse(self.page.locator('#'+id).is_visible())
        self.page.locator('#admin-token').fill(TOKEN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        for id in ('save-schedule','reload-talks','hide-meeting','archive-meeting'):self.assertFalse(self.page.locator('#'+id).is_visible())
        self.open_editor();self.ready()
        boxes=[self.page.get_by_role('button',name=name,exact=True).bounding_box() for name in ('Save changes','Reload talks','Hide Meeting','Archive Meeting')]
        self.assertLess(max(box['y'] for box in boxes)-min(box['y'] for box in boxes),2)
        self.page.locator('#admin-token').fill('')
        for id in ('save-schedule','reload-talks','hide-meeting','archive-meeting'):self.assertFalse(self.page.locator('#'+id).is_visible())
        self.assertEqual(self.posts,0)

    def test_unsaved_talk_edits_must_be_saved_before_hiding_without_password_reentry(self):
        self.open_editor();self.ready()
        button=self.page.get_by_role('button',name='Hide Meeting',exact=True)
        self.assertTrue(button.is_enabled())
        for column,value in [(2,'13-02-2027'),(3,'10:30')]:
            self.field(7,column).fill(value)
            self.assertTrue(button.is_disabled())
            self.assertIn('Save your changes',self.page.locator('#hide-meeting-help').inner_text())
        button.dispatch_event('click')
        self.assertEqual(self.posts,0)
        self.save();self.done()
        self.assertEqual(m.web.parse(self.api.issues[7])['date'],'2027-02-13')
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'10:30')
        self.assertTrue(button.is_enabled())
        button.click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertEqual(self.posts,2)
        self.assertEqual(self.page.locator('#admin-token').input_value(),ADMIN)
        self.assertIn('hidden',m.label_names(self.api.issues[4]))
        self.assertEqual(self.page.request.get(self.base+'/prototype/meetings/meeting-4/').status,404)
        self.assertTrue(self.page.get_by_role('button',name='Reload talks',exact=True).is_disabled())
        self.assertTrue(button.is_disabled())
        self.assertFalse(any('/labels' in req['url'] or req['method'] in {'PATCH','DELETE'} for req in self.requests))
        self.page.get_by_role('link',name='Return to all meetings',exact=True).click()
        self.assertNotIn('data-meeting-id="meeting-4"',self.page.content())
        self.assertFalse(self.errors);self.assertFalse(self.workflow_errors)

    def test_unsaved_visibility_and_inflight_saves_block_meeting_hiding(self):
        self.mode='pending';self.open_editor();self.ready()
        button=self.page.get_by_role('button',name='Hide Meeting',exact=True)
        self.hidden_field(7).check();self.assertTrue(button.is_disabled())
        self.hidden_field(7).uncheck();self.assertTrue(button.is_enabled())
        self.field(7,3).fill('10:30');self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Request submitted.')")
        self.assertTrue(button.is_disabled());self.assertEqual(self.posts,1)
        button.dispatch_event('click');self.assertEqual(self.posts,1)
        self.process_batch();self.page.get_by_role('button',name='Check progress',exact=True).click();self.done()
        self.assertTrue(button.is_enabled())

    def test_equivalent_date_and_time_spellings_do_not_leave_hide_blocked_after_save(self):
        self.open_editor();self.ready();before=copy.deepcopy(self.api.issues[7])
        self.field(7,2).fill('12-2-27');self.field(7,3).fill('9:00')
        button=self.page.get_by_role('button',name='Hide Meeting',exact=True)
        self.assertTrue(button.is_disabled())
        self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent === 'No scheduling changes to save.'")
        self.assertTrue(button.is_enabled());self.assertEqual(self.posts,0)
        self.assertEqual(self.api.issues[7],before)
        button.click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertEqual(self.posts,1)

    def test_empty_meeting_can_be_hidden_and_unsaved_cancellation_restores_availability(self):
        self.open_editor();self.ready();button=self.page.get_by_role('button',name='Hide Meeting',exact=True)
        self.field(7,3).fill('10:30');self.assertTrue(button.is_disabled())
        self.field(7,3).fill('09:00');self.assertTrue(button.is_enabled())
        for number in (7,8):del self.api.issues[number]
        self.page.get_by_role('button',name='Reload talks',exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('hide-meeting').disabled")
        self.assertTrue(self.page.get_by_role('button',name='Save changes',exact=True).is_enabled())
        self.assertEqual(self.page.locator('#schedule-rows tr').count(),0)
        button.click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertEqual(self.posts,1)

    def test_role_revoked_after_loading_cannot_hide_a_meeting(self):
        self.open_editor();self.ready();self.api.permissions['manager']='read'
        self.page.get_by_role('button',name='Hide Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertFalse(self.page.locator('#hide-meeting').is_visible())
        self.assertEqual(self.posts,0);self.assertNotIn('hidden',m.label_names(self.api.issues[4]))

    def test_lost_hiding_response_and_spoofed_receipt_do_not_duplicate_or_confirm_early(self):
        self.mode='pending';self.lost=True;self.open_editor();self.ready()
        self.page.get_by_role('button',name='Hide Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Request submitted.')")
        data=m.scheduler.parse(self.last_event['comment']['body'],m.web)
        fake=dict(schema_version=1,operation='hide-meeting',request_id=data['request_id'],comment_id=self.last_event['comment']['id'],
            request_hash=m.scheduler.digest(self.last_event['comment']['body']),meeting_id='meeting-4',state='synchronized',
            results=[{'number':4,'state':'saved'}],revision='b'*40)
        self.api.comments[4].append({'body':m.scheduler.STATUS+json.dumps(fake)+' -->','user':{'login':'member','type':'User'}})
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.assertNotEqual(self.page.locator('#submission-status').inner_text(),'Meeting hidden.')
        self.process_batch();self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertEqual(self.posts,1)

    def test_hiding_sync_failure_is_not_reported_as_success_and_can_be_recovered(self):
        self.mode='sync-failure';self.open_editor();self.ready()
        self.page.get_by_role('button',name='Hide Meeting',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hiding is not confirmed.')")
        self.assertEqual(self.posts,1);self.assertIn('hidden',m.label_names(self.api.issues[4]))
        self.assertTrue(self.page.get_by_role('button',name='Hide Meeting',exact=True).is_disabled())
        self.mode='automatic';self.process_batch()
        self.page.get_by_role('button',name='Check progress',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertEqual(self.posts,1)

    def test_archived_meeting_hiding_works_with_keyboard_on_mobile(self):
        self.api.issues[7]['labels'].append('talk-hidden')
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'archive'});self.flush_pages()
        self.page.set_viewport_size({'width':390,'height':844})
        self.open_editor();self.ready()
        self.page.get_by_role('button',name='Hide Meeting',exact=True).focus();self.page.keyboard.press('Enter')
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Meeting hidden.')")
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.assertIn('talk-hidden',m.label_names(self.api.issues[7]))
        self.assertTrue(self.api.issues[4]['locked']);self.assertEqual(self.api.issues[4]['state'],'closed')


    def test_registered_names_are_private_sorted_and_precede_dates_and_instructions(self):
        self.api.comments[4].extend([self.attendance('Zoë PRIVATE CANARY'),self.attendance('Alice PRIVATE CANARY',1002,owner=51)])
        self.api.comments[10].append(self.attendance('Other meeting PRIVATE CANARY',1003,ident='meeting-10'))
        self.page.goto(self.base+'/prototype/schedule.html?meeting=meeting-4')
        self.assertFalse(self.page.locator('#registered-people').is_visible())
        self.page.wait_for_function("() => !document.getElementById('admin-fields').disabled")
        self.assertFalse(any('/comments?' in record['url'] for record in self.requests))
        self.open_editor();self.ready();self.registered('Alice PRIVATE CANARY, Zoë PRIVATE CANARY')
        line=self.page.locator('#registered-people')
        self.assertEqual(line.inner_text(),'Registered: Alice PRIVATE CANARY, Zoë PRIVATE CANARY')
        self.assertEqual(line.evaluate('node=>node.nextElementSibling.id'),'meeting-notes-row')
        self.assertTrue(self.page.locator('#meeting-dates').evaluate('node=>node.nextElementSibling.textContent.startsWith("Use ")'))
        self.assertEqual(line.locator('strong').inner_text(),'Registered:')
        self.assertEqual(self.page.locator('#meeting-dates strong').inner_text(),'When:')
        self.assertGreater(int(line.locator('strong').evaluate('node=>getComputedStyle(node).fontWeight')),400)
        self.assertNotIn('Other meeting',line.inner_text())
        public='\n'.join(value for value in self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH).values() if isinstance(value,str))
        for secret in ('Alice PRIVATE CANARY','Zoë PRIVATE CANARY','f'*64):self.assertNotIn(secret,public)
        self.assertEqual(self.posts,0)

    def test_registration_and_unregistration_forms_are_reflected_after_reload(self):
        self.install_roster(['José Example'], [])
        self.open_editor();self.ready();self.registered('None yet.')
        member=self.context.new_page();member.goto(self.base+'/prototype/participation.html?meeting=meeting-4')
        member.wait_for_function("() => !document.getElementById('participation-fields').disabled")
        member.locator('#participant-name').select_option('José Example')
        member.locator('#github-token').fill(TOKEN)
        member.get_by_role('button',name='Check credentials',exact=True).click()
        member.wait_for_function("() => document.getElementById('identity').textContent === 'Credentials accepted.'")
        member.get_by_role('radio',name='Register',exact=True).check();member.get_by_role('button',name='Submit',exact=True).click()
        member.wait_for_function("() => document.getElementById('submission-status').textContent === 'Registration confirmed.'")
        self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.registered('José Example')
        member.get_by_role('radio',name='Unregister',exact=True).check();member.get_by_role('button',name='Submit',exact=True).click()
        member.wait_for_function("() => document.getElementById('submission-status').textContent === 'Unregistration confirmed.'")
        self.page.get_by_role('button',name='Reload talks',exact=True).click();self.ready();self.registered('None yet.')
        self.assertFalse(self.errors);self.assertFalse(self.workflow_errors);member.close()

    def test_registration_read_supports_pagination_all_accounts_and_older_named_formats(self):
        self.api.comments[4].extend(self.attendance(f'Person {index:03}',1000+index,owner=10+index) for index in reversed(range(150)))
        self.api.comments[4].extend([self.attendance('old.member',2001,schema=1),self.attendance('Older Named Member',2002,schema=2)])
        self.open_editor();self.ready();self.registered('Person 149')
        text=self.page.locator('#registered-people').inner_text()
        self.assertIn('old.member',text);self.assertIn('Older Named Member',text)
        self.assertLess(text.index('Person 000'),text.index('Person 149'))
        self.assertTrue(any('/comments?' in request['url'] and 'page=2' in request['url'] for request in self.requests))

    def test_duplicate_names_invalid_comments_and_html_are_handled_without_guessing(self):
        first=self.attendance('Zoë PRIVATE MEMBER')
        duplicate=self.attendance('ZOE\u0308 PRIVATE MEMBER',1002,owner=51)
        wrong=self.attendance('Wrong association',1003,ident='meeting-10')
        withdrawn=self.attendance('Withdrawn name',1004);withdrawn['body']=withdrawn['body'].replace('Yes —','No —',1)
        bot=self.attendance('System name',1005);bot['user']['type']='Bot'
        html=self.attendance('<script>alert(1)</script>',1006)
        self.api.comments[4].extend([first,duplicate,wrong,withdrawn,bot,html,{'id':1007,'body':'Yes','user':first['user']}])
        self.open_editor();self.ready();self.registered('Duplicate registration records need review.')
        text=self.page.locator('#registered-people').inner_text()
        self.assertIn('Zoë PRIVATE MEMBER',text);self.assertNotIn('ZOE\u0308 PRIVATE MEMBER',text)
        for ignored in ('Wrong association','Withdrawn name','System name'):self.assertNotIn(ignored,text)
        self.assertIn('<script>alert(1)</script>',text);self.assertEqual(self.page.locator('#registered-people script').count(),0)
        self.assertFalse(self.errors)

    def test_earlier_reactions_require_review_and_do_not_invent_person_names(self):
        self.reactions=[{'content':'+1','user':{'login':'private-old-login','id':77}}]
        self.open_editor();self.ready();self.registered('Some earlier registrations need review.')
        text=self.page.locator('#registered-people').inner_text()
        self.assertNotIn('private-old-login',text);self.assertNotIn('None yet',text)

    def test_registration_failure_does_not_clear_or_block_schedule_edits(self):
        self.reaction_error=500;self.open_editor();self.ready();self.registered('Could not load registrations.')
        self.field(7,3).fill('10:30');self.save();self.done()
        self.assertEqual(m.web.parse(self.api.issues[7])['time'],'10:30')
        self.assertNotIn('None yet',self.page.locator('#registered-people').inner_text())

    def test_late_registration_response_never_discards_unsaved_talk_edits(self):
        self.hold_registration_read=True;self.open_editor();self.ready()
        self.assertIsNotNone(self.held_registration_route)
        self.registered('Loading…')
        self.field(7,3).fill('10:30')
        self.json_response(self.held_registration_route,[self.attendance('Late PRIVATE MEMBER')])
        self.registered('Late PRIVATE MEMBER')
        self.assertEqual(self.field(7,3).input_value(),'10:30')
        self.assertTrue(self.page.locator('#hide-meeting').is_disabled());self.assertEqual(self.posts,0)

    def test_stale_registration_response_cannot_reappear_after_credentials_are_cleared(self):
        self.hold_registration_read=True;self.open_editor();self.ready()
        self.page.locator('#admin-token').fill('')
        self.json_response(self.held_registration_route,[self.attendance('STALE PRIVATE MEMBER')])
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator('#registered-names').text_content(),'')
        self.assertFalse(self.page.locator('#registered-people').is_visible())
        self.assertNotIn('STALE PRIVATE MEMBER',self.page.content())

    def test_archived_meeting_still_reports_registrations_without_reopening_it(self):
        self.api.comments[4].append(self.attendance('Archived PRIVATE MEMBER'))
        m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'archive'});self.flush_pages()
        self.open_editor();self.ready();self.registered('Archived PRIVATE MEMBER')
        self.assertEqual(self.api.issues[4]['state'],'closed');self.assertTrue(self.api.issues[4]['locked'])
        self.assertIn('archived',m.label_names(self.api.issues[4]));self.assertEqual(self.posts,0)


if __name__ == '__main__': unittest.main()
