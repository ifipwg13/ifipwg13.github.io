"""Include the talk form's script and its CSP hash in the static HTML.

This keeps one editable JS source while letting older preview servers deliver
a complete working form without a second script request. Standard library only.
"""
import argparse
import base64
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- talk-form-script:start -->'
END = '<!-- talk-form-script:end -->'


def render(page, javascript):
    if page.count(START) != 1 or page.count(END) != 1 or page.index(END) <= page.index(START):
        raise ValueError('The talk form needs its script generation markers.')
    if re.search(r'</script', javascript, re.IGNORECASE):
        raise ValueError('The script source must not contain an HTML script terminator.')
    content = '\n' + javascript.rstrip('\n') + '\n'
    digest = base64.b64encode(hashlib.sha256(content.encode('utf-8')).digest()).decode('ascii')
    page, count = re.subn(r"script-src 'self'(?: 'sha256-[A-Za-z0-9+/=]+')?",
                          "script-src 'self' 'sha256-" + digest + "'", page)
    if count != 1:
        raise ValueError('The talk form needs its restricted script-src policy.')
    block = START + '\n<script>' + content + '</script>\n  ' + END
    return page[:page.index(START)] + block + page[page.index(END) + len(END):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'prototype/submit-talk.html'
    page = path.read_text()
    expected = render(page, (ROOT / 'prototype/assets/talk-submission.js').read_text())
    if args.check:
        if page != expected:
            parser.exit(1, 'Talk form is stale. Run python3 scripts/build_talk_form.py\n')
    else:
        path.write_text(expected)


if __name__ == '__main__':
    main()
