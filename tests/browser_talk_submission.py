"""Browser + trusted Python intake/publisher integration; fictitious data only.

No live GitHub writes or real tokens. Run with both repositories checked out:
  python3 tests/browser_talk_submission.py
"""
import copy
import base64
import functools
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = Path(os.environ.get("MEETINGS_CHECKOUT", ROOT.parent / "meetings"))
sys.path.insert(0, str(PRIVATE_ROOT / "tests"))
from test_web_talks import WebGitHub, proposal, m  # noqa: E402
from shared_member_fixtures import SharedGitHub, install_retired_directory
from test_meeting_setup import DETAILS, form_body  # noqa: E402
from test_talk_slides import stage, example_pdf  # noqa: E402

TOKEN = "github_pat_FICTITIOUS_TEST_ONLY_123456"
SECOND_TOKEN = "github_pat_SECOND_FICTITIOUS_TEST_ONLY"
API = "https://api.github.com"
preview_spec = importlib.util.spec_from_file_location('talk_preview', ROOT / 'scripts/preview_server.py')
preview = importlib.util.module_from_spec(preview_spec)
preview_spec.loader.exec_module(preview)


class PreviewSource:
    """Serve the same changing fixture through the actual Codespaces handler."""
    branch = preview.BRANCH
    commit = 'a' * 40

    def __init__(self, directory):
        self.directory = directory

    def read(self, path):
        return (self.directory / path).read_bytes()

    def page(self, path):
        return preview.styled_preview(self.read(path), self.read('prototype/assets/style.css'), self.commit,
                                      self.read('prototype/assets/meetings-list.js'), self.read(preview.LOGO_PATH), self.branch), self.commit

    def synchronized(self):
        return self


