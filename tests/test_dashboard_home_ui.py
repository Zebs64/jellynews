from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "app" / "templates" / "web" / "dashboard.html"
STYLE = ROOT / "app" / "static" / "style.css"
APP_JS = ROOT / "app" / "static" / "app.js"


class DashboardHomeUiTests(unittest.TestCase):
    def test_home_panel_is_default_and_logo_targets_home(self):
        source = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn('class="brand-lockup brand-home"', source)
        self.assertIn('data-panel="panel-home"', source)
        self.assertIn('<button class="nav-btn active" data-panel="panel-home">Accueil</button>', source)
        self.assertIn('<section id="panel-home" class="panel home-panel">', source)
        self.assertIn('<section id="panel-jellyfin" class="panel hidden">', source)
        self.assertIn('id="home-next-run-value"', source)
        self.assertIn('id="home-recent-count-value"', source)
        self.assertIn('id="home-subscribers-value"', source)

    def test_sidebar_active_indicator_has_no_vertical_pseudo_element(self):
        source = STYLE.read_text(encoding="utf-8")

        self.assertNotIn('.nav-btn.active::before', source)
        self.assertIn('button:focus-visible', source)
        self.assertIn('--jn-focus', source)

    def test_logo_and_nav_share_panel_activation(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('function activatePanel(panelId)', source)
        self.assertIn("$$('[data-panel]').forEach", source)
        self.assertIn("api('/api/dashboard-summary')", source)


if __name__ == "__main__":
    unittest.main()
