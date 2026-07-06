from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminUiSecurityTests(unittest.TestCase):
    def test_jellyfin_libraries_rendering_does_not_inject_server_ids_as_html_attributes(self):
        source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        match = re.search(
            r"/\* -------------------------------------------------------- bibliothèques -- \*/(?P<block>.*?)"
            r"/\* ------------------------------------------------------------- test LLM -- \*/",
            source,
            re.S,
        )
        assert match is not None
        block = match.group("block")

        malicious_id = 'x" autofocus onfocus="window.__xss=1" data-x="'
        old_vulnerable_markup = f'<input type="checkbox" value="{malicious_id}">'

        self.assertNotIn("innerHTML = libs.map", block)
        self.assertNotIn("value=\"${", block)
        self.assertIn("document.createElement('input')", block)
        self.assertIn("input.value = id", block)
        self.assertIn("document.createTextNode", block)
        self.assertIn('onfocus="window.__xss=1"', old_vulnerable_markup)


if __name__ == "__main__":
    unittest.main()