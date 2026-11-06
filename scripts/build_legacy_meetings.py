"""Render approved historical content locally; no network or private-repo access."""
import argparse
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
START, END = '<!-- legacy-meetings:start -->', '<!-- legacy-meetings:end -->'
GENERATED = '<!-- generated-legacy-meeting -->'
SCRIPT = '<script src="assets/meetings-list.js" defer></script>'


def validate(records):
    if not isinstance(records, list):
        raise ValueError('Meeting data must be a list.')
    identifiers = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {'name', 'start_date', 'end_date', 'location', 'talks'}:
            raise ValueError('Only the approved meeting fields are allowed.')
        for field in ('name', 'location', 'start_date', 'end_date'):
            if not isinstance(record[field], str) or not record[field].strip():
                raise ValueError('A required meeting field is missing.')
        start, end = dt.date.fromisoformat(record['start_date']), dt.date.fromisoformat(record['end_date'])
        if (start.isoformat(), end.isoformat()) != (record['start_date'], record['end_date']):
            raise ValueError('Dates must use YYYY-MM-DD.')
        if end < start:
            raise ValueError('Meeting dates are reversed.')
        if re.search(r'\bpisa\b', record['name'] + ' ' + record['location'], re.I) and (record['start_date'], record['end_date']) == ('2026-11-20', '2026-11-22'):
            raise ValueError('The excluded meeting must not be imported.')
        if not isinstance(record['talks'], list):
            raise ValueError('Talks must be a list.')
        for talk in record['talks']:
            if not isinstance(talk, dict) or set(talk) != {'title', 'authors', 'abstract'}:
                raise ValueError('Only talk titles, authors, and abstracts are allowed.')
            if (not isinstance(talk['title'], str) or not talk['title'].strip()
                    or not isinstance(talk['authors'], str) or not talk['authors'].strip()
                    or not isinstance(talk['abstract'], str)):
                raise ValueError('Invalid talk content.')
        key = meeting_key(record)
        if key in identifiers:
            raise ValueError('Duplicate historical meeting.')
        identifiers.add(key)
    return sorted(records, key=lambda item: item['start_date'], reverse=True)


def meeting_key(record):
    identity = json.dumps([record['name'], record['start_date']], ensure_ascii=False)
    return 'legacy-' + record['start_date'].replace('-', '') + '-' + hashlib.sha256(identity.encode()).hexdigest()[:12]


def schedule(record):
    def time(value):
        return f'<time datetime="{value}">{dt.date.fromisoformat(value).strftime("%d-%m-%Y")}</time>'
    result = time(record['start_date'])
    if record['end_date'] != record['start_date']:
        result += ' – ' + time(record['end_date'])
    return result


def talks_html(record):
    if not record['talks']:
        return ''
    rows = []
    for number, talk in enumerate(record['talks'], 1):
        ident = meeting_key(record) + '-talk-' + str(number)
        content = ('<span class="talk-title">' + html.escape(talk['title']) + '</span> by '
                   '<span class="talk-authors">' + html.escape(talk['authors']) + '</span>')
        if talk['abstract']:
            escaped = html.escape(talk['abstract'])
            escaped = re.sub(r'[ \t]+$', lambda match: ''.join('&#32;' if c == ' ' else '&#9;' for c in match[0]), escaped, flags=re.MULTILINE)
            content += (' <details class="talk-abstract"><summary>Abstract</summary>'
                        '<div class="abstract-text">' + escaped + '</div></details>')
        rows.append('<li id="' + ident + '">' + content + '</li>')
    return '<ul class="talk-list">' + ''.join(rows) + '</ul>'


def card(record):
    key = meeting_key(record)
    talks = talks_html(record)
    disclosure = ('<details class="talks-overview"><summary>Talks (' + str(len(record['talks']))
                  + ')</summary>' + talks + '</details>') if talks else ''
    result = f'''<article class="legacy-meeting-card" aria-labelledby="{key}-title">
        <h3 id="{key}-title"><a href="legacy-meetings/{key}/">{html.escape(record['name'])}</a></h3>
        <div class="meeting-summary">
          <p><strong>When:</strong> {schedule(record)}</p>
          <p><strong>Where:</strong> {html.escape(record['location'])}</p>
        </div>
        {disclosure}
      </article>'''
    return '\n'.join(line.rstrip() for line in result.split('\n'))


def page(record):
    talks = talks_html(record)
    section = '<section aria-labelledby="talks-heading"><h2 id="talks-heading">Talks</h2>' + talks + '</section>' if talks else ''
    result = f'''<!doctype html>
{GENERATED}
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(record['name'])} · Meetings</title>
  <link rel="stylesheet" href="../../assets/style.css">
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header"><div class="container">
    <a class="brand-logo" href="../../../" aria-label="IFIP WG1.3 home"><img src="../../assets/ifip-logo.png" alt="IFIP" width="75" height="142"></a>
    <p class="site-brand"><a href="../../../">IFIP WG1.3</a></p>
    <nav class="site-nav" aria-label="Main navigation"><a href="../../">All meetings</a></nav>
  </div></header>
  <main id="main" class="container">
    <h1>{html.escape(record['name'])}</h1>
    <div class="meeting-summary">
      <p><strong>When:</strong> {schedule(record)}</p>
      <p><strong>Where:</strong> {html.escape(record['location'])}</p>
    </div>
    {section}
  </main>
  <footer class="container site-footer"><p><a href="../../">Back to all meetings</a></p></footer>
</body>
</html>
'''
    return '\n'.join(line.rstrip() for line in result.split('\n'))


def update_index(source, records):
    boundary = '<!-- generated-meetings:end -->'
    if source.count(boundary) != 1:
        raise ValueError('The existing meeting region must be preserved.')
    if START not in source and END not in source:
        source = source.replace(boundary, boundary + '\n      ' + START + '\n      ' + END, 1)
    if source.count(START) != 1 or source.count(END) != 1 or source.index(START) > source.index(END):
        raise ValueError('Invalid historical content boundary.')
    # Both regions share the existing section. These markers add no visual group.
    source = source[:source.index(START) + len(START)] + '\n      ' + '\n      '.join(card(r) for r in records) + '\n      ' + source[source.index(END):]
    if SCRIPT not in source:
        if source.count('</body>') != 1:
            raise ValueError('Expected one page body.')
        source = source.replace('</body>', '  ' + SCRIPT + '\n</body>', 1)
    return source


def generate(root=ROOT, check=False):
    records = validate(json.loads((root / 'prototype/data/legacy-meetings.json').read_text()))
    index = root / 'prototype/index.html'
    outputs = {index: update_index(index.read_text(), records)}
    directory = root / 'prototype/legacy-meetings'
    outputs.update({directory / meeting_key(r) / 'index.html': page(r) for r in records})
    stale = [path for path in directory.glob('*/index.html') if path not in outputs and GENERATED in path.read_text()]
    different = [path for path, content in outputs.items() if not path.exists() or path.read_text() != content]
    if not check:
        for path in different:
            if path.exists() and path != index and GENERATED not in path.read_text():
                raise ValueError('Refusing to replace a manually maintained page.')
        for path in different:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(outputs[path])
        for path in stale:
            path.unlink()
    return len(records), len(different) + len(stale)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    count, changes = generate(check=args.check)
    print(f'{count} historical meetings; {changes} ' + ('out-of-date files.' if args.check else 'files updated.'))
    raise SystemExit(1 if args.check and changes else 0)
