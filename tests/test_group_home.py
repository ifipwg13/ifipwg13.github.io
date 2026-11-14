"""The editable data file is the ground truth, never a fixed roster count."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIELDS=('current_chairs','past_chairs','members','emeriti')


class Lists(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True); self.groups={}; self.group=None; self.entry=None; self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='ul' and 'data-group-list' in attrs:
            self.group=attrs['data-group-list']; self.groups[self.group]=[]
        elif tag=='li' and self.group:self.entry=''
    def handle_data(self,data):
        if self.entry is not None:self.entry+=data
    def handle_endtag(self,tag):
        if tag=='li' and self.entry is not None:self.groups[self.group].append(self.entry); self.entry=None
        elif tag=='ul':self.group=None


class GroupHomeTests(unittest.TestCase):
    def test_all_four_rendered_lists_match_the_editable_data_file(self):
        source=(ROOT/'prototype/data/group-people.json').read_text()
        data=json.loads(source)
        self.assertEqual(set(data),{'schema_version','version',*FIELDS})
        self.assertEqual(data['schema_version'],1); self.assertGreater(data['version'],0)
        home=(ROOT/'index.html').read_text()
        self.assertEqual(Lists(home).groups,{key:data[key] for key in FIELDS})
        self.assertIn('name="group-people-revision" content="'+hashlib.sha256(source.encode()).hexdigest()+'"',home)
        self.assertIn('name="group-people-version" content="'+str(data['version'])+'"',home)

    def test_members_and_emeriti_are_sequential_static_sections(self):
        home=(ROOT/'index.html').read_text()
        self.assertLess(home.index('id="members"'),home.index('id="emeriti"'))
        self.assertNotIn('members-grid',home)
        self.assertNotRegex(home,r'<script\b')

    def test_old_members_url_redirects_without_maintaining_another_roster(self):
        page=(ROOT/'members/index.html').read_text()
        self.assertIn('content="0; url=../#members"',page)
        self.assertIn('href="../#members"',page)
        self.assertNotIn('<li>',page)

    def test_main_navigation_and_admin_inputs(self):
        home=(ROOT/'index.html').read_text()
        nav=re.search(r'<nav\b[^>]*aria-label="Main navigation".*?</nav>',home,re.S)[0]
        self.assertEqual(re.findall(r'<a\b[^>]*>([^<]*)</a>',nav),['Home','Meetings','Admin'])
        self.assertIn('href="prototype/admin.html"',nav)
        page=(ROOT/'prototype/admin.html').read_text()
        self.assertEqual(re.findall(r'<textarea id="([^"]+)"',page),['current-chairs','past-chairs','members','emeriti'])
        self.assertIn('id="people-fields" disabled',page)
        self.assertIn('id="admin-token" type="password"',page)


if __name__=='__main__':unittest.main()
