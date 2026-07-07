import smtplib
import ssl
import unittest

from app.services import mailer


class SmtpDiagnosticTests(unittest.TestCase):
    def test_specific_smtp_mappings(self):
        cases = [
            (smtplib.SMTPDataError(550, b"5.7.1 policy spam"), "rejet_policy_spam", False),
            (smtplib.SMTPDataError(554, b"5.7.1 refused content"), "contenu_policy_refuse", False),
            (smtplib.SMTPDataError(552, b"5.3.4 message too large"), "message_trop_gros", False),
            (smtplib.SMTPResponseException(451, b"4.7.0 greylisting"), "rate_limit_greylisting", True),
            (smtplib.SMTPResponseException(421, b"temporarily unavailable"), "service_temporaire_throttle", True),
        ]
        for exc, category, retryable in cases:
            with self.subTest(category=category):
                diag = mailer.smtp_diagnostic(exc)
                self.assertEqual(diag["smtp_category"], category)
                self.assertIs(diag["retryable"], retryable)
                self.assertLessEqual(len(diag["smtp_hint"]), 500)

    def test_general_4xx_and_5xx_rules(self):
        temporary = mailer.smtp_diagnostic(smtplib.SMTPResponseException(450, b"mailbox busy"))
        permanent = mailer.smtp_diagnostic(smtplib.SMTPResponseException(553, b"bad mailbox"))

        self.assertEqual(temporary["smtp_category"], "smtp_temporaire")
        self.assertIs(temporary["retryable"], True)
        self.assertEqual(permanent["smtp_category"], "smtp_permanent")
        self.assertIs(permanent["retryable"], False)

    def test_smtp_exception_types_are_covered(self):
        recipients_refused = smtplib.SMTPRecipientsRefused({
            "victim@example.test": (451, b"4.7.0 greylisted victim@example.test token=abcdef")
        })
        cases = [
            smtplib.SMTPDataError(550, b"5.7.1 spam"),
            smtplib.SMTPResponseException(450, b"temporary"),
            recipients_refused,
            smtplib.SMTPSenderRefused(552, b"5.3.4 too big", "sender@example.test"),
            smtplib.SMTPAuthenticationError(535, b"5.7.8 auth failed"),
            smtplib.SMTPConnectError(421, b"connect refused"),
            smtplib.SMTPServerDisconnected("bye"),
            TimeoutError("timeout"),
            ConnectionError("connection lost"),
            OSError("network unreachable"),
            ssl.SSLError("tls failed"),
        ]
        for exc in cases:
            with self.subTest(error_class=type(exc).__name__):
                diag = mailer.smtp_diagnostic(exc)
                self.assertEqual(diag["error_class"], type(exc).__name__)
                self.assertIn("smtp_category", diag)
                self.assertIn("smtp_hint", diag)
                self.assertIn("retryable", diag)

        refused = mailer.smtp_diagnostic(recipients_refused)
        self.assertEqual(refused["smtp_code"], 451)
        self.assertNotIn("victim@example.test", refused["smtp_error"])
        self.assertIn("v***@example.test", refused["smtp_error"])
        self.assertNotIn("abcdef", refused["smtp_error"])

    def test_auth_and_network_categories_without_usable_smtp_code(self):
        auth = mailer.smtp_diagnostic(smtplib.SMTPAuthenticationError(535, b"bad password=secret"))
        disconnected = mailer.smtp_diagnostic(smtplib.SMTPServerDisconnected("bye"))
        timeout = mailer.smtp_diagnostic(TimeoutError("timeout"))

        self.assertEqual(auth["smtp_category"], "smtp_auth")
        self.assertIs(auth["retryable"], False)
        self.assertEqual(disconnected["smtp_category"], "smtp_disconnected")
        self.assertIs(disconnected["retryable"], True)
        self.assertEqual(timeout["smtp_category"], "network_error")
        self.assertIs(timeout["retryable"], True)

    def test_smtp_error_is_redacted_normalized_and_truncated(self):
        hostile = (
            b"5.7.1 rejected <script>alert(1)</script>\r\n"
            b"victim@example.test password=secret token=abcdef " + b"x" * 800
        )
        diag = mailer.smtp_diagnostic(smtplib.SMTPDataError(550, hostile))

        self.assertLessEqual(len(diag["smtp_error"]), 500)
        self.assertNotIn("\r", diag["smtp_error"])
        self.assertNotIn("\n", diag["smtp_error"])
        self.assertNotIn("victim@example.test", diag["smtp_error"])
        self.assertNotIn("secret", diag["smtp_error"])
        self.assertNotIn("abcdef", diag["smtp_error"])
        self.assertIn("v***@example.test", diag["smtp_error"])


if __name__ == "__main__":
    unittest.main()
