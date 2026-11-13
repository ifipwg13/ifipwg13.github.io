"""Import explicitly linked legacy slides; dry-run by default, no private API.

Run with --apply only after reviewing the source associations. Cache and report
paths must stay outside the website checkout. Ordinary page generation is offline.
"""
import argparse
import calendar
from collections import Counter
import concurrent.futures
import copy
import datetime as dt
import hashlib
import http.client
import html.parser
import importlib.util
import io
import json
from pathlib import Path
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile

_spec = importlib.util.spec_from_file_location('legacy_builder', Path(__file__).with_name('build_legacy_meetings.py'))
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)
HOST = 'ifipwg13.cs.ovgu.de'
SOURCE = 'http://' + HOST
MAX_HTML = 2_000_000


class ImportProblem(ValueError):
    pass


class TooLarge(ImportProblem):
    pass


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        return ''.join(child.text() if isinstance(child, Node) else child for child in self.children)

    def all(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.all(tag)


class Document(html.parser.HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag == 'br':
            node.children.append(' ')
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
                       'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def normal(value):
    return ' '.join(unicodedata.normalize('NFC', value).split())


def meeting_label(value):
    return normal(value).removeprefix('Meeting in ')


def verify_meeting(record):
    """Independently check the location/date encoded in the matched heading."""
    prefix = normal(record['location']) + ', '
    label = meeting_label(record['name'])
    if not label.startswith(prefix):
        raise ImportProblem('Meeting name and location do not agree.')
    dates = label[len(prefix):]
    single = re.fullmatch(r'(\d{1,2}) ([A-Za-z]+) (\d{4})', dates)
    same_month = re.fullmatch(r'(\d{1,2}) - (\d{1,2}) ([A-Za-z]+) (\d{4})', dates)
    different_months = re.fullmatch(r'(\d{1,2}) ([A-Za-z]+) - (\d{1,2}) ([A-Za-z]+) (\d{4})', dates)
    months = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name}
    try:
        if single:
            day, month, year = single.groups()
            start = end = dt.date(int(year), months[month.casefold()], int(day))
        elif same_month:
            first, last, month, year = same_month.groups()
            start = dt.date(int(year), months[month.casefold()], int(first))
            end = dt.date(int(year), months[month.casefold()], int(last))
        elif different_months:
            first, first_month, last, last_month, year = different_months.groups()
            start = dt.date(int(year), months[first_month.casefold()], int(first))
            end = dt.date(int(year), months[last_month.casefold()], int(last))
        else:
            raise ValueError
    except (KeyError, ValueError):
        raise ImportProblem('The source meeting dates could not be verified.') from None
    if (start.isoformat(), end.isoformat()) != (record['start_date'], record['end_date']):
        raise ImportProblem('Meeting heading dates differ from the existing record.')


def allowed_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (parsed.scheme in {'http', 'https'} and parsed.hostname == HOST and not parsed.username
                 and not parsed.password and parsed.port in {None, 80, 443} and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ImportProblem('The source link is outside the approved legacy host.')
    return url


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        allowed_url(new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


class Fetcher:
    def __init__(self, cache=None, refresh=False):
        self.cache = Path(cache) if cache else None
        self.refresh = refresh

    def read(self, url, limit, html=False):
        allowed_url(url)
        key = hashlib.sha256(url.encode()).hexdigest() + ('.html' if html else '.bin')
        target = self.cache / key if self.cache else None
        if target and target.exists() and not self.refresh:
            if target.stat().st_size > limit:
                raise TooLarge('File exceeds 10,000,000 bytes.')
            return target.read_bytes()
        opener = urllib.request.build_opener(SameHostRedirect())
        for attempt in range(2):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'IFIP-legacy-slides-import',
                                                              'Accept-Encoding': 'identity'})
                with opener.open(request, timeout=25) as response:
                    allowed_url(response.url)
                    # Content-Length/MIME on the old server are not reliable.
                    chunks, size = [], 0
                    while size <= limit:
                        chunk = response.read(min(1_048_576, limit + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk); size += len(chunk)
                    body = b''.join(chunks)
                    if len(body) <= limit:
                        declared = getattr(response, 'headers', {}).get('Content-Length', '')
                        if declared.isdigit() and len(body) < int(declared):
                            raise http.client.IncompleteRead(body)
                if len(body) > limit:
                    raise TooLarge('File exceeds ' + str(limit) + ' bytes.')
                if target:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                return body
            except urllib.error.HTTPError as error:
                if attempt == 1 or error.code < 500:
                    raise ImportProblem('Source returned HTTP ' + str(error.code) + '.') from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if attempt == 1:
                    raise ImportProblem('Source could not be reached after two attempts.') from None
        raise ImportProblem('Source could not be read.')


def index_entries(source):
    found = {}
    for anchor in Document(source).root.all('a'):
        href = anchor.attrs.get('href', '')
        if re.fullmatch(r'/meetings/[1-9][0-9]*', href) and normal(anchor.text()):
            label = meeting_label(anchor.text())
            if href in found and found[href] != label:
                raise ImportProblem('The index contains conflicting meeting labels.')
            found[href] = label
    return found


def proposals(source, record, url):
    document = Document(source)
    headings = [meeting_label(node.text()) for node in document.root.all('h1')]
    if headings.count(meeting_label(record['name'])) != 1:
        raise ImportProblem('The source page does not uniquely identify the expected meeting.')
    verify_meeting(record)
    results = []
    for anchor in document.root.all('a'):
        if not re.fullmatch(r'[\s\[\](]*slides[\s\[\])]*', anchor.text(), re.I):
            continue
        row = anchor.parent
        while row is not None and row.tag != 'li':
            row = row.parent
        item = {'meeting': record['name'], 'title': '', 'authors': '', 'source_page': url,
                'source_url': urllib.parse.urljoin(url, anchor.attrs.get('href', ''))}
        results.append(item)
        if row is None:
            item.update(status='ambiguous', reason='Slides link has no enclosing talk row.'); continue
        titles = [a for a in row.all('a') if re.fullmatch(r'/talks/[1-9][0-9]*', a.attrs.get('href', ''))
                  and normal(a.text()).casefold() != 'abstract']
        presenters = [a for a in row.all('a') if re.fullmatch(r'/members/[1-9][0-9]*', a.attrs.get('href', ''))]
        if len(titles) != 1 or len(presenters) != 1:
            item.update(status='ambiguous', reason='Talk title or presenter is not unique in its source row.'); continue
        item.update(title=normal(titles[0].text()), authors=normal(presenters[0].text()))
        source_id = titles[0].attrs['href'].rsplit('/', 1)[-1]
        try:
            allowed_url(item['source_url'])
            file_match = re.fullmatch(r'/system/slides/([1-9][0-9]*)/original/[^/]+',
                                     urllib.parse.urlsplit(item['source_url']).path)
            if not file_match or file_match[1] != source_id:
                raise ImportProblem('Slide URL and source talk identifier differ.')
            extension = Path(urllib.parse.unquote(urllib.parse.urlsplit(item['source_url']).path)).suffix.lower().lstrip('.')
            if extension not in builder.SLIDE_TYPES:
                raise ImportProblem('Unrecognized original slide format; review before importing.')
            matches = [i for i, talk in enumerate(record['talks'], 1)
                       if (normal(talk['title']), normal(talk['authors'])) == (item['title'], item['authors'])]
            if len(matches) != 1:
                raise ImportProblem('Meeting/title/presenter does not match exactly one existing talk.')
            item.update(status='candidate', talk_number=matches[0], extension=extension, source_talk=source_id)
        except ImportProblem as error:
            item.update(status='ambiguous', reason=str(error))
    counts = Counter(item.get('talk_number') for item in results if item['status'] == 'candidate')
    for item in results:
        if item['status'] == 'candidate' and counts[item['talk_number']] != 1:
            item.update(status='ambiguous', reason='More than one slide link belongs to this talk.')
    return results


def validate_file(content, extension):
    if extension not in builder.SLIDE_TYPES:
        raise ImportProblem('Unrecognized original slide format.')
    if not content or len(content) > builder.MAX_SLIDE_BYTES:
        raise ImportProblem('Slide file is empty or exceeds 10,000,000 bytes.')
    if extension == 'pdf':
        if not re.match(rb'%PDF-(?:1\.[0-7]|2\.0)[\r\n]', content) or not re.search(rb'%%EOF[\s\0]*$', content):
            raise ImportProblem('The linked file is not a complete PDF.')
    elif extension == 'ppt':
        if len(content) < 512 or not content.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            raise ImportProblem('The linked file is not an original PowerPoint binary.')
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                for name in ('[Content_Types].xml', 'ppt/presentation.xml'):
                    member = archive.getinfo(name)
                    if member.file_size > 2_000_000 or member.flag_bits & 1:
                        raise ValueError
                    if not archive.read(member).lstrip().startswith(b'<'):
                        raise ValueError
        except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError, OSError):
            raise ImportProblem('The linked file is not a readable original PowerPoint presentation.') from None


def collect(records, fetcher, progress=lambda message: None):
    entries = index_entries(fetcher.read(SOURCE + '/meetings', MAX_HTML, html=True).decode('utf-8'))
    work, report, selected = [], [], set()
    for path, label in entries.items():
        matches = [record for record in records if meeting_label(record['name']) == label]
        if not matches:
            continue  # In particular, never add the excluded Pisa meeting.
        if len(matches) != 1:
            raise ImportProblem('The index matches more than one existing legacy meeting.')
        key = builder.meeting_key(matches[0])
        if key in selected:
            raise ImportProblem('The index maps multiple pages to the same legacy meeting.')
        selected.add(key); work.append((matches[0], SOURCE + path))
    for record in records:
        if builder.meeting_key(record) not in selected:
            report.append({'meeting': record['name'], 'status': 'unavailable-meeting',
                           'reason': 'Meeting is missing from the current source index.'})
    def scan(pair):
        record, url = pair
        try:
            items = proposals(fetcher.read(url, MAX_HTML, html=True).decode('utf-8'), record, url)
            return items or [{'meeting': record['name'], 'source_page': url, 'status': 'no-slides'}]
        except (ImportProblem, UnicodeError) as error:
            return [{'meeting': record['name'], 'source_page': url, 'status': 'unavailable-meeting', 'reason': str(error)}]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for items in pool.map(scan, work):
            report.extend(items)
            progress('Scanned ' + items[0]['meeting'])
    return report


def run(root, fetcher, apply=False, progress=lambda message: None):
    root = root.resolve()
    path = root / 'prototype/data/legacy-meetings.json'
    original = path.read_bytes()
    records = builder.validate(json.loads(original))
    result = copy.deepcopy(records)
    by_name = {record['name']: record for record in result}
    report = collect(records, fetcher, progress)
    files = {}
    if apply:
        for item in report:
            if item['status'] != 'candidate':
                continue
            try:
                content = fetcher.read(item['source_url'], builder.MAX_SLIDE_BYTES)
                validate_file(content, item['extension'])
                digest = hashlib.sha256(content).hexdigest()
                record = by_name[item['meeting']]
                target = ('slides/' + builder.meeting_key(record) + '/talk-' + str(item['talk_number'])
                          + '-' + digest + '.' + item['extension'])
                record['talks'][item['talk_number'] - 1]['slides'] = target
                files[root / 'prototype' / target] = content
                item.update(status='imported', path=target, bytes=len(content), sha256=digest)
            except TooLarge as error:
                item.update(status='oversized', reason=str(error))
            except ImportProblem as error:
                item.update(status='unavailable-file', reason=str(error))
            progress(item['status'] + ': ' + item['meeting'] + ' / ' + item['title'])
        builder.validate(result)
        if path.read_bytes() != original:
            raise ImportProblem('The dataset changed during import; no website files were written.')
        for target, content in files.items():
            if (target.is_symlink() or not target.resolve().is_relative_to(root / 'prototype/slides')
                    or (target.exists() and target.read_bytes() != content)):
                raise ImportProblem('A destination has independently modified content; review it before importing.')
        # Guard Pages' published-size limit without modifying unrelated data.
        total = sum(p.stat().st_size for p in (root / 'prototype').rglob('*') if p.is_file() and p not in files)
        if total + sum(map(len, files.values())) > 900_000_000:
            raise ImportProblem('The import approaches the GitHub Pages size limit; review aggregate storage first.')
        for target, content in files.items():
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
        updated = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
        if updated != original:
            path.write_bytes(updated)
        builder.generate(root)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--root', type=Path, default=builder.ROOT)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.report.resolve().is_relative_to(root) or (args.cache and args.cache.resolve().is_relative_to(root)):
        parser.error('Keep source caches and audit reports outside the public website checkout.')
    try:
        report = run(root, Fetcher(args.cache, args.refresh), args.apply,
                     progress=lambda text: print(text, flush=True))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(dict(Counter(item['status'] for item in report)), sort_keys=True))
    except (ImportProblem, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
