import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _BOOTSTRAP_DATA_DIR.name

from fastapi import HTTPException

from app import database
from app.routers import api
from app.services import mailer, newsletter, newsletter_templates


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "app" / "templates" / "web" / "dashboard.html"
APP_JS = ROOT / "app" / "static" / "app.js"


class NewsletterTemplateRegistryTests(unittest.TestCase):
    def test_default_template_is_classic_and_current_template_file(self):
        resolved = newsletter_templates.resolve(database.DEFAULTS)

        self.assertEqual(resolved["template"].id, "classic")
        self.assertEqual(resolved["template"].template_file, "newsletter.html")
        self.assertEqual([block["id"] for block in resolved["blocks"]], newsletter_templates.DEFAULT_BLOCK_ORDER)

    def test_unknown_template_is_rejected(self):
        with self.assertRaises(ValueError):
            newsletter_templates.normalize_settings({"newsletter_template_id": "../../evil.html"})

    def test_blocks_are_known_unique_and_mandatory(self):
        with self.assertRaisesRegex(ValueError, "inconnu"):
            newsletter_templates.normalize_blocks(["preheader", "header", "raw_html", "media_sections", "footer"])
        with self.assertRaisesRegex(ValueError, "dupliqué"):
            newsletter_templates.normalize_blocks(["preheader", "header", "intro", "intro", "media_sections", "footer"])
        with self.assertRaisesRegex(ValueError, "obligatoire désactivé"):
            newsletter_templates.normalize_blocks([
                {"id": "preheader"},
                {"id": "header"},
                {"id": "media_sections", "enabled": False},
                {"id": "footer"},
            ])

    def test_explicit_order_keeps_preheader_first_and_footer_last(self):
        blocks = newsletter_templates.normalize_blocks([
            "footer",
            "media_sections",
            {"id": "intro", "enabled": False},
            "header",
            "preheader",
        ])

        self.assertEqual(blocks[0]["id"], "preheader")
        self.assertEqual(blocks[-1]["id"], "footer")
        self.assertFalse(next(block for block in blocks if block["id"] == "intro")["enabled"])


class NewsletterRenderingTests(unittest.TestCase):
    DANGEROUS_HREFS = ["javascript:alert(2)", "data:text/html,<b>x</b>"]

    def render_template(self, template_id: str, blocks: list[dict[str, Any]] | None = None) -> str:
        settings = dict(database.DEFAULTS)
        settings["newsletter_template_id"] = template_id
        if blocks is not None:
            settings["newsletter_blocks_json"] = newsletter_templates.serialize_blocks(blocks)
        context, _ = newsletter.sample_context(settings)
        return newsletter.render_html(settings, context, for_email=True, with_unsub=True)

    def test_all_registered_templates_render_email_safe_html(self):
        for template_id in newsletter_templates.TEMPLATES:
            with self.subTest(template_id=template_id):
                html = self.render_template(template_id)
                self.assertIn("<table", html)
                self.assertIn("role=\"presentation\"", html)
                self.assertIn(mailer.UNSUB_PLACEHOLDER, html)
                self.assertNotIn("<script", html.lower())
                self.assertNotIn("<link", html.lower())
                self.assertNotIn("display:flex", html.lower())

    def test_intro_block_can_be_disabled_without_free_html(self):
        blocks = newsletter_templates.default_blocks()
        for block in blocks:
            if block["id"] == "intro":
                block["enabled"] = False
        html = self.render_template("editorial", blocks)

        self.assertNotIn("Prévisualisation JellyNews", html)
        self.assertIn("Le Courant des Abysses", html)

    def test_registered_templates_neutralize_dangerous_item_hrefs(self):
        for template_id in newsletter_templates.TEMPLATES:
            for href in self.DANGEROUS_HREFS:
                with self.subTest(template_id=template_id, href=href):
                    settings = dict(database.DEFAULTS)
                    settings["newsletter_template_id"] = template_id
                    settings["jellyfin_url"] = href
                    context, _ = newsletter.sample_context(settings)
                    context["sections"][0]["entries"][0]["url"] = href

                    html = newsletter.render_html(settings, context, for_email=True, with_unsub=True).lower()

                    self.assertNotIn('href="javascript:', html)
                    self.assertNotIn('href="data:', html)


class NewsletterApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = database.DATA_DIR
        self.old_db_path = database.DB_PATH
        self.old_uploads_dir = database.UPLOADS_DIR
        database.DATA_DIR = Path(self.tmp.name)
        database.UPLOADS_DIR = Path(self.tmp.name) / "uploads"
        database.UPLOADS_DIR.mkdir(exist_ok=True)
        database.DB_PATH = Path(self.tmp.name) / "jellynews.db"
        database.init_db()

    def tearDown(self):
        database.DATA_DIR = self.old_data_dir
        database.DB_PATH = self.old_db_path
        database.UPLOADS_DIR = self.old_uploads_dir
        self.tmp.cleanup()

    def test_settings_export_contains_newsletter_template_configuration(self):
        blocks = newsletter_templates.default_blocks()
        blocks[2]["enabled"] = False
        api.save_settings({
            "newsletter_template_id": "compact",
            "newsletter_blocks_json": newsletter_templates.serialize_blocks(blocks),
        })

        backup = json.loads(bytes(api.export_settings().body).decode("utf-8"))

        self.assertEqual(backup["settings"]["newsletter_template_id"], "compact")
        self.assertIn("newsletter_blocks_json", backup["settings"])
        self.assertIn("jellynews-backup-v1.1.0-secrets.json", api.export_settings().headers["content-disposition"])

    def test_invalid_settings_reject_without_persistence(self):
        with self.assertRaises(HTTPException) as ctx:
            api.save_settings({"newsletter_template_id": "evil"})

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(database.get_settings()["newsletter_template_id"], "classic")

    def test_save_settings_rejects_dangerous_public_urls_without_persistence(self):
        dangerous = [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
            "//evil.test/path",
        ]

        for key in ("jellyfin_url", "jellyfin_external_url", "app_public_url"):
            for value in dangerous:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(HTTPException) as ctx:
                        api.save_settings({key: value})
                    self.assertEqual(ctx.exception.status_code, 400)
                    self.assertNotEqual(database.get_settings()[key], value)

    def test_invalid_imported_newsletter_config_rejects_without_partial_restore(self):
        payload = {
            "schema_version": 2,
            "settings": {"timezone": "Europe/Paris", "newsletter_template_id": "evil"},
            "subscribers": [],
            "send_logs": [],
            "archives": [],
        }

        with self.assertRaises(HTTPException) as ctx:
            api._prepare_backup_import(payload)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(database.get_settings()["timezone"], database.DEFAULTS["timezone"])

    def test_preview_falls_back_to_sample_render(self):
        with patch.object(api.newsletter, "build_context", side_effect=RuntimeError("offline")):
            response = api.preview()

        body = bytes(response.body).decode("utf-8")
        self.assertIn("Le Courant des Abysses", body)
        self.assertIn("Prévisualisation", body)

    def test_preview_fallback_never_renders_dangerous_hrefs_from_stored_settings(self):
        database.set_settings({"jellyfin_url": "javascript:alert(2)"})

        with patch.object(api.newsletter, "build_context", side_effect=RuntimeError("offline")):
            response = api.preview()

        body = bytes(response.body).decode("utf-8").lower()
        self.assertNotIn('href="javascript:', body)
        self.assertNotIn('href="data:', body)

    def test_test_email_sends_rendered_newsletter_to_single_validated_address(self):
        captured = {}

        def fake_send(settings, recipients, subject, html, logo_path=None, inline_images=None, unsub_urls=None):
            captured["recipients"] = recipients
            captured["subject"] = subject
            captured["html"] = html
            return mailer.SendResult(total=1, sent=1, failures=[])

        with patch.object(api.newsletter, "build_context", side_effect=RuntimeError("offline")), \
             patch.object(api.mailer, "send_html", side_effect=fake_send) as send_html:
            result = api.test_email({"to": "Admin@Example.Test"})

        self.assertTrue(result["ok"])
        self.assertEqual(captured["recipients"], ["Admin@Example.Test"])
        self.assertEqual(captured["subject"], "JellyNews — Newsletter de test")
        self.assertIn("Le Courant des Abysses", captured["html"])
        send_html.assert_called_once()


class NewsletterEditorUiTests(unittest.TestCase):
    def test_dashboard_contains_controlled_editor_fields(self):
        source = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn('name="newsletter_template_id"', source)
        self.assertIn('name="newsletter_blocks_json"', source)
        self.assertIn('id="newsletter-template-cards"', source)
        self.assertIn('id="newsletter-block-list"', source)
        self.assertNotIn("textarea name=\"newsletter_html\"", source)

    def test_template_config_is_rendered_with_dom_nodes_not_inner_html(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("document.createElement('button')", source)
        self.assertIn("document.createElement('option')", source)
        self.assertIn("textContent = template.name", source)
        self.assertNotIn("newsletter-template-cards').innerHTML", source)
        self.assertNotIn("newsletter-block-list').innerHTML", source)


if __name__ == "__main__":
    unittest.main()
