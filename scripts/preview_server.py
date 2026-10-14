"""Serve the latest public prototype branch without changing local files.

Run: python3 scripts/preview_server.py
Uses only Python and Git; never reads private Issues or publishes a website.
"""

import argparse
import datetime as dt
import html
import http.server
import re
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

BRANCH = "prototype/meeting-management"
REF = "refs/remotes/origin/" + BRANCH
REPOSITORY = "ifipwg13/ifipwg13.github.io"


class PreviewError(Exception):
    pass


def resource_path(url):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    if not path.startswith("/") or path.startswith("//") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", path):
        raise FileNotFoundError
    if any(part.startswith(".") for part in path.split("/") if part):
        raise FileNotFoundError
    if path.endswith("/"):
        path += "index.html"
    if not path.endswith((".html", ".css")):
        raise FileNotFoundError
    return "prototype/" + path.lstrip("/")


def canonical_url(url):
    """Redirect the original file server's /prototype/ URLs to this server's root."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    # Validate before issuing redirects, including encoded traversal and // hosts.
    resource_path(path + "/" if not path.endswith(("/", ".html", ".css")) else path)
    canonical = path
    if path == "/prototype":
        canonical = "/"
    elif path.startswith("/prototype/"):
        canonical = path.removeprefix("/prototype")
    if re.fullmatch(r"/meetings/(?:demo-001|meeting-[1-9][0-9]*)", canonical):
        canonical += "/"
    return canonical if canonical != path else None


def styled_preview(content, stylesheet, revision):
    """Deliver a complete styled page even if a browser's CSS request would fail."""
    page = content.decode("utf-8")
    style = "<style>\n" + stylesheet.decode("utf-8").replace("</", "<\\/") + "\n</style>"
    pattern = r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>'
    page, replacements = re.subn(pattern, lambda _: style, page, flags=re.IGNORECASE)
    if replacements != 1 or page.lower().count("<body>") != 1:
        raise PreviewError("The preview page needs its stylesheet and body markers. Ask the organizer to review it.")
    fetched = dt.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d-%m-%Y %H:%M:%S %Z")
    banner = ('<aside aria-label="Live preview" style="background:#edf3fa;color:#202b3c;'
              'border-bottom:1px solid #d6dee8;padding:.65rem 1rem;font-size:.9rem">'
              '<strong>Live preview</strong> · Updates from GitHub on refresh · '
              f'Version {html.escape(revision[:7])} · Retrieved {fetched}</aside>')
    return re.sub(r"<body>", lambda _: "<body>\n" + banner, page, count=1, flags=re.IGNORECASE).encode("utf-8")


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

    def read(self, path, revision=None):
        # Restrict reads even when called directly rather than by the HTTP handler.
        if not path.startswith("prototype/") or resource_path("/" + path.removeprefix("prototype/")) != path:
            raise FileNotFoundError
        revision = revision or self.latest(force=path.endswith('.html'))
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise PreviewError("The preview revision could not be read.")
        return self.git("show", f"{revision}:{path}", missing_ok=True)

    def page(self, path):
        # HTML and CSS must come from the same commit even during an update.
        revision = self.latest(force=True)
        content = self.read(path, revision)
        try:
            stylesheet = self.read("prototype/assets/style.css", revision)
        except FileNotFoundError:
            raise PreviewError("The prototype stylesheet is missing from GitHub; the preview cannot display it correctly.") from None
        return styled_preview(content, stylesheet, revision), revision


def make_server(source, host="0.0.0.0", port=8001):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.serve(head=False)

        def do_HEAD(self):
            self.serve(head=True)

        def serve(self, head):
            try:
                redirect = canonical_url(self.path)
                if redirect:
                    self.send_response(307)
                    self.send_header("Location", redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                path = resource_path(self.path)
                if path.endswith(".html"):
                    content, revision = source.page(path)
                else:
                    content = source.read(path)
                    revision = source.commit
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
            self.send_header("X-Preview-Revision", revision)
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def end_headers(self):
            # Errors and redirects must not remain cached either.
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

        def log_message(self, *args):
            # Avoid logging arbitrary URL/query contents.
            pass

    return http.server.ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        source = GitSource(args.repository)
        source.latest()
        with make_server(source, port=args.port) as server:
            print(f"LIVE PREVIEW on port {server.server_port}. Open this port from Codespaces Ports. "
                  "The page must show the Live preview label; HTML and styling update together from GitHub.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (PreviewError, OSError) as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
