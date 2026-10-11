"""Exercise updates through real local Git repositories and HTTP; no credentials."""

import http.client
import importlib.util
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("preview", Path(__file__).resolve().parents[1] / "scripts/preview_server.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def git(repository, *args):
    return subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=True).stdout


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
        (self.remote / "prototype/index.html").write_text("<h1>First meeting</h1>")
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
        (self.remote / "prototype/index.html").write_text("<h1>First and new meeting</h1>")
        (self.remote / "prototype/meetings/meeting-12").mkdir(parents=True)
        (self.remote / "prototype/meetings/meeting-12/index.html").write_text("<h1>New meeting</h1>")
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
