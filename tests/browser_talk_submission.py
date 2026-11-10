"""Browser + trusted Python intake/publisher integration; fictitious data only.

No live GitHub writes or real tokens. Run with both repositories checked out:
  python3 tests/browser_talk_submission.py
"""
import copy
import functools
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
from test_meeting_setup import DETAILS  # noqa: E402

TOKEN = "github_pat_FICTITIOUS_TEST_ONLY_123456"
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


class FormBrowserTests(unittest.TestCase):
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
        self.api = WebGitHub()
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
        self.response_mode = "success"
        self.status_mode = "automatic"
        self.context.route("**/*", self.route)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def flush_pages(self):
        for name, value in self.api.branch_files(m.PUBLIC, m.PREVIEW_BRANCH).items():
            path = self.directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)

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
            route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST",
                          "Access-Control-Allow-Headers": "authorization,content-type,x-github-api-version"})
            return
        self.assertEqual(request.headers.get("authorization"), "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, request.url)
        self.assertNotIn(TOKEN, request.post_data or "")
        path = url.path
        if path == "/user":
            if self.response_mode in {"401", "403", "404"}:
                self.json_response(route, {}, int(self.response_mode))
            else:
                self.json_response(route, {"login": "member"})
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

    def credentials(self):
        self.page.locator("#github-token").fill(TOKEN)
        self.page.get_by_role("button", name="Check token", exact=True).click()
        self.page.wait_for_function("() => !document.getElementById('submit-talk').disabled")
        self.assertIn("Submitting as member", self.page.locator("#identity").inner_text())

    def fill_talk(self, title="Fictitious trees", authors="A. Example", abstract="A fictitious abstract.\nSecond line."):
        self.page.locator("#talk-title").fill(title)
        self.page.locator("#authors").fill(authors)
        self.page.locator("#abstract").fill(abstract)

    def wait_published(self):
        self.page.wait_for_function("() => document.getElementById('submission-status').textContent.includes('Your talk is published')")

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
        self.assertEqual(self.page.locator(".talk-list a").inner_text(), "Fictitious trees")
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
        self.page.get_by_role('button', name='Submit talk', exact=True).click()
        self.wait_published()
        self.assertEqual(self.posts, 1)

    def test_expired_or_denied_tokens_and_rejected_post_allow_safe_correction(self):
        self.open_form()
        for code in ("401", "403", "404"):
            self.response_mode = code
            self.page.locator("#github-token").fill(TOKEN)
            self.page.get_by_role("button", name="Check token", exact=True).click()
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
        self.page.get_by_role("button", name="Clear token").click()
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


if __name__ == "__main__":
    unittest.main()