class QuietFiles(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class FormBrowserFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=shutil.which("chromium"), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        shutil.copytree(ROOT / "prototype/assets", self.directory / "prototype/assets")
        shutil.copy(ROOT / "prototype/submit-talk.html", self.directory / "prototype/submit-talk.html")
        self.api = SharedGitHub()
        files = self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH)
        files['prototype/index.html'] = files['prototype/index.html'].replace('<html><body>',
            '<html><head><link rel="stylesheet" href="assets/style.css"></head><body>')
        m.prepare(self.api, m.authorize(self.api, self.api.request(4), "issues"))
        m.prepare(self.api, m.authorize(self.api, self.api.request(10, DETAILS | {"name": "Second fictitious meeting"}), "issues"))
        self.flush_pages()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietFiles, directory=str(self.directory)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.preview = preview.make_server(PreviewSource(self.directory), host='127.0.0.1', port=0)
        threading.Thread(target=self.preview.serve_forever, daemon=True).start()
        self.addCleanup(self.preview.server_close)
        self.addCleanup(self.preview.shutdown)
        self.context = self.browser.new_context(viewport={"width": 1100, "height": 950})
        self.addCleanup(self.context.close)
        self.requests = []
        self.external = []
        self.errors = []
        self.posts = 0
        self.upload_posts = 0
        self.upload_mode = 'success'
        self.upload_commit = None
        self.response_mode = "success"
        self.status_mode = "automatic"
        self.context.route("**/*", self.route)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def flush_pages(self):
        files = self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH)
        for old in self.directory.glob('prototype/slides/*/*.pdf'):
            if str(old.relative_to(self.directory)) not in files:
                old.unlink()
        for name, value in files.items():
            path = self.directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value) if isinstance(value, bytes) else path.write_text(value)

    def json_response(self, route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body),
                      headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc.startswith("127.0.0.1:"):
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn(TOKEN, request.url)
            route.continue_()
            return
        if not request.url.startswith(API + "/"):
            self.external.append(request.url)
            route.abort()
            return
        self.requests.append({"method": request.method, "url": request.url, "headers": request.headers,
                              "body": request.post_data})
        if request.method == "OPTIONS":
            route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, PUT",
                          "Access-Control-Allow-Headers": "authorization,content-type,x-github-api-version"})
            return
        self.assertIn(request.headers.get("authorization"), {"Bearer " + TOKEN, "Bearer " + SECOND_TOKEN})
        for credential in (TOKEN, SECOND_TOKEN):
            self.assertNotIn(credential, request.url)
            self.assertNotIn(credential, request.post_data or "")
        path = url.path
        upload_root = '/repos/' + m.web.UPLOADS
        if path.startswith(upload_root + '/'):
            if request.method == 'PUT':
                self.upload_posts += 1
                self.assertTrue(path.startswith(upload_root + '/contents/submissions/'))
                if self.upload_mode == '403':
                    self.json_response(route, {'message':'PRIVATE DENIAL'}, 403); return
                if self.upload_mode == 'lost-before-upload':
                    route.abort('failed'); return
                data = request.post_data_json
                self.assertEqual(set(data), {'message','branch','content'})
                self.assertEqual(data['branch'], 'main')
                submission = path.rsplit('/',1)[1].removesuffix('.pdf')
                content = base64.b64decode(data['content'])
                reference = stage(self.api, content, submission)
                self.upload_commit = reference['commit']
                metadata = self.api.api('GET', f"repos/{m.web.UPLOADS}/contents/{reference['path']}?ref={self.upload_commit}")
                if self.upload_mode == 'lost-response': route.abort('failed')
                else: self.json_response(route, {'content':metadata,'commit':{'sha':self.upload_commit}}, 201)
            elif path == upload_root + '/git/ref/heads/main':
                if self.upload_commit: self.json_response(route, {'object':{'sha':self.upload_commit}})
                else: self.json_response(route, {}, 404)
            elif '/contents/submissions/' in path:
                metadata = self.api.api('GET', path.lstrip('/') + '?' + url.query, missing_ok=True)
                self.json_response(route, metadata or {}, 200 if metadata else 404)
            else: raise AssertionError('Unsupported upload operation: ' + path)
            return
        if path == "/user":
            if self.response_mode in {"401", "403", "404"}:
                self.json_response(route, {}, int(self.response_mode))
            else:
                self.json_response(route, {"login": "member", "id": 11})
        elif path == "/repos/ifipwg13/meetings":
            repo = {"full_name": m.PRIVATE}
            if self.response_mode != "metadata-only":
                repo["permissions"] = {"pull": True, "push": False, "admin": False}
            self.json_response(route, repo)
        elif path == "/repos/ifipwg13/meetings/issues" and request.method == "POST":
            self.posts += 1
            if self.response_mode == "post-403":
                self.json_response(route, {}, 403)
                return
            data = request.post_data_json
            self.assertEqual(set(data), {"title", "body"})
            number = max(self.api.issues) + 1
            self.api.issues[number] = proposal(number) | data
            self.api.issues[number]["labels"] = []
            self.last_number = number
            if self.status_mode == "automatic":
                self.process(number)
            if self.response_mode == "lost-response": route.abort("failed")
            else: self.json_response(route, {"number": number}, 201)
        elif path == "/repos/ifipwg13/meetings/issues":
            records = [copy.deepcopy(issue) for issue in self.api.issues.values() if issue.get("user", {}).get("login") == "member"]
            self.json_response(route, records)
        elif path.endswith("/comments"):
            number = int(path.split("/")[-2])
            comments = copy.deepcopy(self.api.comments.get(number, []))
            for comment in comments:
                # The REST model uses symbolic commit IDs. Real GitHub uses SHA-1.
                if m.web.STATUS_MARKER in comment["body"]:
                    start = len(m.web.STATUS_MARKER)
                    end = comment["body"].index(" -->")
                    data = json.loads(comment["body"][start:end])
                    if "revision" in data: data["revision"] = "a" * 40
                    comment["body"] = m.web.STATUS_MARKER + json.dumps(data) + " -->\nStatus"
            self.json_response(route, comments)
        else:
            raise AssertionError("Unexpected API path: " + path)

    def process(self, number):
        event = {"repository": {"full_name": m.PRIVATE}, "sender": {"login": "member"},
                 "action": "opened", "issue": {"number": number}}
        m.prepare(self.api, m.authorize(self.api, event, "issues"), reader=self.api)
        self.flush_pages()

    def open_form(self, ident="meeting-4", ready=True):
        self.page.goto(self.base + "/prototype/submit-talk.html" + ("?meeting=" + ident if ident is not None else ""))
        if ready:
            self.page.wait_for_function("() => !document.getElementById('talk-fields').disabled")
        self.assertFalse(self.page.locator("#check-status").is_visible())
        self.assertFalse(self.page.locator("#meeting-link").is_visible())

    def credentials(self, credential=TOKEN):
        self.page.locator("#github-token").fill(credential)
        self.page.get_by_role("button", name="Check credentials", exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('submit-talk').disabled")
        self.assertEqual('Credentials accepted.', self.page.locator('#identity').inner_text())

    def fill_talk(self, title="Fictitious trees", authors="A. Example", abstract="A fictitious abstract.\nSecond line."):
        self.page.locator("#talk-title").fill(title)
        self.page.locator("#authors").fill(authors)
        self.page.locator("#abstract").fill(abstract)

    def wait_published(self):
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('Your talk is published')")



class FormBrowserTests(FormBrowserFixture):
    def test_retired_directory_never_controls_submission_or_leaks_names(self):
        install_retired_directory(self.api)
        self.open_form(); self.credentials(); self.fill_talk()
        self.page.get_by_role('button', name='Submit talk', exact=True).click(); self.wait_published()
        self.assertEqual(self.posts, 1)
        self.assertNotIn('PRIVATE DIRECTORY CANARY', self.page.content())
        self.assertFalse(any('participant-directory' in r['url'] or '/issues/900' in r['url'] for r in self.requests))

    def test_two_submissions_need_no_name_and_do_not_publish_account_information(self):
        numbers = []
        for title in ['First fictitious contribution','Second fictitious contribution']:
            self.open_form(); self.credentials(); self.fill_talk(title)
            self.page.get_by_role('button', name='Submit talk', exact=True).click(); self.wait_published()
            numbers.append(self.last_number)
            data = m.web.parse(self.api.issues[self.last_number])
            self.assertNotIn('participant', data)
            self.assertEqual(self.page.locator('#participant-name').count(), 0)
        self.assertNotEqual(*numbers)
        self.assertEqual(self.api.issues[numbers[0]]['user'], self.api.issues[numbers[1]]['user'])
        public = '\n'.join(self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH).values())
        for value in ['PRIVATE Alice Example','PRIVATE Bob Example','credential_fingerprint',hashlib.sha256(TOKEN.encode()).hexdigest()]:
            self.assertNotIn(value, public)
        self.assertNotIn('GitHub', self.page.locator('body').inner_text())

    def test_silent_password_autofill_cannot_reuse_checked_credentials(self):
        self.open_form()
        self.credentials(); self.fill_talk()
        self.page.locator('#github-token').evaluate("node => {node.value='changed-password';}")
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Check credentials')")
        self.assertEqual(self.posts, 0)

    def test_pending_talk_cannot_be_checked_with_another_password_on_same_account(self):
        self.status_mode = 'pending'
        self.open_form(); self.credentials(); self.fill_talk()
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Submitted.')")
        self.page.locator('#github-token').fill(SECOND_TOKEN)
        self.page.get_by_role('button', name='Check credentials', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('original password')")
        self.assertEqual(self.posts, 1)
        self.assertTrue(self.page.locator('#submit-talk').is_disabled())

    def test_pending_talk_can_be_checked_again_using_original_password(self):
        self.status_mode = 'pending'
        self.open_form(); self.credentials(); self.fill_talk()
        self.page.get_by_role('button',name='Submit talk',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Submitted.')")
        self.page.locator('#github-token').fill('')
        self.page.locator('#github-token').fill(TOKEN)
        self.page.get_by_role('button',name='Check credentials',exact=True).click()
        self.page.wait_for_function("() => document.getElementById('identity').textContent === 'Credentials accepted.'")
        self.page.get_by_role('button',name='Check submission status',exact=True).click()
        self.assertEqual(self.posts,1)

    def test_credentials_changed_during_availability_refresh_abort_before_post(self):
        self.open_form(); self.credentials(); self.fill_talk()
        def change_credentials(route):
            self.page.locator('#github-token').evaluate("node => { node.value = 'changed-password'; node.dispatchEvent(new Event('input', {bubbles:true})); }")
            route.fulfill(status=200, content_type='text/html', body=(self.directory / 'prototype/index.html').read_text())
        self.context.route('**/prototype/index.html', change_credentials)
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.page.wait_for_function("() => document.getElementById('form-error').textContent.includes('Check credentials')")
        self.assertEqual(self.posts, 0)
        self.assertTrue(self.page.locator('#submit-talk').is_disabled())
        self.assertFalse(self.errors)

    def multi_day(self):
        details = DETAILS | {'end_date': '2027-02-14'}
        self.api.issues[4]['body'] = m.meeting_registration_intro('meeting-4', details) + form_body(details)
        m.manage_meeting(self.api, {'number': 4, 'id': 'meeting-4', 'action': 'sync'})
        self.flush_pages()

    def test_default_time_and_automatic_single_day_date_are_sent(self):
        self.open_form()
        self.assertEqual(self.page.locator('#talk-time').input_value(), '09:00')
        self.assertFalse(self.page.locator('#talk-date-field').is_visible())
        self.credentials()
        self.fill_talk()
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.wait_published()
        data = m.web.parse(self.api.issues[self.last_number])
        self.assertEqual((data['date'], data['time']), (DETAILS['date'], '09:00'))

    def test_multi_day_date_and_time_normalization_then_public_display(self):
        self.multi_day()
        self.open_form()
        self.assertTrue(self.page.locator('#talk-date-field').is_visible())
        self.assertEqual(self.page.locator('#talk-date').input_value(), '12-02-2027')
        self.page.locator('#talk-date').fill('14-2-27')
        self.page.locator('#talk-time').fill('9:05')
        self.credentials()
        self.fill_talk()
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.wait_published()
        data = m.web.parse(self.api.issues[self.last_number])
        self.assertEqual((data['date'], data['time']), ('2027-02-14', '09:05'))
        self.page.get_by_role('link', name='Return to meeting').click()
        self.assertEqual(self.page.locator('.talk-date').inner_text(), '14-02-2027')
        self.assertEqual(self.page.locator('.talk-time').inner_text(), '09:05')

    def test_invalid_time_calendar_and_date_range_never_post(self):
        self.multi_day()
        self.open_form()
        self.credentials()
        self.fill_talk()
        for time, date in [('24:00', '12-2-27'), ('9:0', '12-2-27'), ('09:60', '12-2-27'),
                           ('09:00', '29-2-27'), ('09:00', '15-2-27'), ('09:00', '11-2-27')]:
            self.page.locator('#talk-time').fill(time)
            self.page.locator('#talk-date').fill(date)
            self.page.get_by_role('button', name='Submit talk', exact=True).click()
            self.assertEqual(self.posts, 0)
            self.assertTrue(self.page.locator('#form-error').is_visible())

    def test_calendar_and_clock_are_invariant_across_browser_timezones(self):
        self.multi_day()
        for zone in ('Europe/Berlin', 'America/Los_Angeles', 'Asia/Tokyo'):
            context = self.browser.new_context(timezone_id=zone)
            self.addCleanup(context.close)
            context.route('**/*', self.route)
            self.page = context.new_page()
            self.open_form()
            self.page.locator('#talk-time').fill('02:30')
            self.page.locator('#talk-date').fill('13-2-27')
            self.credentials()
            self.fill_talk('Timezone independent ' + zone)
            self.page.get_by_role('button', name='Submit talk', exact=True).click()
            self.wait_published()
            data = m.web.parse(self.api.issues[self.last_number])
            self.assertEqual((data['date'], data['time']), ('2027-02-13', '02:30'))

    def test_full_read_user_submission_stays_on_site_and_renders_escaped_projection(self):
        self.open_form()
        self.credentials()
        self.fill_talk(abstract="Use <script>throw Error('leak')</script> as plain ASCII.\n\tMore text.")
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.wait_published()
        self.assertIn("/submit-talk.html", self.page.url)
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.api.permissions["member"], "read")
        self.assertEqual(self.api.issues[self.last_number]["user"]["login"], "member")
        self.assertEqual(set(m.label_names(self.api.issues[self.last_number])), {"talk", "meeting:meeting-4", m.web.FORMAT_LABEL})
        self.assertEqual(self.page.evaluate("[localStorage.length, sessionStorage.length]"), [0, 0])
        self.assertEqual(self.page.locator("#github-token").get_attribute("type"), "password")
        self.assertEqual(self.page.locator("#github-token").get_attribute("autocomplete"), "current-password")
        self.assertNotIn(TOKEN, self.page.content())
        self.page.get_by_role("link", name="Return to meeting").click()
        self.assertEqual(self.page.locator("h1").inner_text(), DETAILS["name"])
        self.assertEqual(self.page.locator(".talk-list .talk-title").inner_text(), "Fictitious trees")
        self.page.get_by_text("Abstract", exact=True).click()
        self.assertIn("<script>", self.page.locator(".abstract-text").inner_text())
        self.assertEqual(self.page.locator(".abstract-text script").count(), 0)
        self.assertFalse(self.external)
        self.assertFalse(self.errors)
        public = "\n".join(self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH).values())
        for secret in (TOKEN, '"submission_id"', '"login"'):
            self.assertNotIn(secret, public)

    def test_required_fields_ascii_and_length_errors_prevent_post(self):
        self.open_form()
        self.credentials()
        for title, authors, abstract in (("", "A", "Text"), ("Talk", "", "Text"), ("Talk", "A", ""),
                                          ("René", "A", "Text"), ("Talk", "René", "Text"), ("Talk", "A", "René"),
                                          ("[meeting 4] Talk", "A", "Text"), ("   ", "A", "Text")):
            self.fill_talk(title, authors, abstract)
            self.page.get_by_role("button", name="Submit talk", exact=True).click()
            self.assertEqual(self.posts, 0)
        for selector, length in (("#talk-title", 201), ("#authors", 501), ("#abstract", 20001)):
            self.fill_talk()
            self.page.locator(selector).evaluate("(node, value) => { node.value = value; }", "x" * length)
            self.page.get_by_role("button", name="Submit talk", exact=True).click()
            self.assertEqual(self.posts, 0)

    def test_double_submit_and_lost_response_recover_without_duplicate_issue(self):
        self.response_mode = "lost-response"
        self.open_form()
        self.credentials()
        self.fill_talk()
        self.page.locator("#talk-form").evaluate("node => { node.requestSubmit(); node.requestSubmit(); }")
        self.wait_published()
        self.assertEqual(self.posts, 1)
        self.page.get_by_role("button", name="Check submission status").click()
        self.assertEqual(self.posts, 1)
        self.assertTrue(any("creator=member" in request["url"] for request in self.requests))

    def test_pending_or_forged_comment_does_not_claim_publication(self):
        self.status_mode = "pending"
        self.open_form()
        self.credentials()
        self.fill_talk()
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.startsWith('Submitted.')")
        issue = self.api.issues[self.last_number]
        data = m.web.parse(issue)
        fake = {"schema_version": 1, "submission_id": data["submission_id"], "state": "published", "revision": "a" * 40, "meeting_id": "meeting-4"}
        self.api.comments[self.last_number] = [{"body": m.web.STATUS_MARKER + json.dumps(fake) + " -->", "user": {"login": "member", "type": "User"}}]
        self.page.get_by_role("button", name="Check submission status").click()
        self.assertNotIn("Your talk is published", self.page.locator("#submission-status").inner_text())
        self.process(self.last_number)
        self.page.get_by_role("button", name="Check submission status").click()
        self.wait_published()
        self.assertEqual(self.posts, 1)

    def test_optional_repository_permissions_metadata_is_not_required(self):
        self.response_mode = "metadata-only"
        self.open_form()
        self.credentials()
        self.fill_talk()
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.wait_published()
        self.assertEqual(self.api.permissions["member"], "read")

    def test_meeting_link_submits_through_legacy_preview_without_a_script_request(self):
        # Reproduce a server started before the form existed: HTML is fetched
        # from the current branch, but its executable script allowlist is older.
        current_resource_path = preview.resource_path
        def old_resource_path(url):
            path = current_resource_path(url)
            if path == 'prototype/assets/talk-submission.js':
                raise FileNotFoundError
            return path
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        script_requests = []
        self.page.on('request', lambda request: script_requests.append(request.url) if request.url.endswith('.js') else None)
        with patch.object(preview, 'resource_path', side_effect=old_resource_path):
            self.assertEqual(self.page.request.get(self.base + '/prototype/assets/talk-submission.js').status, 404)
            self.page.goto(self.base + '/prototype/meetings/meeting-4/')
            self.page.get_by_role('link', name='Add talk', exact=True).click()
            self.page.wait_for_function("() => !document.getElementById('talk-fields').disabled")
            self.assertIn('?meeting=meeting-4', self.page.url)
            self.assertEqual(self.page.locator('#meeting-name').inner_text(), DETAILS['name'])
            self.assertFalse(self.page.locator('#meeting-choice').is_visible())
            self.assertFalse(script_requests)
            self.credentials()
            self.fill_talk()
            self.page.get_by_role('button', name='Submit talk', exact=True).click()
            self.wait_published()
            self.assertEqual(self.posts, 1)
            self.assertEqual(m.web.parse(self.api.issues[self.last_number])['meeting_id'], 'meeting-4')
            self.page.get_by_role('link', name='Return to meeting').click()
            self.assertEqual(self.page.url, self.base + '/prototype/meetings/meeting-4/')
            self.assertIn('Fictitious trees', self.page.locator('.public-talks').inner_text())
        self.assertFalse(self.errors)

    def test_generic_form_still_allows_explicit_meeting_selection(self):
        self.open_form(None)
        self.assertTrue(self.page.locator('#meeting-choice').is_visible())
        self.assertFalse(self.page.locator('#meeting-context').is_visible())
        self.page.locator('#meeting').select_option('meeting-10')
        self.credentials()
        self.fill_talk('Generic form talk')
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.wait_published()
        self.assertEqual(m.web.parse(self.api.issues[self.last_number])['meeting_id'], 'meeting-10')

    def test_unavailable_context_never_switches_to_another_active_meeting(self):
        for ident in ('meeting-999', 'invalid', 'meeting-4'):
            if ident == 'meeting-4':
                m.manage_meeting(self.api, {'number': 4, 'id': 'meeting-4', 'action': 'archive'})
                self.flush_pages()
            self.open_form(ident, ready=False)
            self.page.wait_for_function("() => document.getElementById('form-status').textContent.includes('unavailable or closed')")
            self.assertFalse(self.page.locator('#meeting-choice').is_visible())
            self.assertTrue(self.page.locator('#talk-title').is_disabled())
            self.assertTrue(self.page.locator('#github-token').is_disabled())
            self.assertTrue(self.page.locator('#submit-talk').is_disabled())
        self.assertEqual(self.posts, 0)

    def test_stalled_meeting_request_times_out_and_can_be_retried(self):
        self.page.clock.install()
        stalled = {'enabled': True}
        routes = []
        def index_request(route):
            if not stalled['enabled']:
                route.continue_()
            else:
                routes.append(route)
            # An unhandled route remains pending until AbortController cancels it.
        self.context.route('**/prototype/index.html', index_request)
        self.open_form(ready=False)
        self.page.wait_for_function("() => document.getElementById('form-status').textContent.startsWith('Loading')")
        self.page.clock.fast_forward(15001)
        self.page.wait_for_function("() => !document.getElementById('retry-meetings').hidden")
        self.assertIn('could not be loaded', self.page.locator('#form-status').inner_text())
        self.assertTrue(self.page.locator('#talk-title').is_disabled())
        self.assertEqual(self.posts, 0)
        for route in routes:
            route.abort()
        stalled['enabled'] = False
        self.page.get_by_role('button', name='Retry loading').click()
        self.page.wait_for_function("() => !document.getElementById('talk-fields').disabled")
        self.assertFalse(self.page.locator('#retry-meetings').is_visible())
        self.assertEqual(self.page.locator('#meeting-name').inner_text(), DETAILS['name'])

    def test_failed_availability_refresh_keeps_input_and_never_posts_a_talk(self):
        self.open_form()
        self.credentials()
        self.fill_talk()
        self.context.route('**/prototype/index.html', lambda route: route.fulfill(status=503, body='Untrusted upstream response'))
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('retry-meetings').hidden")
        self.assertEqual(self.posts, 0)
        self.assertNotIn('Untrusted upstream response', self.page.locator('#form-status').inner_text())
        self.assertEqual(self.page.locator('#talk-title').input_value(), 'Fictitious trees')
        self.assertTrue(self.page.locator('#submit-talk').is_disabled())
        self.context.unroute('**/prototype/index.html')
        self.page.get_by_role('button', name='Retry loading').click()
        self.page.wait_for_function("() => !document.getElementById('submit-talk').disabled")
        self.assertFalse(self.page.locator('#form-error').is_visible())
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.wait_published()
        self.assertEqual(self.posts, 1)

    def test_expired_or_denied_tokens_and_rejected_post_allow_safe_correction(self):
        self.open_form()
        for code in ("401", "403", "404"):
            self.response_mode = code
            self.page.locator("#github-token").fill(TOKEN)
            self.page.get_by_role("button", name="Check credentials", exact=True).click()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertTrue(self.page.locator("#submit-talk").is_disabled())
            self.assertNotIn(TOKEN, self.page.locator("#form-error").inner_text())
        self.response_mode = "success"
        self.credentials()
        self.fill_talk()
        self.response_mode = "post-403"
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('did not accept')")
        self.assertEqual(self.posts, 1)
        self.response_mode = "success"
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.wait_published()
        self.assertEqual(self.posts, 2)

    def test_archive_race_and_hidden_or_legacy_meetings_cannot_receive_new_talks(self):
        self.open_form()
        self.credentials()
        self.fill_talk()
        # Simulate stale public metadata: private authority changes immediately
        # before POST. The browser cannot override the archived private state.
        m.manage_meeting(self.api, {"number": 4, "id": "meeting-4", "action": "archive"})
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('needs correction')")
        self.assertNotIn("talk", m.label_names(self.api.issues[self.last_number]))
        self.assertNotIn("Fictitious trees", (self.directory / "prototype/meetings/meeting-4/index.html").read_text())
        self.open_form("legacy-20200101-000000000000", ready=False)
        self.page.wait_for_function("() => document.getElementById('form-status').textContent.includes('unavailable or closed')")
        self.assertTrue(self.page.locator('#talk-title').is_disabled())
        self.assertFalse(self.page.locator('#meeting-choice').is_visible())
        self.open_form(None)
        self.assertNotIn("meeting-4", self.page.locator("#meeting option").evaluate_all("nodes => nodes.map(n => n.value)"))
        self.assertEqual(self.page.locator("#meeting option").count(), 2)  # blank + active second meeting

    def test_preselection_second_meeting_mobile_layout_and_token_clear(self):
        for width in (1100, 375, 320):
            self.page.set_viewport_size({"width": width, "height": 950})
            self.open_form("meeting-10")
            self.assertEqual(self.page.locator("#meeting").input_value(), "meeting-10")
            self.assertFalse(self.page.locator('#meeting-choice').is_visible())
            self.assertEqual(self.page.locator('#meeting-name').inner_text(), 'Second fictitious meeting')
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.credentials()
        self.fill_talk("A second-meeting talk")
        self.page.get_by_role("button", name="Submit talk", exact=True).click()
        self.wait_published()
        self.assertNotIn("A second-meeting talk", (self.directory / "prototype/meetings/meeting-4/index.html").read_text())
        self.assertIn("A second-meeting talk", (self.directory / "prototype/meetings/meeting-10/index.html").read_text())
        self.assertEqual(self.page.get_by_role("button", name="Clear token").count(), 0)
        self.page.locator("#github-token").fill("")
        self.assertEqual(self.page.locator("#github-token").input_value(), "")
        self.assertTrue(self.page.locator("#submit-talk").is_disabled())

    def test_javascript_unavailable_and_native_form_submission_cannot_leak_token(self):
        nojs = self.browser.new_context(java_script_enabled=False)
        self.addCleanup(nojs.close)
        page = nojs.new_page()
        page.goto(self.base + "/prototype/submit-talk.html")
        self.assertTrue(page.locator("#submit-talk").is_disabled())
        self.assertIsNotNone(page.locator("#credential-fields").get_attribute("disabled"))
        self.assertIn("Enable JavaScript", page.locator("noscript").inner_text())
        self.open_form()
        self.credentials()
        self.page.locator("#talk-form").evaluate("form => form.submit()")
        self.assertEqual(self.posts, 0)
        self.assertNotIn(TOKEN, self.page.url)


