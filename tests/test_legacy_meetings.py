"""Historical content has a strict public-only schema and survives synchronization."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_builder', ROOT / 'scripts/build_legacy_meetings.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
RECORD = {'name': 'Meeting in Example', 'start_date': '2016-03-31', 'end_date': '2016-04-01',
          'location': 'Example room', 'talks': [{'title': 'A talk', 'authors': 'Example presenter',
                                                'abstract': 'First paragraph.\n\nSecond paragraph.'}]}
INDEX = '''<!doctype html><html><head><link rel="stylesheet" href="assets/style.css"></head><body>
<section aria-label="Meetings"><!-- generated-meetings:start --><!-- generated-meetings:end --></section>
</body></html>'''


class LegacyTests(unittest.TestCase):
    def test_dataset_has_only_permitted_fields_and_excludes_the_specified_meeting(self):
        records = json.loads((ROOT / 'prototype/data/legacy-meetings.json').read_text())
        validated = b.validate(records)
        self.assertEqual(len(validated), 38)
        self.assertEqual(sum(len(r['talks']) for r in validated), 227)
        self.assertEqual(sum(bool(t['abstract']) for r in validated for t in r['talks']), 212)
        self.assertTrue(all(t['authors'].strip() for r in validated for t in r['talks']))

    def test_source_presenter_is_the_author_and_collaborators_stay_in_the_abstract(self):
        records = json.loads((ROOT / 'prototype/data/legacy-meetings.json').read_text())
        talks = [t for r in records for t in r['talks']]
        talk = next(t for t in talks if t['title'] == 'Axiomatising relative entropy')
        self.assertEqual(talk['authors'], 'Fabio Zanasi')
        self.assertEqual(talk['abstract'], 'Based on https://arxiv.org/pdf/2603.04530\n\nJoint work with: Ralph Sarkis')
        title_only = next(t for t in talks if t['title'] == 'A logic for abstract (hyper)properties')
        self.assertEqual(title_only['authors'], 'Paolo Baldan')
        self.assertEqual(title_only['abstract'], 'Joint work with: Roberto Bruni, Francesco Ranzato, Diletta Rigo')

    def test_legacy_talks_are_plain_text_and_the_presenter_is_escaped(self):
        record = copy.deepcopy(RECORD)
        record['talks'][0]['authors'] = 'Name <script>unsafe</script>'
        for source in [b.talks_html(record), b.card(record)]:
            self.assertIn('by <span class="talk-authors">Name &lt;script&gt;unsafe&lt;/script&gt;</span>', source)
            self.assertNotIn('<script>', source)
        self.assertNotIn('<a ', b.talks_html(record))
        self.assertNotIn('legacy-meetings/', b.talks_html(record))
        for authors in ['', None, ['Example presenter']]:
            record['talks'][0]['authors'] = authors
            with self.subTest(authors=authors), self.assertRaises(ValueError):
                b.validate([record])

    def test_separator_removal_keeps_punctuation_in_legacy_content(self):
        record = copy.deepcopy(RECORD)
        record['talks'][0].update(title='Values · types', authors='A. Example', abstract='Multiply x · y.')
        source = b.talks_html(record)
        self.assertIn('Values · types</span>', source)
        self.assertIn('>A. Example</span> <details', source)
        self.assertIn('Multiply x · y.', source)
        self.assertNotIn('</span> · <details', source)

    def test_extra_metadata_or_invented_fields_are_rejected(self):
        for key in ('source_url', 'coverage_notes', 'id', 'description', 'authors'):
            record = copy.deepcopy(RECORD); record[key] = 'not permitted'
            with self.subTest(key=key), self.assertRaises(ValueError): b.validate([record])
        record = copy.deepcopy(RECORD); record['talks'][0]['source_url'] = 'not permitted'
        with self.assertRaises(ValueError): b.validate([record])

    def test_only_the_specified_pisa_date_is_excluded(self):
        record = copy.deepcopy(RECORD)
        record.update(name='Meeting in Pisa', location='Pisa, Italy', start_date='2026-11-20', end_date='2026-11-22')
        with self.assertRaises(ValueError): b.validate([record])
        record.update(start_date='2025-11-20', end_date='2025-11-22')
        self.assertEqual(len(b.validate([record])), 1)

    def test_dates_are_valid_canonical_and_sorted_by_start(self):
        other = copy.deepcopy(RECORD); other.update(name='Other meeting', start_date='2025-01-01', end_date='2025-01-01')
        self.assertEqual(b.validate([RECORD, other])[0]['name'], 'Other meeting')
        for start,end in [('2016-04-02','2016-04-01'),('2016-02-30','2016-03-01'),('20160331','2016-04-01')]:
            record = copy.deepcopy(RECORD); record.update(start_date=start,end_date=end)
            with self.assertRaises(ValueError): b.validate([record])
        self.assertIn('31-03-2016', b.schedule(RECORD)); self.assertIn('01-04-2016', b.schedule(RECORD))

    def test_same_list_preserves_private_region_and_uses_meeting_name_without_buttons(self):
        canonical = '<!-- meeting:meeting-38:start --><article class="meeting-card">Existing</article><!-- meeting:meeting-38:end -->'
        source = INDEX.replace('<!-- generated-meetings:end -->', canonical + '<!-- generated-meetings:end -->')
        rendered = b.update_index(source, [RECORD])
        self.assertIn(canonical, rendered)
        self.assertEqual(rendered.count('<section'), 1)
        self.assertLess(rendered.index(b.START), rendered.index('</section>'))
        self.assertEqual(b.update_index(rendered, [RECORD]), rendered)
        card = b.card(RECORD)
        self.assertNotIn('class="button"', card)
        self.assertIn(f'<h3 id="{b.meeting_key(RECORD)}-title"><a href="legacy-meetings/{b.meeting_key(RECORD)}/">Meeting in Example</a></h3>', card)
        self.assertNotIn('github.com', card)
        for unwanted in ('View meeting','organizer-controls','talk-hide','Register','Archive','Hide','Past meetings','Source:'):
            self.assertNotIn(unwanted, card)

    def test_abstracts_are_exact_escaped_and_collapsed_without_placeholders(self):
        record = copy.deepcopy(RECORD)
        record['talks'][0].update(title='<script>bad</script>',abstract='One\n\nTwo <img src=x>  \nLast')
        page = b.page(record)
        self.assertNotIn('<script>', page)
        self.assertNotIn('<img src=x', page)
        self.assertEqual(page.count('<img '), 1)
        self.assertIn('<img src="../../assets/ifip-logo.png" alt="IFIP"', page)
        self.assertIn('&lt;img src=x&gt;', page)
        self.assertIn('One\n\nTwo', page)
        self.assertNotIn('<details open',page)
        self.assertNotIn('github.com',page)
        record['talks'][0]['abstract'] = ''
        self.assertNotIn('class="talk-abstract"', b.page(record))
        record['talks'] = []
        self.assertNotIn('not available',b.page(record))
        self.assertNotIn('No talks',b.card(record))

    def test_generation_is_idempotent_and_refuses_manual_page_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'prototype/data').mkdir(parents=True)
            (root/'prototype/data/legacy-meetings.json').write_text(json.dumps([RECORD]))
            (root/'prototype/index.html').write_text(INDEX)
            target=root/'prototype/legacy-meetings'/b.meeting_key(RECORD)/'index.html'
            target.parent.mkdir(parents=True); target.write_text('Manual content')
            with self.assertRaises(ValueError): b.generate(root)
            self.assertEqual((root/'prototype/index.html').read_text(),INDEX)
            target.unlink()
            self.assertEqual(b.generate(root)[0],1)
            self.assertEqual(b.generate(root,check=True),(1,0))
            self.assertEqual(b.generate(root),(1,0))
        with self.assertRaises(ValueError): b.validate([RECORD,RECORD])

    def test_actual_generated_pages_match_the_restricted_dataset(self):
        self.assertEqual(b.generate(ROOT,check=True),(38,0))


class SynchronizerCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless((ROOT.parent/'meetings/tests/test_meeting_setup.py').exists(), 'Requires the configured sibling private checkout for read-only integration')
    def test_unmodified_synchronizer_and_acceptance_checker_preserve_legacy_content(self):
        private = ROOT.parent/'meetings'
        fixture_spec=importlib.util.spec_from_file_location('private_fixture',private/'tests/test_meeting_setup.py')
        fixture=importlib.util.module_from_spec(fixture_spec); fixture_spec.loader.exec_module(fixture)
        contract_spec=importlib.util.spec_from_file_location('private_contract',private/'.github/scripts/check_meeting_preview.py')
        contract=importlib.util.module_from_spec(contract_spec); contract_spec.loader.exec_module(contract)
        source_before=(private/'.github/scripts/meeting_setup.py').read_bytes()
        m,api=fixture.m,fixture.FakeGitHub()
        api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)['prototype/index.html']=INDEX
        m.prepare(api,m.authorize(api,api.request(4),'issues'))
        files=api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
        files['prototype/index.html']=b.update_index(files['prototype/index.html'],[RECORD])
        site_pages = {path: (ROOT/path).read_text() for path in ['index.html','members/index.html']}
        files.update(site_pages)
        legacy_path='prototype/legacy-meetings/'+b.meeting_key(RECORD)+'/index.html'
        files[legacy_path]=b.page(RECORD)
        expected=b.card(RECORD)
        for maintain in [True,False]:
            api.issues[7]={'number':7,'title':'New fixture proposal','state':'open','body':'### Authors\n\nSpeaker\n\n### Abstract\n\nPublic abstract',
                           'labels':['talk','meeting:meeting-4']}
            m.sync_preview(api,maintain_private=maintain)
            files=api.branch_files(m.PUBLIC,m.PREVIEW_BRANCH)
            self.assertIn(expected,files['prototype/index.html'])
            self.assertEqual(files[legacy_path],b.page(RECORD))
            for path, source in site_pages.items():
                self.assertEqual(files[path], source)
            record={'id':'meeting-4','manifest':m.load_manifest(api,'meeting-4','main'),'status':'active','approved':True,
                    'talks':m.public_talks(api,'meeting-4'),'page':files['prototype/meetings/meeting-4/index.html']}
            self.assertEqual(contract.check_documents(files['prototype/index.html'],[record]),(1,1))
        self.assertEqual((private/'.github/scripts/meeting_setup.py').read_bytes(),source_before)


if __name__ == '__main__': unittest.main()
