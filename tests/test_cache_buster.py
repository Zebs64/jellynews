from pathlib import Path
import unittest

from app.version import APP_VERSION, ASSET_VERSION


ROOT = Path(__file__).resolve().parents[1]
WEB_TEMPLATES = ROOT / "app" / "templates" / "web"


class CacheBusterTests(unittest.TestCase):
    def test_app_version_is_1_0_3(self):
        self.assertEqual(APP_VERSION, "1.0.3")
        self.assertEqual(ASSET_VERSION, APP_VERSION)

    def test_web_templates_version_mutable_assets(self):
        for name in ["dashboard.html", "login.html", "setup.html", "unsubscribe.html"]:
            with self.subTest(template=name):
                source = (WEB_TEMPLATES / name).read_text(encoding="utf-8")
                self.assertIn('/static/style.css?v={{ asset_version }}', source)

        dashboard = (WEB_TEMPLATES / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('/static/app.js?v={{ asset_version }}', dashboard)
        self.assertIn('/static/brand/jellynews-mark.svg?v={{ asset_version }}', dashboard)
        self.assertIn("JellyNews v{{ app_version }}", dashboard)

    def test_css_versions_static_svg_backgrounds(self):
        source = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("/static/brand/media-current-bg.svg?v=1.0.3", source)
        self.assertIn("/static/brand/empty-media-mail.svg?v=1.0.3", source)
        self.assertNotIn("media-current-bg.svg')", source)
        self.assertNotIn("empty-media-mail.svg')", source)


if __name__ == "__main__":
    unittest.main()
