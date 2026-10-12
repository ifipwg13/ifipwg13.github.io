"""Exercise updates through real local Git repositories and HTTP; no credentials."""

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

    def server(self):
        server = p.make_server(self.source, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path="/", method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

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
        self.assertIn(b"New meeting", self.request(server, "/meetings/meeting-12/")[2])
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual((self.checkout / "prototype/index.html").read_text(), "Local work in progress")
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.main)
        self.assertEqual(git(self.checkout, "rev-parse", "origin/main"), self.main)

    def test_outside_hidden_and_traversal_paths_are_refused(self):
        server = self.server()
        for path in ["/README.md", "/../README.md", "/%2e%2e/prototype-secret.html", "/.git/config",
                     "/.hidden.html", "/%2ehidden.html", "/meetings/../../prototype-secret.html", "/assets/style.css%00",
                     "/prototype-secret.html", "/anything.js"]:
            with self.subTest(path=path):
                status, _, content = self.request(server, path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"Unrelated repository file", content)
                self.assertNotIn(b"Outside prototype", content)
                self.assertNotIn(b"Hidden", content)
        with self.assertRaises(FileNotFoundError):
            self.source.read("README.md")
        # Git returns a symlink's text; it cannot follow it outside the tree.
        self.assertEqual(self.source.read("prototype/link.html"), b"../README.md")

    def test_head_stylesheet_and_query_string(self):
        server = self.server()
        status, headers, content = self.request(server, "/assets/style.css")
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
        for old, new in [("/prototype", "/"), ("/prototype/", "/"),
                         ("/prototype/index.html", "/index.html"),
                         ("/prototype/assets/style.css", "/assets/style.css"),
                         ("/prototype/meetings/meeting-12", "/meetings/meeting-12/"),
                         ("/meetings/meeting-12", "/meetings/meeting-12/")]:
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

    def test_html_and_style_use_the_same_revision_during_a_concurrent_update(self):
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
                git(self.remote, "add", "prototype/assets/style.css")
                git(self.remote, "commit", "-m", "Update styling")
                self.source.latest(force=True)
            return content

        server = self.server()
        with patch.object(self.source, "read", side_effect=advancing_read):
            _, headers, content = self.request(server)
        self.assertEqual(headers["X-Preview-Revision"], first)
        self.assertIn(b"First meeting", content)
        self.assertIn(b"color: navy", content)
        self.assertNotIn(b"color: green", content)
        _, headers, content = self.request(server)
        self.assertIn(b"First and new meeting", content)
        self.assertIn(b"color: green", content)
        self.assertNotEqual(headers["X-Preview-Revision"], first)

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
        readme = (Path(p.__file__).resolve().parents[1] / "README.md").read_text()
        blocks = re.findall(r"```sh\n(.*?)```", readme, flags=re.DOTALL)
        command = textwrap.dedent(next(block for block in blocks if "meeting_preview_script=" in block))
        command = command.replace("--port 8001", "--port 0")
        command = command.replace("/tmp/meeting-preview.", str(Path(self.directory.name) / "meeting-preview."))
        (self.checkout / "prototype/index.html").write_text("Preserved local changes")
        head = git(self.checkout, "rev-parse", "HEAD")
        # exec keeps the server as this process, so teardown cannot orphan it.
        command = command.replace('python3 "$meeting_preview_script"', 'exec python3 "$meeting_preview_script"')
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
                self.assertIn(b"First meeting", content)
                self.assertIn(b"Live preview", content)
            finally:
                connection.close()
            self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), head)
            self.assertEqual(git(self.checkout, "rev-parse", "origin/" + p.BRANCH), latest)
            self.assertEqual((self.checkout / "prototype/index.html").read_text(), "Preserved local changes")
        finally:
            process.terminate()
            process.communicate(timeout=10)

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


if __name__ == "__main__":
    unittest.main()
