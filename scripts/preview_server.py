"""Serve the latest public prototype branch without changing local files.

Run: python3 scripts/preview_server.py
Uses only Python and Git; never reads private Issues or publishes a website.
"""

import argparse
import http.server
import re
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

BRANCH = "prototype/meeting-management"
REF = "refs/remotes/origin/" + BRANCH
REPOSITORY = "ifipwg13/ifipwg13.github.io"


class PreviewError(Exception):
    pass


def resource_path(url):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    if not path.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", path):
        raise FileNotFoundError
    if any(part.startswith(".") for part in path.split("/") if part):
        raise FileNotFoundError
    if path.endswith("/"):
        path += "index.html"
    if not path.endswith((".html", ".css")):
        raise FileNotFoundError
    return "prototype/" + path.lstrip("/")


class GitSource:
    def __init__(self, repository, interval=2):
        self.repository = Path(repository)
        self.interval = interval
        self.last_fetch = None
        self.commit = None
        self.lock = threading.Lock()
        remote = self.git("config", "--get", "remote.origin.url").decode().strip()
        parsed = urllib.parse.urlsplit(remote)
        https_repo = parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.path.rstrip("/").removesuffix(".git") == "/" + REPOSITORY
        ssh_repo = remote in {"git@github.com:" + REPOSITORY, "git@github.com:" + REPOSITORY + ".git"}
        if not (https_repo or ssh_repo):
            raise PreviewError("Run this preview from the ifipwg13/ifipwg13.github.io repository with its original origin remote.")

    def git(self, *args, missing_ok=False):
        try:
            result = subprocess.run(["git", "-C", str(self.repository), *args],
                                    capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise PreviewError("The preview could not read GitHub. Check the Codespace's connection and try refreshing again.") from None
        if result.returncode:
            if missing_ok:
                raise FileNotFoundError
            # Git output can contain credential-bearing remote URLs. Never echo it.
            raise PreviewError("The preview could not update from GitHub. Check access to the prototype branch and refresh again.")
        return result.stdout

    def latest(self, force=False):
        with self.lock:
            if force or self.last_fetch is None or time.monotonic() - self.last_fetch >= self.interval:
                self.git("fetch", "--quiet", "origin", f"refs/heads/{BRANCH}:{REF}")
                commit = self.git("rev-parse", "--verify", REF).decode().strip()
                if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
                    raise PreviewError("The prototype branch could not be read. Refresh again.")
                self.commit = commit
                self.last_fetch = time.monotonic()
            return self.commit

    def read(self, path):
        # Restrict reads even when called directly rather than by the HTTP handler.
        if not path.startswith("prototype/") or resource_path("/" + path.removeprefix("prototype/")) != path:
            raise FileNotFoundError
        return self.git("show", f"{self.latest(force=path.endswith('.html'))}:{path}", missing_ok=True)


def make_server(source, host="0.0.0.0", port=8000):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.serve(head=False)

        def do_HEAD(self):
            self.serve(head=True)

        def serve(self, head):
            try:
                path = resource_path(self.path)
                content = source.read(path)
            except (FileNotFoundError, ValueError):
                self.send_error(404, "Page not found")
                return
            except PreviewError as error:
                print(str(error), flush=True)
                self.send_error(503, "Preview could not update from GitHub. Check the Codespaces terminal and refresh again.")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8" if path.endswith(".css") else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def log_message(self, *args):
            # Avoid logging arbitrary URL/query contents.
            pass

    return http.server.ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        source = GitSource(Path(__file__).resolve().parents[1])
        source.latest()
        with make_server(source, port=args.port) as server:
            print(f"Prototype preview on port {server.server_port}. Refresh Firefox to receive GitHub updates; no git pull is needed.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (PreviewError, OSError) as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
