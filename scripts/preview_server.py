"""Serve the latest public site branch without changing local files.

Run: python3 scripts/preview_server.py
Uses only Python and Git; never reads private Issues or publishes a website.
"""

import argparse
import base64
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
LIST_SCRIPT = '<script src="assets/meetings-list.js" defer></script>'
LOGO_PATH = 'prototype/assets/ifip-logo.png'
LOGO_IMAGE = re.compile(r'''(<img\b[^>]*\bsrc=["'])(?:(?:\.\./){1,2}|prototype/)?assets/ifip-logo\.png(["'])''', re.IGNORECASE)
SYNCHRONIZED_VIEW = '/__preview/synchronized/'


class PreviewError(Exception):
    pass


def url_path(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme or parsed.netloc:
        raise FileNotFoundError
    path = urllib.parse.unquote(parsed.path)
    if not path.startswith("/") or path.startswith("//") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", path):
        raise FileNotFoundError
    if any(part.startswith(".") for part in path.split("/") if part):
        raise FileNotFoundError
    return path


def resource_path(url):
    path = url_path(url)
    if path.endswith("/"):
        path += "index.html"
    if path in {"/index.html", "/members/index.html"}:
        return path.lstrip("/")
    if not path.startswith("/prototype/"):
        raise FileNotFoundError
    if not path.endswith((".html", ".css")) and path not in {"/prototype/assets/meetings-list.js", '/' + LOGO_PATH}:
        raise FileNotFoundError
    return path.lstrip("/")


def canonical_url(url):
    """Match static-site URLs and retain old preview links as redirects."""
    path = url_path(url)
    canonical = path
    if path in {"/members", "/prototype"}:
        canonical += "/"
    elif path in {"/meetings", "/meetings/"}:
        canonical = "/prototype/"
    elif path.startswith(("/meetings/", "/legacy-meetings/", "/assets/")):
        canonical = "/prototype" + path
    if re.fullmatch(r"/prototype/(?:meetings/(?:demo-001|meeting-[1-9][0-9]*)|legacy-meetings/legacy-[0-9]{8}-[0-9a-f]{12})", canonical):
        canonical += "/"
    resource_path(canonical)
    return canonical if canonical != path else None


def styled_preview(content, stylesheet, revision, javascript=None, logo=None, branch=BRANCH):
    """Deliver a complete styled page even if a browser's CSS request would fail."""
    page = content.decode("utf-8")
    style = "<style>\n" + stylesheet.decode("utf-8").replace("</", "<\\/") + "\n</style>"
    pattern = r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>'
    page, replacements = re.subn(pattern, lambda _: style, page, flags=re.IGNORECASE)
    if replacements != 1 or page.lower().count("<body>") != 1:
        raise PreviewError("The preview page needs its stylesheet and body markers. Ask the organizer to review it.")
    if LIST_SCRIPT in page:
        if javascript is None:
            raise PreviewError("The meeting-list script is missing; the preview cannot sort the combined list.")
        script = '<script>\n' + javascript.decode('utf-8').replace('</', '<\\/') + '\n</script>'
        page = page.replace(LIST_SCRIPT, script)
    if LOGO_IMAGE.search(page):
        if logo is None or not logo.startswith(b'\x89PNG\r\n\x1a\n'):
            raise PreviewError('The IFIP logo is missing or invalid; the preview cannot display this version correctly.')
        data_url = 'data:image/png;base64,' + base64.b64encode(logo).decode('ascii')
        page = LOGO_IMAGE.sub(lambda match: match[1] + data_url + match[2], page)
    fetched = dt.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d-%m-%Y %H:%M:%S %Z")
    synchronized = branch == BRANCH
    mode = 'Synchronized preview' if synchronized else 'Review snapshot'
    explanation = ('Issue changes appear after synchronization succeeds and you refresh.' if synchronized else
                   'This review branch does not receive Issue updates. '
                   f'<a href="{SYNCHRONIZED_VIEW}">Switch to synchronized preview</a>.')
    banner = ('<aside aria-label="Preview status" style="background:#edf3fa;color:#202b3c;'
              'border-bottom:1px solid #d6dee8;padding:.65rem 1rem;font-size:.9rem">'
              f'<strong>{mode}</strong> · Source: <code>{html.escape(branch)}</code> · '
              f'Version {html.escape(revision[:7])} · Retrieved {fetched}<br>{explanation}</aside>')
    return re.sub(r"<body>", lambda _: "<body>\n" + banner, page, count=1, flags=re.IGNORECASE).encode("utf-8")


class GitSource:
    def __init__(self, repository, interval=2, branch=BRANCH):
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
        if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch):
            raise PreviewError("Choose a valid public Git branch for the preview.")
        try:
            self.git("check-ref-format", "refs/heads/" + branch)
        except PreviewError:
            raise PreviewError("Choose a valid public Git branch for the preview.") from None
        self.branch = branch
        self.ref = "refs/remotes/origin/" + branch

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
            raise PreviewError("The preview could not update from GitHub. Check access to the selected preview branch and refresh again.")
        return result.stdout

    def latest(self, force=False):
        with self.lock:
            if force or self.last_fetch is None or time.monotonic() - self.last_fetch >= self.interval:
                self.git("fetch", "--quiet", "origin", f"refs/heads/{self.branch}:{self.ref}")
                commit = self.git("rev-parse", "--verify", self.ref).decode().strip()
                if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
                    raise PreviewError("The selected preview branch could not be read. Refresh again.")
                self.commit = commit
                self.last_fetch = time.monotonic()
            return self.commit

    def read(self, path, revision=None):
        # Restrict reads even when called directly rather than by the HTTP handler.
        if resource_path("/" + path) != path:
            raise FileNotFoundError
        revision = revision or self.latest(force=path.endswith('.html'))
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise PreviewError("The preview revision could not be read.")
        return self.git("show", f"{revision}:{path}", missing_ok=True)

    def synchronized(self):
        """Return a reader for the public branch maintained by Issue automation."""
        if self.branch == BRANCH:
            return self
        reader = GitSource(self.repository, self.interval, branch=BRANCH)
        # Both views fetch into one checkout; serialize their Git fetches.
        reader.lock = self.lock
        return reader

    def page(self, path):
        # HTML, CSS, and the list sorter must share a commit during an update.
        revision = self.latest(force=True)
        content = self.read(path, revision)
        try:
            stylesheet = self.read("prototype/assets/style.css", revision)
        except FileNotFoundError:
            raise PreviewError("The shared stylesheet is missing from GitHub; the preview cannot display it correctly.") from None
        javascript = None
        if LIST_SCRIPT.encode() in content:
            try:
                javascript = self.read('prototype/assets/meetings-list.js', revision)
            except FileNotFoundError:
                raise PreviewError("The meeting-list script is missing; the preview cannot sort the combined list.") from None
        logo = None
        if LOGO_IMAGE.search(content.decode('utf-8')):
            try:
                logo = self.read(LOGO_PATH, revision)
            except FileNotFoundError:
                raise PreviewError('The IFIP logo is missing from GitHub; the preview cannot display it correctly.') from None
        return styled_preview(content, stylesheet, revision, javascript, logo, self.branch), revision


