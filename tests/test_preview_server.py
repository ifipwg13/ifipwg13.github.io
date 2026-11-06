"""Exercise updates through real local Git repositories and HTTP; no credentials."""

import base64
import http.client
import importlib.util
import re
import select
import subprocess
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("preview", Path(__file__).resolve().parents[1] / "scripts/preview_server.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def git(repository, *args):
    return subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=True).stdout


def meeting_page(title, stylesheet="assets/style.css"):
    return (f'<!doctype html><html><head><link rel="stylesheet" href="{stylesheet}"></head>'
            f'<body><h1>{title}</h1><a class="button" href="https://github.com/">View meeting</a></body></html>')


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.remote, self.checkout = root / "remote", root / "checkout"
        self.remote.mkdir()
        git(self.remote, "init", "-b", "main")
        git(self.remote, "config", "user.name", "Preview test")
        git(self.remote, "config", "user.email", "preview@example.invalid")
        (self.remote / "README.md").write_text("Unrelated repository file")
        git(self.remote, "add", ".")
        git(self.remote, "commit", "-m", "Published baseline")
        self.main = git(self.remote, "rev-parse", "main")
        git(self.remote, "switch", "-c", p.BRANCH)
        (self.remote / "prototype/assets").mkdir(parents=True)
        (self.remote / "index.html").write_text(meeting_page("Group homepage", "prototype/assets/style.css"))
        (self.remote / "members").mkdir()
        (self.remote / "members/index.html").write_text(meeting_page("Group members", "../prototype/assets/style.css"))
        (self.remote / "other-root.html").write_text("Restricted root file")
        (self.remote / "members/private.html").write_text("Restricted member file")
        (self.remote / "prototype/index.html").write_text(meeting_page("First meeting"))
        (self.remote / "prototype/assets/style.css").write_text("h1 {color: navy}")
        (self.remote / "prototype-secret.html").write_text("Outside prototype")
        (self.remote / "prototype/.hidden.html").write_text("Hidden")
        (self.remote / "prototype/link.html").symlink_to("../README.md")
        git(self.remote, "add", ".")
        git(self.remote, "commit", "-m", "Initial prototype")
        git(root, "clone", "--branch", p.BRANCH, str(self.remote), str(self.checkout))
        # Keep the real public remote identity, but route Git to an isolated
        # fixture through repository-local configuration. Never use the network.
        git(self.checkout, "remote", "set-url", "origin", "https://github.com/" + p.REPOSITORY + ".git")
        git(self.checkout, "config", "url." + str(self.remote) + ".insteadOf", "https://github.com/" + p.REPOSITORY + ".git")
        self.source = p.GitSource(self.checkout)

    def publish(self):
        (self.remote / "prototype/index.html").write_text(meeting_page("First and new meeting"))
        (self.remote / "prototype/meetings/meeting-12").mkdir(parents=True)
        (self.remote / "prototype/meetings/meeting-12/index.html").write_text(meeting_page("New meeting", "../../assets/style.css"))
        git(self.remote, "add", "prototype")
        git(self.remote, "commit", "-m", "Add a meeting")

    def publish_sorter(self):
        index = self.remote / "prototype/index.html"
        index.write_text(index.read_text().replace("</body>", p.LIST_SCRIPT + "</body>"))
        (self.remote / "prototype/assets/meetings-list.js").write_text('const revision = "first";')
        git(self.remote, "add", "prototype")
        git(self.remote, "commit", "-m", "Add the meeting-list sorter")

    def publish_logo(self):
        index = self.remote / 'prototype/index.html'
        index.write_text(index.read_text().replace('</body>', '<img src="assets/ifip-logo.png" alt="IFIP"></body>'))
        (self.remote / p.LOGO_PATH).write_bytes(b'\x89PNG\r\n\x1a\nfirst-version')
        (self.remote / 'prototype/assets/other.png').write_bytes(b'NOT-ALLOWED')
        git(self.remote, 'add', 'prototype')
        git(self.remote, 'commit', '-m', 'Add the local IFIP logo')

    def server(self):
        server = p.make_server(self.source, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path="/prototype/", method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def documented_command(self, variable):
        readme = (Path(p.__file__).resolve().parents[1] / "README.md").read_text()
        blocks = re.findall(r"```sh\n(.*?)```", readme, flags=re.DOTALL)
        command = textwrap.dedent(next(block for block in blocks if variable + "=" in block))
        command = command.replace("--port 8001", "--port 0")
        for prefix in ["meeting-preview.", "group-preview."]:
            command = command.replace("/tmp/" + prefix, str(Path(self.directory.name) / prefix))
        return command.replace('python3 "$' + variable + '"', 'exec python3 "$' + variable + '"')

    def check_documented_server(self, command, expected):
        process = subprocess.Popen(["bash", "-c", command], cwd=self.checkout,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            readable, _, _ = select.select([process.stdout], [], [], 20)
            self.assertTrue(readable, "Preview did not start")
            line = process.stdout.readline().decode()
            match = re.search(r"LIVE PREVIEW on port ([0-9]+)", line)
            self.assertIsNotNone(match, line)
            connection = http.client.HTTPConnection("127.0.0.1", int(match[1]), timeout=10)
            try:
                connection.request("GET", "/")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                content = response.read()
                self.assertIn(expected, content)
                self.assertIn(b"Live preview", content)
            finally:
                connection.close()
        finally:
            process.terminate()
            process.communicate(timeout=10)

    def test_refresh_fetches_new_commit_without_restart_pull_or_local_file_changes(self):
        server = self.server()
        head = git(self.checkout, "rev-parse", "HEAD")
        first = self.request(server)
        self.assertEqual(first[0], 200)
        self.assertIn(b"First meeting", first[2])
        # A local edit is preserved while the preview serves the GitHub version.
        (self.checkout / "prototype/index.html").write_text("Local work in progress")
        self.publish()
        updated = self.request(server)
        self.assertEqual(updated[0], 200)
        self.assertIn(b"First and new meeting", updated[2])
        self.assertEqual(updated[1]["Cache-Control"], "no-store")
        self.assertIn(b"New meeting", self.request(server, "/prototype/meetings/meeting-12/")[2])
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual((self.checkout / "prototype/index.html").read_text(), "Local work in progress")
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.main)
        self.assertEqual(git(self.checkout, "rev-parse", "origin/main"), self.main)

    def test_outside_hidden_and_traversal_paths_are_refused(self):
        server = self.server()
        for path in ["/README.md", "/../README.md", "/%2e%2e/prototype-secret.html", "/.git/config",
                     "/.hidden.html", "/%2ehidden.html", "/meetings/../../prototype-secret.html", "/assets/style.css%00",
                     "/prototype-secret.html", "/anything.js", "/assets/other.js", "/data/legacy-meetings.json",
                     "/other-root.html", "/members/private.html", "/members/../index.html", "/prototype/data/legacy-meetings.json"]:
            with self.subTest(path=path):
                status, _, content = self.request(server, path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"Unrelated repository file", content)
                self.assertNotIn(b"Outside prototype", content)
                self.assertNotIn(b"Hidden", content)
                self.assertNotIn(b"Restricted root file", content)
                self.assertNotIn(b"Restricted member file", content)
        with self.assertRaises(FileNotFoundError):
            self.source.read("README.md")
        # Git returns a symlink's text; it cannot follow it outside the tree.
        self.assertEqual(self.source.read("prototype/link.html"), b"../README.md")

    def test_direct_reads_cannot_bypass_the_root_allowlist(self):
        for path in ['other-root.html', 'members/private.html', 'members/../index.html',
                     '../index.html', 'prototype/../index.html', '/index.html',
                     'prototype/.git/config.html']:
            with self.subTest(path=path), self.assertRaises(FileNotFoundError):
                self.source.read(path)
        for path in ['//example.com/index.html', 'https://example.com/index.html',
                     '/%2f%2fexample.com/index.html']:
            with self.subTest(path=path), self.assertRaises(FileNotFoundError):
                p.canonical_url(path)

    def test_head_stylesheet_and_query_string(self):
        server = self.server()
        status, headers, content = self.request(server, "/prototype/assets/style.css")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/css; charset=utf-8")
        self.assertIn(b"color: navy", content)
        status, headers, content = self.request(server, method="HEAD")
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(content, b"")
        self.assertEqual(self.request(server, "/?refresh=1")[0], 200)

    def test_page_contains_its_styling_and_live_revision_without_a_css_request(self):
        server = self.server()
        status, headers, content = self.request(server)
        self.assertEqual(status, 200)
        self.assertIn(b"<style>\nh1 {color: navy}\n</style>", content)
        self.assertNotIn(b'rel="stylesheet"', content)
        self.assertIn(b"<strong>Live preview</strong>", content)
        revision = git(self.remote, "rev-parse", p.BRANCH).decode().strip()
        self.assertEqual(headers["X-Preview-Revision"], revision)
        self.assertIn(revision[:7].encode(), content)
        self.assertEqual(headers["Pragma"], "no-cache")

    def test_legacy_and_slashless_urls_redirect_to_a_styled_current_page(self):
        self.publish()
        server = self.server()
        for old, new in [("/prototype", "/prototype/"), ("/members", "/members/"),
                         ("/meetings", "/prototype/"), ("/meetings/", "/prototype/"),
                         ("/assets/style.css", "/prototype/assets/style.css"),
                         ("/prototype/meetings/meeting-12", "/prototype/meetings/meeting-12/"),
                         ("/meetings/meeting-12", "/prototype/meetings/meeting-12/"),
                         ("/meetings/meeting-12/", "/prototype/meetings/meeting-12/")]:
            with self.subTest(old=old):
                status, headers, content = self.request(server, old)
                self.assertEqual(status, 307)
                self.assertEqual(headers["Location"], new)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(content, b"")
                status, headers, content = self.request(server, new)
                self.assertEqual(status, 200)
                if new.endswith(".css"):
                    self.assertIn(b"color: navy", content)
                else:
                    self.assertIn(b"Live preview", content)
                    self.assertIn(b"<style>", content)

    def test_home_members_and_meetings_have_distinct_canonical_paths(self):
        server = self.server()
        for path, title in [("/", b"Group homepage"), ("/index.html", b"Group homepage"),
                            ("/members/", b"Group members"), ("/members/index.html", b"Group members"),
                            ("/prototype/", b"First meeting"), ("/prototype/index.html", b"First meeting")]:
            with self.subTest(path=path):
                status, headers, content = self.request(server, path)
                self.assertEqual(status, 200)
                self.assertIn(title, content)
                self.assertIn(b"<style>", content)
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertNotIn('Location', headers)

    def test_logo_is_inlined_and_only_its_exact_png_path_is_served(self):
        self.publish_logo()
        server = self.server()
        _, _, content = self.request(server)
        data = (self.remote / p.LOGO_PATH).read_bytes()
        self.assertIn(b'data:image/png;base64,' + base64.b64encode(data), content)
        status, headers, body = self.request(server, '/' + p.LOGO_PATH)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(body, data)
        self.assertEqual(self.request(server, '/prototype/assets/other.png')[0], 404)
        status, headers, _ = self.request(server, '/assets/ifip-logo.png')
        self.assertEqual(status, 307)
        self.assertEqual(headers['Location'], '/' + p.LOGO_PATH)

    def test_missing_or_invalid_logo_returns_uncached_error(self):
        self.publish_logo()
        server = self.server()
        for invalid in [None, b'INVALID-IMAGE']:
            path = self.remote / p.LOGO_PATH
            if invalid is None:
                path.unlink()
            else:
                path.write_bytes(invalid)
            git(self.remote, 'add', 'prototype')
            git(self.remote, 'commit', '-m', 'Simulate unavailable logo')
            with patch('builtins.print'):
                status, headers, content = self.request(server)
            self.assertEqual(status, 503)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertNotIn(b'First meeting', content)

    def test_logo_uses_the_html_revision_during_a_concurrent_update(self):
        self.publish_logo()
        original = self.source.read
        changed = False
        def advancing_read(path, revision=None):
            nonlocal changed
            content = original(path, revision)
            if path.endswith('.html') and not changed:
                changed = True
                (self.remote / p.LOGO_PATH).write_bytes(b'\x89PNG\r\n\x1a\nsecond-version')
                git(self.remote, 'add', 'prototype')
                git(self.remote, 'commit', '-m', 'Update the logo')
                self.source.latest(force=True)
            return content
        server = self.server()
        with patch.object(self.source, 'read', side_effect=advancing_read):
            _, _, content = self.request(server)
        self.assertIn(base64.b64encode(b'\x89PNG\r\n\x1a\nfirst-version'), content)
        self.assertNotIn(base64.b64encode(b'\x89PNG\r\n\x1a\nsecond-version'), content)
        self.assertIn(base64.b64encode(b'\x89PNG\r\n\x1a\nsecond-version'), self.request(server)[2])

    def test_html_style_and_sorter_use_the_same_revision_during_a_concurrent_update(self):
        self.publish_sorter()
        first = git(self.remote, "rev-parse", p.BRANCH).decode().strip()
        original = self.source.read
        switched = False

        def advancing_read(path, revision=None):
            nonlocal switched
            content = original(path, revision)
            if path.endswith(".html") and not switched:
                switched = True
                self.publish()
                (self.remote / "prototype/assets/style.css").write_text("h1 {color: green}")
                index = self.remote / "prototype/index.html"
                index.write_text(index.read_text().replace("</body>", p.LIST_SCRIPT + "</body>"))
                (self.remote / "prototype/assets/meetings-list.js").write_text('const revision = "second";')
                git(self.remote, "add", "prototype")
                git(self.remote, "commit", "-m", "Update styling")
                self.source.latest(force=True)
            return content

        server = self.server()
        with patch.object(self.source, "read", side_effect=advancing_read):
            _, headers, content = self.request(server)
        self.assertEqual(headers["X-Preview-Revision"], first)
        self.assertIn(b"First meeting", content)
        self.assertIn(b"color: navy", content)
        self.assertIn(b'const revision = "first";', content)
        self.assertNotIn(b'const revision = "second";', content)
        self.assertNotIn(b"color: green", content)
        _, headers, content = self.request(server)
        self.assertIn(b"First and new meeting", content)
        self.assertIn(b"color: green", content)
        self.assertIn(b'const revision = "second";', content)
        self.assertNotEqual(headers["X-Preview-Revision"], first)

    def test_sorter_is_inlined_and_its_only_allowed_asset_url_has_correct_mime(self):
        self.publish_sorter()
        server = self.server()
        status, headers, content = self.request(server)
        self.assertEqual(status, 200)
        self.assertIn(b'<script>\nconst revision = "first";\n</script>', content)
        self.assertNotIn(p.LIST_SCRIPT.encode(), content)
        status, headers, content = self.request(server, "/prototype/assets/meetings-list.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(content, b'const revision = "first";')
        status, headers, _ = self.request(server, "/assets/meetings-list.js")
        self.assertEqual(status, 307)
        self.assertEqual(headers["Location"], "/prototype/assets/meetings-list.js")

    def test_missing_sorter_returns_an_uncached_error_instead_of_unsorted_meetings(self):
        self.publish_sorter()
        (self.remote / "prototype/assets/meetings-list.js").unlink()
        git(self.remote, "add", "prototype")
        git(self.remote, "commit", "-m", "Simulate missing sorter")
        server = self.server()
        with patch("builtins.print"):
            status, headers, content = self.request(server)
        self.assertEqual(status, 503)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(b"First meeting", content)

    def test_slashless_historical_page_redirects_to_styled_page(self):
        path = "/legacy-meetings/legacy-20160331-012345abcdef"
        directory = self.remote / "prototype" / path.lstrip("/")
        directory.mkdir(parents=True)
        (directory / "index.html").write_text(meeting_page("Historical meeting", "../../assets/style.css"))
        git(self.remote, "add", "prototype")
        git(self.remote, "commit", "-m", "Add historical meeting")
        server = self.server()
        for url in (path, "/prototype" + path):
            status, headers, _ = self.request(server, url)
            self.assertEqual(status, 307)
            self.assertEqual(headers["Location"], '/prototype' + path + "/")
        status, _, content = self.request(server, '/prototype' + path + "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Historical meeting", content)
        self.assertIn(b"color: navy", content)

    def test_missing_stylesheet_returns_uncached_error_instead_of_unstyled_page(self):
        (self.remote / "prototype/assets/style.css").unlink()
        git(self.remote, "add", "prototype/assets/style.css")
        git(self.remote, "commit", "-m", "Simulate missing stylesheet")
        server = self.server()
        with patch("builtins.print"):
            status, headers, content = self.request(server)
        self.assertEqual(status, 503)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(b"First meeting", content)

    def test_legacy_traversal_and_redirect_to_external_host_are_refused(self):
        server = self.server()
        for url in ["/prototype/../README.md", "/prototype/%2e%2e/prototype-secret.html",
                    "/%2f%2fexample.com/index.html", "//example.com/index.html"]:
            with self.subTest(url=url):
                status, headers, content = self.request(server, url)
                self.assertEqual(status, 404)
                self.assertNotIn("Location", headers)
                self.assertEqual(headers["Cache-Control"], "no-store")

    def test_invalid_html_structure_cannot_silently_serve_an_unstyled_page(self):
        (self.remote / "prototype/index.html").write_text("<h1>Missing stylesheet</h1>")
        git(self.remote, "add", "prototype/index.html")
        git(self.remote, "commit", "-m", "Simulate incomplete page")
        server = self.server()
        with patch("builtins.print"):
            status, headers, content = self.request(server)
        self.assertEqual(status, 503)
        self.assertNotIn(b"Missing stylesheet", content)

    def test_fetched_script_starts_outside_checkout_and_preserves_local_work(self):
        # Reproduce managed checkouts that fetch only main: an ordinary fetch
        # must not be mistaken for updating origin/prototype/meeting-management.
        git(self.checkout, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
        initial = git(self.checkout, "rev-parse", "origin/" + p.BRANCH)
        (self.remote / "scripts").mkdir()
        (self.remote / "scripts/preview_server.py").write_text(Path(p.__file__).read_text())
        git(self.remote, "add", "scripts/preview_server.py")
        git(self.remote, "commit", "-m", "Publish current preview server")
        latest = git(self.remote, "rev-parse", p.BRANCH)
        self.assertNotEqual(initial, latest)
        git(self.checkout, "fetch", "origin", p.BRANCH)
        self.assertEqual(git(self.checkout, "rev-parse", "origin/" + p.BRANCH), initial)
        (self.checkout / "prototype/index.html").write_text("Preserved local changes")
        head = git(self.checkout, "rev-parse", "HEAD")
        self.check_documented_server(self.documented_command('meeting_preview_script'), b"Group homepage")
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.checkout, "rev-parse", "origin/" + p.BRANCH), latest)
        self.assertEqual((self.checkout / "prototype/index.html").read_text(), "Preserved local changes")

    def test_existing_codespace_review_command_selects_the_feature_without_altering_local_work(self):
        prototype = git(self.remote, "rev-parse", p.BRANCH)
        git(self.remote, "switch", "-c", "feature/classic-style-compact-talks")
        (self.remote / "index.html").write_text(meeting_page("Review group homepage", "prototype/assets/style.css"))
        (self.remote / "scripts").mkdir()
        (self.remote / "scripts/preview_server.py").write_text(Path(p.__file__).read_text())
        git(self.remote, "add", ".")
        git(self.remote, "commit", "-m", "Review-only group homepage")
        git(self.checkout, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
        (self.checkout / "index.html").write_text("Preserved local homepage")
        head = git(self.checkout, "rev-parse", "HEAD")
        self.check_documented_server(self.documented_command('group_preview_script'), b"Review group homepage")
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.remote, "rev-parse", p.BRANCH), prototype)
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.main)
        self.assertEqual((self.checkout / "index.html").read_text(), "Preserved local homepage")

    def test_failed_update_does_not_silently_serve_stale_page_or_echo_git_output(self):
        server = self.server()
        self.assertEqual(self.request(server)[0], 200)
        git(self.checkout, "config", "url." + str(self.remote) + ".insteadOf", "unused")
        with patch.object(p.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stderr=b"TEST-ONLY-CREDENTIAL")), patch("builtins.print") as log:
            status, _, content = self.request(server)
            self.assertEqual(status, 503)
            self.assertNotIn(b"First meeting", content)
            self.assertNotIn(b"TEST-ONLY-CREDENTIAL", content)
            self.assertNotIn("TEST-ONLY-CREDENTIAL", str(log.call_args_list))

    def test_private_remote_is_rejected(self):
        git(self.checkout, "remote", "set-url", "origin", "https://github.com/ifipwg13/meetings.git")
        with self.assertRaisesRegex(p.PreviewError, "original origin"):
            p.GitSource(self.checkout)

    def test_selected_feature_branch_is_previewed_without_merging_the_prototype(self):
        prototype = git(self.remote, "rev-parse", p.BRANCH)
        main = git(self.remote, "rev-parse", "main")
        git(self.remote, "switch", "-c", "feature/review")
        (self.remote / "prototype/index.html").write_text(meeting_page("Review feature"))
        git(self.remote, "add", "prototype/index.html")
        git(self.remote, "commit", "-m", "Unmerged review feature")
        self.source = p.GitSource(self.checkout, branch="feature/review")
        server = self.server()
        status, headers, content = self.request(server)
        self.assertEqual(status, 200)
        self.assertIn(b"Review feature", content)
        self.assertEqual(headers["X-Preview-Revision"], git(self.remote, "rev-parse", "feature/review").decode().strip())
        self.assertEqual(git(self.remote, "rev-parse", p.BRANCH), prototype)
        self.assertEqual(git(self.remote, "rev-parse", "main"), main)
        default = p.GitSource(self.checkout)
        self.assertIn(b"First meeting", default.page("prototype/index.html")[0])

    def test_invalid_review_branch_names_are_rejected(self):
        for branch in ["-main", "../main", "main:refs/heads/main", "feature/../main", "main\nprivate", "feature/"]:
            with self.subTest(branch=branch), self.assertRaises(p.PreviewError):
                p.GitSource(self.checkout, branch=branch)


if __name__ == "__main__":
    unittest.main()
