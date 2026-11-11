import os
import re
import tempfile
import unittest
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime
from unittest.mock import patch

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_DIR", _BOOTSTRAP_DATA_DIR.name)

from fastapi import HTTPException

from app import database
from app.routers import api
from app.services import mailer, newsletter


BASE_SETTINGS = {
    "smtp_host": "smtp.example.test",
    "smtp_port": "587",
    "smtp_security": "none",
    "smtp_sender": "newsletter@example.test",
    "smtp_batch_size": "25",
    "smtp_batch_pause_seconds": "0",
}

MESSAGE_ID_RE = re.compile(r"^<[^<>@\s]+@example\.test>$")


class FakeServer:
    def __init__(self):
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def send_message(self, msg):
        # smtplib aplatit réellement le message : on fait de même pour tester
        # le rendu tel qu'il partira sur le réseau.
        self.messages.append(message_from_bytes(msg.as_bytes(), policy=policy.default))


def _send(settings, recipients, html="<p>Bonjour %%UNSUB_URL%%</p>", **kwargs):
    fake = FakeServer()
    with patch.object(mailer, "_connect", return_value=fake), patch.object(mailer.time, "sleep"):
        result = mailer.send_html(settings, recipients, "Sujet", html, **kwargs)
    return result, fake.messages


def _sample_text(settings: dict, *, with_unsub: bool) -> str:
    context, _ = newsletter.sample_context(settings, "Intro « drôle » & chaleureuse")
    context["title"] = "Films & Séries"
    return newsletter.render_text(settings, context, with_unsub=with_unsub)


class MessageHeadersTests(unittest.TestCase):
    def test_date_header_is_present_and_rfc5322(self):
        _, messages = _send(BASE_SETTINGS, ["one@example.test"])

        date = messages[0]["Date"]
        self.assertIsNotNone(date)
        parsed = parsedate_to_datetime(str(date))
        self.assertIsNotNone(parsed.tzinfo)

    def test_message_id_is_unique_and_uses_sender_domain(self):
        _, messages = _send(BASE_SETTINGS, ["one@example.test", "two@example.test"])

        ids = [str(msg["Message-ID"]) for msg in messages]
        for message_id in ids:
            self.assertRegex(message_id, MESSAGE_ID_RE)
        self.assertEqual(len(set(ids)), 2)

    def test_message_id_without_sender_domain_still_valid(self):
        settings = {**BASE_SETTINGS, "smtp_sender": "", "smtp_user": "apikey"}
        _, messages = _send(settings, ["one@example.test"])

        self.assertRegex(str(messages[0]["Message-ID"]), r"^<[^<>\s]+@[^<>\s]+>$")

    def test_from_without_name_stays_bare_address(self):
        _, messages = _send(BASE_SETTINGS, ["one@example.test"])

        self.assertEqual(str(messages[0]["From"]), "newsletter@example.test")

    def test_from_uses_display_name_with_accents(self):
        settings = {**BASE_SETTINGS, "smtp_sender_name": "Médiathèque Léa"}
        _, messages = _send(settings, ["one@example.test"])

        address = messages[0]["From"].addresses[0]
        self.assertEqual(address.display_name, "Médiathèque Léa")
        self.assertEqual(address.addr_spec, "newsletter@example.test")

    def test_from_keeps_legacy_name_in_sender_and_strips_line_breaks(self):
        legacy = {**BASE_SETTINGS, "smtp_sender": "Ancien Nom <newsletter@example.test>"}
        _, messages = _send(legacy, ["one@example.test"])
        address = messages[0]["From"].addresses[0]
        self.assertEqual(address.display_name, "Ancien Nom")
        self.assertEqual(address.addr_spec, "newsletter@example.test")

        injected = {**BASE_SETTINGS, "smtp_sender_name": "Nom\r\nBcc: victim@example.test"}
        result, messages = _send(injected, ["one@example.test"])
        self.assertEqual(result.sent, 1)
        self.assertNotIn("Bcc", messages[0])

    def test_unsubscribe_headers_are_kept(self):
        url = "https://jellynews.example/unsubscribe/abc"
        _, messages = _send(BASE_SETTINGS, ["one@example.test"], unsub_urls={"one@example.test": url})

        self.assertEqual(str(messages[0]["List-Unsubscribe"]), f"<{url}>")
        self.assertEqual(str(messages[0]["List-Unsubscribe-Post"]), "List-Unsubscribe=One-Click")


class PlainTextPartTests(unittest.TestCase):
    def setUp(self):
        self.settings = {**database.DEFAULTS, **BASE_SETTINGS, "jellyfin_url": "https://jellyfin.example.test"}

    def test_text_part_mirrors_newsletter_content(self):
        url = "https://jellynews.example/unsubscribe/abc"
        text = _sample_text(self.settings, with_unsub=True)
        _, messages = _send(
            self.settings, ["one@example.test"], text=text, unsub_urls={"one@example.test": url},
        )

        plain = messages[0].get_body(preferencelist=("plain",))
        self.assertNotEqual(plain["Content-Transfer-Encoding"], "base64")
        content = plain.get_content()
        self.assertIn("Films & Séries", content)
        self.assertNotIn("&amp;", content)
        self.assertIn("Intro « drôle » & chaleureuse", content)
        self.assertIn("Prévisualisation du", content)
        for title in ("Le Courant des Abysses", "Station 404", "Midnight Packets"):
            self.assertIn(title, content)
        self.assertIn("https://jellyfin.example.test", content)
        self.assertIn(f"Se désinscrire en un clic : {url}", content)
        self.assertNotIn(mailer.UNSUB_PLACEHOLDER, content)
        self.assertGreater(len(content.split()), 50)

    def test_text_part_respects_disabled_intro_and_unsafe_links(self):
        settings = {
            **self.settings,
            "newsletter_blocks_json": '[{"id":"preheader","enabled":true},{"id":"header","enabled":true},'
            '{"id":"intro","enabled":false},{"id":"media_sections","enabled":true},{"id":"footer","enabled":true}]',
        }
        context, _ = newsletter.sample_context(settings, "Intro masquée")
        context["sections"][0]["entries"][0]["url"] = "javascript:alert(1)"

        text = newsletter.render_text(settings, context, with_unsub=False)

        self.assertNotIn("Intro masquée", text)
        self.assertNotIn("javascript:", text)
        self.assertIn("répondez simplement à cet e-mail", text)

    def test_fallback_text_when_caller_provides_none(self):
        _, messages = _send(BASE_SETTINGS, ["one@example.test"])

        content = messages[0].get_body(preferencelist=("plain",)).get_content()
        self.assertIn("Jellyfin", content)


class SenderNameSettingTests(unittest.TestCase):
    def test_sender_name_is_known_setting(self):
        self.assertIn("smtp_sender_name", database.DEFAULTS)

    def test_sender_name_rejects_line_breaks_and_is_trimmed(self):
        with self.assertRaises(HTTPException):
            api._validate_settings({"smtp_sender_name": "Nom\nBcc: x@example.test"})
        with self.assertRaises(HTTPException):
            api._validate_settings({"smtp_sender_name": "x" * (api.SENDER_NAME_MAX + 1)})
        payload = {"smtp_sender_name": "  JellyNews  "}
        api._validate_settings(payload)
        self.assertEqual(payload["smtp_sender_name"], "JellyNews")


if __name__ == "__main__":
    unittest.main()