class SlideBrowserTests(FormBrowserFixture):
    def select_pdf(self, content=None, name='slides.pdf'):
        self.page.locator('#slides').set_input_files({'name':name,'mimeType':'application/pdf',
                                                     'buffer':example_pdf() if content is None else content})

    def submit(self):
        self.page.get_by_role('button', name='Submit talk', exact=True).click()

    def test_member_upload_publishes_pdf_title_link_in_actual_preview(self):
        self.base = f'http://127.0.0.1:{self.preview.server_port}/__preview/synchronized'
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf()
        for width in (1100,375,320):
            self.page.set_viewport_size({'width':width,'height':950})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.submit(); self.wait_published()
        self.assertEqual((self.posts,self.upload_posts),(1,1))
        self.assertTrue(self.page.locator('#talk-title').is_disabled())
        data = m.web.parse(self.api.issues[self.last_number])
        self.assertNotIn('participant',data)
        self.assertEqual(data['slides']['size'],len(example_pdf()))
        self.page.get_by_role('link', name='Return to meeting').click()
        title = self.page.locator('.public-talks a.talk-title')
        self.assertEqual(title.inner_text(),'Fictitious trees')
        address = title.evaluate('node => node.href')
        self.assertTrue(address.startswith(self.base + '/prototype/slides/meeting-4/'))
        result = self.page.request.get(address)
        self.assertEqual(result.status,200)
        self.assertEqual(result.headers['content-type'],'application/pdf')
        self.assertEqual(result.headers['x-content-type-options'],'nosniff')
        self.assertEqual(result.body(),example_pdf())
        self.assertEqual(self.api.permissions['member'],'read')
        writes = [request for request in self.requests if request['method'] in {'POST','PUT','PATCH','DELETE'}]
        self.assertEqual([request['method'] for request in writes],['PUT','POST'])
        self.assertTrue(writes[0]['url'].startswith(API + '/repos/' + m.web.UPLOADS + '/contents/submissions/'))
        self.assertEqual(writes[1]['url'],API + '/repos/' + m.PRIVATE + '/issues')
        self.assertFalse(self.errors); self.assertFalse(self.external)

    def test_exact_ten_mb_pdf_is_accepted_end_to_end(self):
        content = example_pdf(10_000_000)
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf(content); self.submit(); self.wait_published()
        self.assertEqual(self.upload_posts,1)
        attachment = m.public_talks(self.api,'meeting-4')[-1]['slides']
        self.assertEqual(self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)[attachment['path']],content)

    def test_oversized_empty_and_wrong_file_are_rejected_before_any_write(self):
        self.open_form(); self.credentials(); self.fill_talk()
        for content,name in [(b'','empty.pdf'),(example_pdf(),'slides.txt'),(b'not a pdf','slides.pdf'),
                             (b'x' * 10_000_001,'oversized.pdf')]:
            self.select_pdf(content,name); self.submit()
            self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
            self.assertEqual((self.posts,self.upload_posts),(0,0))
        self.assertFalse(self.errors)

    def test_trusted_validation_rejects_spoofed_pdf_despite_browser_header_check(self):
        self.open_form(); self.credentials(); self.fill_talk()
        self.select_pdf(b'%PDF-1.7\nThis is not a PDF structure.\n%%EOF'); self.submit()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('needs correction')")
        self.assertFalse(any(path.endswith('.pdf') for path in self.api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)))
        self.assertNotIn('Fictitious trees',(self.directory / 'prototype/meetings/meeting-4/index.html').read_text())

    def test_lost_upload_response_recovers_pinned_file_without_duplicate_upload_or_issue(self):
        self.upload_mode = 'lost-response'
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf(); self.submit(); self.wait_published()
        self.page.get_by_role('button',name='Check submission status',exact=True).click()
        self.assertEqual((self.posts,self.upload_posts),(1,1))
        self.assertTrue(any('/git/ref/heads/main' in request['url'] for request in self.requests))
        self.assertTrue(any('?ref=' + self.upload_commit in request['url'] for request in self.requests))

    def test_unconfirmed_upload_does_not_create_issue_or_retry_put(self):
        self.upload_mode = 'lost-before-upload'
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf(); self.submit()
        self.page.wait_for_function("() => !document.getElementById('check-status').hidden && !document.getElementById('check-status').disabled")
        self.page.get_by_role('button',name='Check submission status',exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('form-error').hidden")
        self.assertEqual((self.posts,self.upload_posts),(0,1))
        self.assertTrue(self.page.locator('#submit-talk').is_disabled())

    def test_missing_file_write_permission_does_not_create_issue_and_can_be_corrected(self):
        self.upload_mode = '403'
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf(); self.submit()
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('No talk was sent')")
        self.assertEqual((self.posts,self.upload_posts),(0,1))
        self.assertIn('file-write permission',self.page.locator('#form-error').inner_text())
        self.assertNotIn('PRIVATE DENIAL',self.page.locator('body').inner_text())
        self.upload_mode = 'success'; self.submit(); self.wait_published()
        self.assertEqual((self.posts,self.upload_posts),(1,2))

    def test_lost_issue_response_after_upload_recovers_without_second_post(self):
        self.response_mode = 'lost-response'
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf(); self.submit(); self.wait_published()
        self.assertEqual((self.posts,self.upload_posts),(1,1))
        self.assertTrue(any('creator=member' in request['url'] for request in self.requests))

    def test_meeting_closing_during_upload_prevents_issue_post(self):
        self.open_form(); self.credentials(); self.fill_talk(); self.select_pdf()
        def close_meeting(route):
            m.manage_meeting(self.api,{'number':4,'id':'meeting-4','action':'archive'})
            self.flush_pages()
            self.route(route)
        self.context.route('**/repos/' + m.web.UPLOADS + '/contents/submissions/*',close_meeting)
        self.submit()
        self.page.wait_for_function("() => !document.getElementById('check-status').hidden && !document.getElementById('check-status').disabled")
        self.assertEqual((self.posts,self.upload_posts),(0,1))
        self.assertFalse(self.errors)


if __name__ == "__main__":
    unittest.main()
