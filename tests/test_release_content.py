"""Check the exact static candidate served by branch-based GitHub Pages."""
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])


class ReleaseContentTests(unittest.TestCase):
    def test_every_local_html_link_and_asset_exists_without_preview_routes(self):
        pages = [ROOT / 'index.html', *ROOT.glob('members/*.html'), *ROOT.glob('prototype/**/*.html')]
        self.assertGreater(len(pages), 10)
        for page in pages:
            source = page.read_text()
            base = 'https://release.invalid/' + str(page.relative_to(ROOT))
            self.assertNotIn('aria-label="Preview status"', source, str(page))
            for link in Links(source).links:
                parsed = urlsplit(urljoin(base, link))
                if parsed.scheme != 'https' or parsed.netloc != 'release.invalid':
                    continue
                with self.subTest(page=page.relative_to(ROOT), link=link):
                    self.assertNotIn('/__preview/', parsed.path)
                    target = ROOT / unquote(parsed.path).lstrip('/')
                    self.assertTrue(target.resolve().is_relative_to(ROOT))
                    if target.is_dir():
                        target = target / 'index.html'
                    self.assertTrue(target.is_file(), str(target.relative_to(ROOT)))

    def test_pages_bypasses_jekyll_and_has_capacity_for_current_static_content(self):
        self.assertTrue((ROOT / '.nojekyll').is_file())
        paths = [ROOT / 'index.html', *ROOT.glob('members/**/index.html'),
                 *(p for p in (ROOT / 'prototype').rglob('*') if p.is_file())]
        self.assertLess(sum(path.stat().st_size for path in paths), 1_000_000_000)
        slides = list((ROOT / 'prototype/slides').rglob('*.*'))
        self.assertTrue(slides)
        self.assertTrue(all(0 < path.stat().st_size <= 10_000_000 for path in slides))

    def test_current_home_data_matches_the_static_page(self):
        import importlib.util
        private = ROOT.parent / 'meetings/.github/scripts/group_profile.py'
        spec = importlib.util.spec_from_file_location('release_profile', private)
        profile = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(profile)
        profile.verify_home((ROOT / 'index.html').read_text(), (ROOT / profile.DATA_PATH).read_text())


if __name__ == '__main__':
    unittest.main()
