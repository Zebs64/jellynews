from pathlib import Path
import unittest

from app.version import APP_VERSION, ASSET_VERSION


ROOT = Path(__file__).resolve().parents[1]
WEB_TEMPLATES = ROOT / "app" / "templates" / "web"


class CacheBusterTests(unittest.TestCase):
    def test_app_version_is_1_1_3(self):
        self.assertEqual(APP_VERSION, "1.1.3")
        self.assertEqual(ASSET_VERSION, APP_VERSION)

    def test_web_templates_version_mutable_assets(self):
        expected_favicon_links = [
            '/static/brand/jellynews-mark.svg?v={{ asset_version }}',
            '/static/brand/favicon-32.png?v={{ asset_version }}',
            '/static/brand/favicon.ico?v={{ asset_version }}',
            '/static/brand/apple-touch-icon.png?v={{ asset_version }}',
            '/static/brand/site.webmanifest?v={{ asset_version }}',
        ]
        for name in ["dashboard.html", "login.html", "setup.html", "unsubscribe.html"]:
            with self.subTest(template=name):
                source = (WEB_TEMPLATES / name).read_text(encoding="utf-8")
                self.assertIn('/static/style.css?v={{ asset_version }}', source)
                for link in expected_favicon_links:
                    self.assertIn(link, source)

        dashboard = (WEB_TEMPLATES / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('/static/app.js?v={{ asset_version }}', dashboard)
        self.assertIn('/static/brand/jellynews-mark.svg?v={{ asset_version }}', dashboard)
        self.assertIn('/static/brand/jellynews-mascot.png?v={{ asset_version }}', dashboard)
        self.assertIn('alt="Mascotte JellyNews distribuant le courrier de la médiathèque"', dashboard)
        self.assertIn("JellyNews v{{ app_version }}", dashboard)

    def test_favicon_assets_are_shipped_with_app_static_files(self):
        for name in [
            "favicon-16.png",
            "favicon-32.png",
            "favicon-48.png",
            "favicon.ico",
            "apple-touch-icon.png",
            "icon-192.png",
            "icon-512.png",
            "site.webmanifest",
            "jellynews-mascot.png",
        ]:
            with self.subTest(asset=name):
                self.assertTrue((ROOT / "app" / "static" / "brand" / name).is_file())

    def test_css_versions_static_svg_backgrounds(self):
        source = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("/static/brand/media-current-bg.svg?v=1.1.3", source)
        self.assertIn("/static/brand/empty-media-mail.svg?v=1.1.3", source)
        self.assertNotIn("media-current-bg.svg')", source)
        self.assertNotIn("empty-media-mail.svg')", source)


if __name__ == "__main__":
    unittest.main()
