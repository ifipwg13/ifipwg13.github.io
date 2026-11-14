"""Own-site Admin -> trusted group update -> static Home, fictitious credentials."""
import copy
import json
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
import unittest

from browser_talk_submission import FormBrowserFixture, TOKEN, API, ROOT, m
import test_group_profile as profile_tests

g=m.profile
ADMIN='github_pat_GROUP_ADMIN_FICTITIOUS_ONLY'


class GroupAdminBrowserTests(FormBrowserFixture):
    def setUp(self):
        super().setUp()
        self.api=profile_tests.GroupGitHub()
        files=self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
        files['index.html']=g.render((ROOT/'index.html').read_text(),profile_tests.PEOPLE,1)
        files['prototype/admin.html']=(ROOT/'prototype/admin.html').read_text()
        files['members/index.html']=(ROOT/'members/index.html').read_text()
        self.flush_pages()
        self.base=f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        self.mode='automatic'; self.lost=False; self.auth_error=None; self.post_error=None
        self.workflow_errors=[]; self.last_event=None

    def route(self,route):
        request=route.request
        if not request.url.startswith(API+'/'):return super().route(route)
        url=urlsplit(request.url)
        self.requests.append({'method':request.method,'url':request.url,'headers':request.headers,'body':request.post_data})
        if request.method=='OPTIONS':
            route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET, POST',
                'Access-Control-Allow-Headers':'authorization,content-type,x-github-api-version'});return
        self.assertIn(request.headers.get('authorization'),{'Bearer '+ADMIN,'Bearer '+TOKEN})
        for secret in (ADMIN,TOKEN): self.assertNotIn(secret,request.url); self.assertNotIn(secret,request.post_data or '')
        owner={'login':'manager' if request.headers['authorization']=='Bearer '+ADMIN else 'member','id':1,'type':'User'}
        root='/repos/'+m.PRIVATE; path=url.path
        if self.auth_error:self.json_response(route,{'message':'PRIVATE RESPONSE CANARY'},self.auth_error)
        elif path=='/user':self.json_response(route,owner)
        elif path==root:self.json_response(route,{'full_name':m.PRIVATE,'permissions':{'pull':True}})
        elif path==root+'/collaborators/'+owner['login']+'/permission':self.json_response(route,{'permission':self.api.permissions[owner['login']]})
        elif path==root+'/issues':
            self.assertEqual(request.method,'GET')
            query=parse_qs(url.query); names=query['labels'][0].split(',')
            records=[self.api.issue_record(issue) for issue in self.api.issues.values() if all(name in m.label_names(issue) for name in names) and issue['state']=='open']
            page=int(query.get('page',['1'])[0]); self.json_response(route,records[(page-1)*100:page*100])
        elif path==root+f'/issues/{g.control_number()}/comments':
            if request.method=='POST':
                self.posts+=1
                if self.post_error:self.json_response(route,{'message':'PRIVATE POST CANARY'},self.post_error);return
                comment=self.api.api('POST',path.lstrip('/'),request.post_data_json)
                comment['user']=owner; self.api.comments[g.control_number()][-1]['user']=owner
                self.last_event={'repository':{'full_name':m.PRIVATE},'sender':owner,'action':'created',
                                 'issue':{'number':g.control_number()},'comment':comment}
                if self.mode!='pending':self.process_update()
                if self.lost:route.abort('failed')
                else:self.json_response(route,comment,201)
            else:
                comments=copy.deepcopy(self.api.comments[g.control_number()])
                for comment in comments:
                    if not comment['body'].startswith(g.STATUS):continue
                    data=json.loads(comment['body'][len(g.STATUS):comment['body'].index(' -->')])
                    if 'revision' in data:data['revision']='b'*40
                    comment['body']=g.STATUS+json.dumps(data)+' -->\nStatus'
                page=int(parse_qs(url.query).get('page',['1'])[0]); self.json_response(route,comments[(page-1)*100:page*100])
        else:raise AssertionError('Unexpected browser API: '+path)

    def process_update(self):
        try:
            request=m.authorize(self.api,self.last_event,'issue_comment')
            if self.mode=='verification-failure':
                real=g.verify_home
                def fail(home,text):
                    if g.parse_document(text)[1]>1:raise g.ProfileError('Fictitious verification failure')
                    return real(home,text)
                with patch.object(g,'verify_home',side_effect=fail):m.prepare(self.api,request,reader=self.api)
            else:m.prepare(self.api,request,reader=self.api)
        except m.SetupError as failure:self.workflow_errors.append(str(failure))
        self.flush_pages()

    def open_admin(self,credential=ADMIN):
        self.page.goto(self.base+'/prototype/admin.html')
        self.page.locator('#admin-token').fill(credential)
        self.page.get_by_role('button',name='Check credentials',exact=True).click()
    def ready(self):self.page.wait_for_function("() => !document.getElementById('save-people').disabled")
    def save(self):self.page.get_by_role('button',name='Save changes',exact=True).click()
    def done(self):self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Home lists updated.')")

    def test_navigation_prefill_unicode_save_and_static_home(self):
        self.page.goto(self.base+'/')
        self.assertEqual(self.page.get_by_role('navigation').get_by_role('link').all_text_contents(),['Home','Meetings','Admin'])
        self.page.get_by_role('link',name='Admin',exact=True).click()
        self.assertEqual(self.page.locator('textarea').count(),4)
        self.assertTrue(self.page.locator('#current-chairs').is_disabled())
        self.page.locator('#admin-token').fill(ADMIN);self.page.get_by_role('button',name='Check credentials',exact=True).click();self.ready()
        for key,id in {'current_chairs':'current-chairs','past_chairs':'past-chairs','members':'members','emeriti':'emeriti'}.items():
            self.assertEqual(self.page.locator('#'+id).input_value(),'\n'.join(profile_tests.PEOPLE[key]))
        before=set(self.api.issues)
        self.page.locator('#current-chairs').fill('Zoë Müller\n李明')
        self.page.locator('#past-chairs').fill('José Example')
        self.page.locator('#members').fill('Zoë Müller\n\nRene\u0301 Example\nÖlveczky, Example (NO)')
        self.page.locator('#emeriti').fill('')
        self.save();self.done()
        self.assertEqual(self.posts,1);self.assertEqual(set(self.api.issues),before)
        self.page.get_by_role('link',name='Return to Home',exact=True).click()
        self.assertEqual(self.page.locator('[data-group-list="members"] li').all_text_contents(),['Zoë Müller','René Example','Ölveczky, Example (NO)'])
        self.assertEqual(self.page.locator('[data-group-list="emeriti"] li').count(),0)
        self.assertFalse(self.errors);self.assertFalse(self.workflow_errors)
        self.assertFalse(any('/contents/' in r['url'] or r['method'] in {'PATCH','DELETE'} for r in self.requests))

    def test_reload_reuses_password_and_order_and_all_empty_lists_are_supported(self):
        self.open_admin();self.ready();self.page.locator('#members').fill('B. Example\nA. Example');self.save();self.done()
        self.page.get_by_role('button',name='Reload lists',exact=True).click();self.ready()
        self.assertEqual(self.page.locator('#members').input_value(),'B. Example\nA. Example')
        self.assertEqual(self.page.locator('#admin-token').input_value(),ADMIN)
        for id in ('current-chairs','past-chairs','members','emeriti'):self.page.locator('#'+id).fill('')
        self.save();self.done()
        values=g.parse_document(self.api.file(m.PUBLIC,g.DATA_PATH,m.PREVIEW_BRANCH))[0]
        self.assertTrue(all(not names for names in values.values()))

    def test_read_credentials_and_role_revoked_before_save_cannot_write(self):
        self.open_admin(TOKEN)
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertTrue(self.page.locator('#members').is_disabled());self.assertEqual(self.posts,0)
        self.open_admin();self.ready();self.page.locator('#members').fill('Changed')
        self.api.permissions['manager']='read';self.save()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('requires administrator')")
        self.assertEqual(self.posts,0)

    def test_loading_failure_disables_save_and_reload_recovers_without_empty_overwrite(self):
        original=self.api.file(m.PUBLIC,'index.html',m.PREVIEW_BRANCH)
        files=self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
        files['index.html']=original.replace('group-people-revision','missing-revision');self.flush_pages()
        self.open_admin()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('could not be loaded')")
        self.assertTrue(self.page.locator('#save-people').is_disabled())
        self.assertTrue(self.page.get_by_role('button',name='Reload lists',exact=True).is_enabled())
        files['index.html']=original;self.flush_pages()
        self.page.get_by_role('button',name='Reload lists',exact=True).click();self.ready()
        self.assertEqual(self.page.locator('#members').input_value(),'\n'.join(profile_tests.PEOPLE['members']))
        self.assertEqual(self.posts,0)

    def test_missing_or_ambiguous_control_record_disables_save(self):
        self.api.issues[g.control_number()+1]=copy.deepcopy(self.api.issues[g.control_number()])|{'number':g.control_number()+1}
        self.open_admin()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('ambiguous')")
        self.assertTrue(self.page.locator('#save-people').is_disabled());self.assertEqual(self.posts,0)

    def test_plain_text_html_is_escaped_and_controls_or_credentials_rejected(self):
        self.open_admin();self.ready()
        for value in ('bad\x01name','x'*201,ADMIN):
            self.page.locator('#members').fill(value);self.save()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertEqual(self.posts,0)
        self.page.locator('#members').fill('<script>alert("x")</script>\nÄnne & José ✝');self.save();self.done()
        self.page.get_by_role('link',name='Return to Home',exact=True).click()
        self.assertEqual(self.page.locator('[data-group-list="members"] li').all_text_contents(),['<script>alert("x")</script>','Änne & José ✝'])
        self.assertEqual(self.page.locator('script').count(),0);self.assertFalse(self.errors)

    def test_concurrent_profile_edit_conflicts_and_reload_reads_newer_lists(self):
        self.open_admin();self.ready();self.page.locator('#members').fill('Stale editor changes')
        newer=profile_tests.PEOPLE|{'past_chairs':['A newer Unicode ä correction']}
        files=self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
        files[g.DATA_PATH]=g.document(newer,2);files['index.html']=g.render(files['index.html'],newer,2);self.flush_pages()
        self.save();self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('The lists changed elsewhere.')")
        self.assertEqual(g.parse_document(self.api.file(m.PUBLIC,g.DATA_PATH,m.PREVIEW_BRANCH))[0],newer)
        self.page.get_by_role('button',name='Reload lists',exact=True).click();self.ready()
        self.assertEqual(self.page.locator('#past-chairs').input_value(),'A newer Unicode ä correction')

    def test_lost_post_and_double_click_do_not_duplicate_updates(self):
        self.lost=True;self.open_admin();self.ready();self.page.locator('#members').fill('Lost response recovery ä')
        self.save();self.done();self.assertEqual(self.posts,1)
        self.assertEqual(g.parse_document(self.api.file(m.PUBLIC,g.DATA_PATH,m.PREVIEW_BRANCH))[1],2)
        self.page.get_by_role('button',name='Save changes',exact=True).evaluate('node=>{node.disabled=false;node.click();node.click();}')
        self.assertEqual(self.posts,1)

    def test_failed_verification_not_reported_as_saved_and_retry_recovers(self):
        self.mode='verification-failure';self.open_admin();self.ready();self.page.locator('#members').fill('A corrected é name');self.save()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('The update needs administrator attention.')")
        self.assertNotIn('Home lists updated',self.page.locator('#submission-status').inner_text())
        self.mode='automatic';self.process_update()
        self.page.get_by_role('button',name='Check progress',exact=True).click();self.done()
        self.assertEqual(self.posts,1)

    def test_credential_change_reload_mobile_and_storage(self):
        self.open_admin();self.ready();self.page.locator('#members').fill('Changed')
        self.page.locator('#admin-token').evaluate("node=>{node.value='silently-changed-password';}");self.save()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Check the original administrator')")
        self.assertEqual(self.posts,0)
        self.page.reload();self.assertEqual(self.page.locator('#admin-token').input_value(),'')
        self.page.set_viewport_size({'width':375,'height':950})
        self.page.locator('#admin-token').fill(ADMIN);self.page.get_by_role('button',name='Check credentials',exact=True).click();self.ready()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),375)
        self.assertEqual(self.page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length'),0)
        self.assertNotIn('PRIVATE RESPONSE CANARY',self.page.content())

    def test_unchanged_and_blank_line_only_edits_send_no_request(self):
        self.open_admin();self.ready()
        self.page.locator('#members').fill('\n  '+'\n\n'.join(profile_tests.PEOPLE['members'])+'\n')
        self.save();self.page.wait_for_function("() => document.getElementById('submission-status').textContent==='No list changes to save.'")
        self.assertEqual(self.posts,0)


if __name__=='__main__':unittest.main()
