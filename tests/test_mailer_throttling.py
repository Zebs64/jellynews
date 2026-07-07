import smtplib
import unittest
from unittest.mock import patch

from app.services import mailer


BASE_SETTINGS = {
    "smtp_host": "smtp.example.test",
    "smtp_port": "587",
    "smtp_security": "none",
    "smtp_sender": "newsletter@example.test",
    "smtp_batch_size": "2",
    "smtp_batch_pause_seconds": "3",
}


class FakeServer:
    def __init__(self, failing: set[str] | None = None):
        self.failing = failing or set()
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def send_message(self, msg):
        recipient = msg["To"]
        if recipient in self.failing:
            raise smtplib.SMTPException("refused")
        self.messages.append(msg)


class MailerTests(unittest.TestCase):
    def test_send_html_uses_one_message_per_recipient_without_cc_bcc_and_keeps_unsubscribe(self):
        fake = FakeServer()
        recipients = ["one@example.test", "two@example.test", "three@example.test"]
        unsub_urls = {email: f"https://jellynews.example/unsubscribe/{index}" for index, email in enumerate(recipients)}

        with patch.object(mailer, "_connect", return_value=fake), patch.object(mailer.time, "sleep") as sleep:
            result = mailer.send_html(
                BASE_SETTINGS,
                recipients,
                "Sujet",
                "<p>Bonjour %%UNSUB_URL%%</p>",
                unsub_urls=unsub_urls,
            )

        self.assertEqual(result.total, 3)
        self.assertEqual(result.sent, 3)
        self.assertEqual(result.failures, [])
        self.assertEqual([msg["To"] for msg in fake.messages], recipients)
        for msg in fake.messages:
            self.assertNotIn("Cc", msg)
            self.assertNotIn("Bcc", msg)
            self.assertEqual(msg["List-Unsubscribe"], f"<{unsub_urls[msg['To']] }>")
            self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        sleep.assert_called_once_with(3)

    def test_send_html_isolates_partial_smtp_failure(self):
        fake = FakeServer(failing={"two@example.test"})
        recipients = ["one@example.test", "two@example.test", "three@example.test"]

        with patch.object(mailer, "_connect", return_value=fake), patch.object(mailer.time, "sleep"):
            result = mailer.send_html(BASE_SETTINGS, recipients, "Sujet", "<p>Bonjour</p>")

        self.assertEqual(result.total, 3)
        self.assertEqual(result.sent, 2)
        self.assertEqual(result.failed, 1)
        self.assertIn("t***@example.test: SMTPException", result.failures)
        self.assertEqual(result.failure_details[0]["recipient"], "t***@example.test")
        self.assertEqual(result.failure_details[0]["error_class"], "SMTPException")
        self.assertEqual(result.failure_details[0]["smtp_category"], "smtp_unknown")
        self.assertEqual([msg["To"] for msg in fake.messages], ["one@example.test", "three@example.test"])

    def test_send_html_masks_recipient_in_smtp_failure_logs(self):
        fake = FakeServer(failing={"victim@example.test"})

        with (
            patch.object(mailer, "_connect", return_value=fake),
            patch.object(mailer.time, "sleep"),
            self.assertLogs("jellynews.mailer", level="ERROR") as captured,
        ):
            result = mailer.send_html(
                BASE_SETTINGS,
                ["victim@example.test"],
                "Sujet",
                "<p>Bonjour</p>",
            )

        log_output = "\n".join(captured.output)
        self.assertNotIn("victim@example.test", log_output)
        self.assertIn("v***@example.test", log_output)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.sent, 0)
        self.assertEqual(result.failures, ["v***@example.test: SMTPException"])

    def test_throttle_settings_validate_bounds(self):
        self.assertEqual(mailer.throttle_settings(BASE_SETTINGS), (2, 3))
        with self.assertRaises(ValueError):
            mailer.throttle_settings({**BASE_SETTINGS, "smtp_batch_size": "0"})
        with self.assertRaises(ValueError):
            mailer.throttle_settings({**BASE_SETTINGS, "smtp_batch_pause_seconds": "3601"})


if __name__ == "__main__":
    unittest.main()
