"""Source association and bounded-file import tests; no network or real records."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('slide_import', ROOT / 'scripts/import_legacy_slides.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
b = m.builder
PDF = b'%PDF-1.7\nFictitious test data\n%%EOF\n'
RECORD = {'name': 'Meeting in Example, Italy, 01 - 02 March 2020', 'location': 'Example, Italy',
          'start_date': '2020-03-01', 'end_date': '2020-03-02',
          'talks': [{'title':'Identical title','authors':'A. Presenter','abstract':'Unchanged abstract.'}]}
INDEX = '<html><body><!-- generated-meetings:start -->PRESERVE LIVE MEETINGS<!-- generated-meetings:end --></body></html>'


def page(record=RECORD, talk_id=7, slides='/system/slides/7/original/talk.pdf?123', presenter='A. Presenter'):
    return ('<h1>Site name</h1><h1>' + record['name'] + '</h1><ul><li>'
            + '<a href="/talks/' + str(talk_id) + '">Identical title</a> by '
            + '<a href="/members/1">' + presenter + '</a><i><a href="/talks/' + str(talk_id) + '">abstract</a>'
            + '<a href="' + slides + '">slides</a><a href="/system/papers/7/original/paper.pdf">paper</a></i></li></ul>')


def office(extension):
    if extension == 'ppt':
        return b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\0' * 504
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('ppt/presentation.xml','<presentation/>')
    return out.getvalue()


class SourceTests(unittest.TestCase):
    def test_meeting_title_presenter_and_source_id_all_required(self):
        item = m.proposals(page(),RECORD,m.SOURCE + '/meetings/1')[0]
        self.assertEqual(item['status'],'candidate')
        self.assertEqual(item['talk_number'],1)
        self.assertEqual(item['source_talk'],'7')
        self.assertIn('/system/slides/7/',item['source_url'])
        for source in (page(presenter='Other presenter'),page(slides='/system/slides/8/original/talk.pdf'),
                       page(slides='/system/papers/7/original/talk.pdf'),
                       page(slides='http://other.invalid/system/slides/7/original/talk.pdf')):
            self.assertEqual(m.proposals(source,RECORD,m.SOURCE + '/meetings/1')[0]['status'],'ambiguous')
        wrong = copy.deepcopy(RECORD); wrong['name'] = 'Another meeting'
        with self.assertRaises(m.ImportProblem):m.proposals(page(wrong),RECORD,m.SOURCE + '/meetings/1')

    def test_duplicates_do_not_fall_back_to_order_or_filename(self):
        record = copy.deepcopy(RECORD); record['talks'] *= 2
        self.assertEqual(m.proposals(page(),record,m.SOURCE + '/meetings/1')[0]['status'],'ambiguous')
        source = page().replace('</i>','<a href="/system/slides/7/original/second.pdf">slides</a></i>')
        items=m.proposals(source,RECORD,m.SOURCE + '/meetings/1')
        self.assertEqual([x['status'] for x in items],['ambiguous','ambiguous'])

    def test_paper_or_abstract_links_alone_never_become_slides(self):
        source = page().replace('>slides<','>paper<')
        self.assertEqual(m.proposals(source,RECORD,m.SOURCE + '/meetings/1'),[])

    def test_meeting_dates_location_and_known_prefix_are_verified(self):
        m.verify_meeting(RECORD)
        m.verify_meeting(RECORD | {'name':RECORD['name'].removeprefix('Meeting in ')})
        for changes in ({'location':'Other room'},{'start_date':'2020-03-02'}, {'end_date':'2020-03-03'}):
            with self.subTest(changes=changes),self.assertRaises(m.ImportProblem):m.verify_meeting(RECORD | changes)
        for name,start,end in [('Example, Italy, 31 March - 01 April 2020','2020-03-31','2020-04-01'),
                               ('Example, Italy, 01 March 2020','2020-03-01','2020-03-01')]:
            m.verify_meeting(RECORD | {'name':name,'start_date':start,'end_date':end})

    def test_unrecognized_fields_and_cross_meeting_file_references_are_rejected(self):
        record = copy.deepcopy(RECORD)
        digest = hashlib.sha256(PDF).hexdigest()
        path='slides/' + b.meeting_key(record) + '/talk-1-' + digest + '.pdf'
        record['talks'][0]['slides']=path
        b.validate([record])
        for bad in ('https://example.invalid/file.pdf','../secret.pdf',path.replace('talk-1-','talk-2-'),
                    path.replace(b.meeting_key(record),'legacy-20200301-aaaaaaaaaaaa')):
            record['talks'][0]['slides']=bad
            with self.assertRaises(ValueError):b.validate([record])

    def test_original_formats_retained_and_html_error_pages_rejected(self):
        for ext in b.SLIDE_TYPES:
            content=PDF if ext=='pdf' else office(ext)
            m.validate_file(content,ext)
            with self.assertRaises(m.ImportProblem):m.validate_file(b'<html>Not found</html>',ext)
        with self.assertRaises(m.ImportProblem):m.validate_file(b'', 'pdf')
        with self.assertRaises(m.ImportProblem):m.validate_file(office('pptx'), 'zip')


class FetchTests(unittest.TestCase):
    def test_actual_byte_limit_accepts_boundary_and_stops_at_one_byte_over(self):
        for size, accepted in [(b.MAX_SLIDE_BYTES,True),(b.MAX_SLIDE_BYTES+1,False)]:
            response=io.BytesIO(b'x'*size);response.url=m.SOURCE + '/system/slides/7/original/test.pdf'
            response.headers={'Content-Length':'3','Content-Type':'text/plain'}
            with patch.object(m.urllib.request,'build_opener') as opener:
                opener.return_value.open.return_value=response
                if accepted:self.assertEqual(len(m.Fetcher().read(response.url,b.MAX_SLIDE_BYTES)),size)
                else:
                    with self.assertRaises(m.TooLarge):m.Fetcher().read(response.url,b.MAX_SLIDE_BYTES)
                request=opener.return_value.open.call_args.args[0]
                self.assertIsNone(request.get_header('Authorization'))
                self.assertEqual(request.get_header('Accept-encoding'),'identity')

    def test_source_errors_have_bounded_retries_and_no_guessed_alternative(self):
        url=m.SOURCE + '/meetings/1'
        with patch.object(m.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.HTTPError(url,500,'error',{},None)
            with self.assertRaisesRegex(m.ImportProblem,'HTTP 500'):m.Fetcher().read(url,100)
            self.assertEqual(opener.return_value.open.call_count,2)
        with self.assertRaises(m.ImportProblem):m.allowed_url('http://other.invalid/file.pdf')
        with self.assertRaises(m.ImportProblem):m.allowed_url(m.SOURCE+':bad/meetings/1')

    def test_truncated_http_transfer_is_reported_after_bounded_retries(self):
        with patch.object(m.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=m.http.client.IncompleteRead(b'partial')
            with self.assertRaises(m.ImportProblem):m.Fetcher().read(m.SOURCE+'/meetings/1',100)
            self.assertEqual(opener.return_value.open.call_count,2)

    def test_short_reads_are_accumulated_and_silent_truncation_is_never_cached(self):
        url=m.SOURCE+'/system/slides/7/original/talk.pdf'
        class Chunked(io.BytesIO):
            def read(self,size=-1):return super().read(min(size,3))
        response=Chunked(PDF);response.url=url;response.headers={'Content-Length':str(len(PDF))}
        with patch.object(m.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            self.assertEqual(m.Fetcher().read(url,100),PDF)
        replies=[]
        for _ in range(2):
            r=io.BytesIO(PDF);r.url=url;r.headers={'Content-Length':'1000'};replies.append(r)
        with tempfile.TemporaryDirectory() as cache,patch.object(m.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=replies
            with self.assertRaises(m.ImportProblem):m.Fetcher(cache).read(url,100)
            self.assertEqual(list(Path(cache).iterdir()),[])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'prototype/data').mkdir(parents=True)
        self.data=self.root/'prototype/data/legacy-meetings.json'
        self.data.write_text(json.dumps([RECORD],ensure_ascii=False,indent=2)+'\n')
        (self.root/'prototype/index.html').write_text(INDEX)

    def fetcher(self, data=PDF, unavailable=False):
        class Fake:
            def read(inner,url,limit,html=False):
                if url==m.SOURCE + '/meetings':
                    return ('<a href="/meetings/1">' + RECORD['name'].removeprefix('Meeting in ')+'</a>'
                            '<a href="/meetings/40">Pisa, Italy, 20 - 22 November 2026</a>').encode()
                if url==m.SOURCE + '/meetings/1':
                    if unavailable:raise m.ImportProblem('Source returned HTTP 500.')
                    return page().encode()
                if '/system/slides/7/' in url:
                    if len(data)>limit:raise m.TooLarge('File exceeds 10,000,000 bytes.')
                    return data
                raise AssertionError('Unexpected source request: '+url)
        return Fake()

    def test_dry_run_writes_nothing_and_import_is_idempotent_without_text_changes(self):
        before=self.data.read_bytes()
        report=m.run(self.root,self.fetcher())
        self.assertEqual(report[0]['status'],'candidate');self.assertEqual(self.data.read_bytes(),before)
        self.assertFalse((self.root/'prototype/slides').exists())
        report=m.run(self.root,self.fetcher(),apply=True)
        self.assertEqual(report[0]['status'],'imported')
        actual=json.loads(self.data.read_text());reference=actual[0]['talks'][0].pop('slides')
        self.assertEqual(actual,json.loads(before))
        self.assertEqual((self.root/'prototype'/reference).read_bytes(),PDF)
        snapshots={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        m.run(self.root,self.fetcher(),apply=True)
        self.assertEqual(snapshots,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertIn('PRESERVE LIVE MEETINGS',(self.root/'prototype/index.html').read_text())

    def test_oversized_and_unavailable_sources_leave_talks_without_links(self):
        for fetcher,status in [(self.fetcher(b'x'*(b.MAX_SLIDE_BYTES+1)),'oversized'),
                               (self.fetcher(unavailable=True),'unavailable-meeting')]:
            report=m.run(self.root,fetcher,apply=True)
            self.assertEqual(report[0]['status'],status)
            self.assertNotIn('slides',json.loads(self.data.read_text())[0]['talks'][0])

    def test_binary_files_are_verified_before_render_and_tampering_cannot_pass(self):
        m.run(self.root,self.fetcher(),apply=True)
        records=json.loads(self.data.read_text());path=self.root/'prototype'/records[0]['talks'][0]['slides']
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):b.generate(self.root,check=True)
        path.unlink()
        with self.assertRaisesRegex(ValueError,'missing'):b.generate(self.root,check=True)

    def test_matching_title_in_another_meeting_does_not_receive_the_file(self):
        other=copy.deepcopy(RECORD);other.update(name='Meeting in Other, Italy, 01 - 02 March 2020',location='Other, Italy')
        self.data.write_text(json.dumps([RECORD,other]))
        report=m.run(self.root,self.fetcher(),apply=True)
        records=json.loads(self.data.read_text())
        matched=next(r for r in records if r['name']==RECORD['name'])
        unmatched=next(r for r in records if r['name']==other['name'])
        self.assertIn('slides',matched['talks'][0]);self.assertNotIn('slides',unmatched['talks'][0])
        self.assertTrue(any(row['status']=='unavailable-meeting' for row in report))


if __name__=='__main__':unittest.main()