def make_server(source, host="0.0.0.0", port=8001):
    synchronized_source = None
    selection_lock = threading.Lock()

    def synchronized_reader():
        nonlocal synchronized_source
        with selection_lock:
            if synchronized_source is None:
                synchronized_source = source.synchronized()
            return synchronized_source

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.serve(head=False)

        def do_HEAD(self):
            self.serve(head=True)

        def serve(self, head):
            try:
                request_path = url_path(self.path)
                if request_path == SYNCHRONIZED_VIEW.rstrip('/'):
                    self.redirect(SYNCHRONIZED_VIEW)
                    return
                selected_source, view_prefix = source, ''
                if request_path.startswith(SYNCHRONIZED_VIEW):
                    selected_source = synchronized_reader()
                    view_prefix = SYNCHRONIZED_VIEW.rstrip('/')
                    request_path = '/' + request_path[len(SYNCHRONIZED_VIEW):]
                redirect = canonical_url(request_path)
                if redirect:
                    self.redirect(view_prefix + redirect)
                    return
                path = resource_path(request_path)
                if path.endswith(".html"):
                    content, revision = selected_source.page(path)
                else:
                    content = selected_source.read(path)
                    revision = selected_source.commit
            except (FileNotFoundError, ValueError):
                self.send_error(404, "Page not found")
                return
            except PreviewError as error:
                print(str(error), flush=True)
                self.send_error(503, "Preview could not update from GitHub. Check the Codespaces terminal and refresh again.")
                return
            self.send_response(200)
            mime = ('image/png' if path.endswith('.png') else 'text/javascript' if path.endswith('.js')
                    else 'text/css' if path.endswith('.css') else 'text/html')
            self.send_header("Content-Type", mime + ('' if mime == 'image/png' else "; charset=utf-8"))
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Preview-Revision", revision)
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def redirect(self, location):
            self.send_response(307)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

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
    parser.add_argument("--branch", default=BRANCH, help="Public branch to preview; defaults to the existing prototype draft.")
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        source = GitSource(args.repository, branch=args.branch)
        source.latest()
        with make_server(source, port=args.port) as server:
            mode = 'SYNCHRONIZED PREVIEW' if source.branch == BRANCH else 'REVIEW SNAPSHOT'
            print(f"{mode} on port {server.server_port}. Open this port from Codespaces Ports. "
                  f"Source: {source.branch}. Check the Preview status bar for the source and version.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (PreviewError, OSError) as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
