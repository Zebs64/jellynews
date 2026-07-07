import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from fastapi import HTTPException

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _BOOTSTRAP_DATA_DIR.name

from app import database
from app.routers import api
from app.services import jellyfin


class DummyUpload:
    def __init__(self, payload: dict | list | str):
        if isinstance(payload, str):
            self.data = payload.encode("utf-8")
        else:
            self.data = json.dumps(payload).encode("utf-8")

    async def read(self) -> bytes:
        return self.data


class BackupImportExportTests(unittest.TestCase):
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

    def import_payload(self, payload: dict | list | str) -> dict:
        with patch.object(api.scheduler, "reschedule") as reschedule:
            result = asyncio.run(api.import_settings(cast(Any, DummyUpload(payload))))
        reschedule.assert_called_once()
        return result

    def test_export_backup_contains_settings_subscribers_logs_and_archives_only(self):
        database.create_admin("admin", "hash-not-exported")
        database.set_settings({"timezone": "Europe/Paris", "smtp_password": "smtp-secret"})
        database.add_subscriber("user@example.test")
        database.add_log("manual", "ok", 3, 1, "sent")
        database.add_archive("JellyNews", 3, 1, "<h1>Archive</h1>")

        response = api.export_settings()
        backup = json.loads(bytes(response.body).decode("utf-8"))
        dump = json.dumps(backup)

        self.assertEqual(backup["schema_version"], 2)
        self.assertEqual(backup["app_version"], jellyfin.JELLYFIN_CLIENT_VERSION)
        self.assertIn("settings", backup)
        self.assertEqual(backup["settings"]["smtp_password"], "smtp-secret")
        self.assertEqual(backup["subscribers"][0]["email"], "user@example.test")
        self.assertEqual(backup["send_logs"][0]["trigger"], "manual")
        self.assertEqual(backup["archives"][0]["html"], "<h1>Archive</h1>")
        self.assertNotIn("users", backup)
        self.assertNotIn("password_hash", dump)
        self.assertNotIn("secret.key", dump)
        self.assertIn("jellynews-backup-v1.1.1-secrets.json", response.headers["content-disposition"])

    def test_import_legacy_settings_only_export_still_works(self):
        result = self.import_payload({
            "timezone": "Europe/Paris",
            "schedule_hour": "7",
            "unknown_key": "ignored",
        })

        settings = database.get_settings()
        self.assertTrue(result["ok"])
        self.assertEqual(result["imported"]["settings"], 2)
        self.assertEqual(settings["schedule_hour"], "7")
        self.assertNotIn("unknown_key", settings)
        self.assertEqual(database.list_subscribers(), [])

    def test_import_full_backup_is_idempotent_for_subscribers_logs_and_archives(self):
        payload = {
            "schema_version": 2,
            "app_version": "1.0.2",
            "settings": {"timezone": "Europe/Paris", "schedule_hour": "9", "ignored": "nope"},
            "subscribers": [
                {"email": "USER@Example.Test", "created_at": "2026-07-06T10:00:00"},
                {"email": "user@example.test", "created_at": "2026-07-06T10:01:00"},
            ],
            "send_logs": [{
                "created_at": "2026-07-06T10:02:00",
                "trigger": "manual",
                "status": "ok",
                "items_count": 4,
                "recipients": 1,
                "detail": "sent",
            }],
            "archives": [{
                "created_at": "2026-07-06T10:03:00",
                "subject": "JellyNews",
                "items_count": 4,
                "recipients": 1,
                "html": "<p>Archive</p>",
            }],
        }

        first = self.import_payload(payload)
        second = self.import_payload(payload)

        self.assertEqual(first["imported"]["subscribers"], 1)
        self.assertEqual(first["imported"]["send_logs"], 1)
        self.assertEqual(first["imported"]["archives"], 1)
        self.assertEqual(second["skipped"]["subscribers"], 1)
        self.assertEqual(second["skipped"]["send_logs"], 1)
        self.assertEqual(second["skipped"]["archives"], 1)
        self.assertEqual(len(database.list_subscribers()), 1)
        self.assertEqual(len(database.list_logs()), 1)
        self.assertEqual(len(database.list_archives()), 1)
        self.assertEqual(database.get_settings()["schedule_hour"], "9")

    def test_import_export_preserves_smtp_diagnostic_fields_and_legacy_logs(self):
        database.add_log(
            "manual", "partial", 4, 1, "1/2 message(s) accepté(s) par le serveur SMTP.",
            {
                "error_class": "SMTPDataError",
                "smtp_code": 550,
                "smtp_error": "5.7.1 rejet policy",
                "smtp_category": "rejet_policy_spam",
                "smtp_hint": "Vérifier SPF/DKIM/DMARC.",
                "retryable": False,
            },
        )
        backup = json.loads(bytes(api.export_settings().body).decode("utf-8"))
        exported = backup["send_logs"][0]

        self.assertEqual(exported["error_class"], "SMTPDataError")
        self.assertEqual(exported["smtp_code"], 550)
        self.assertEqual(exported["retryable"], 0)

        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        database.DATA_DIR = Path(self.tmp.name)
        database.UPLOADS_DIR = Path(self.tmp.name) / "uploads"
        database.UPLOADS_DIR.mkdir(exist_ok=True)
        database.DB_PATH = Path(self.tmp.name) / "jellynews.db"
        database.init_db()

        imported = self.import_payload(backup)
        self.assertEqual(imported["imported"]["send_logs"], 1)
        stored = database.list_logs()[0]
        self.assertEqual(stored["error_class"], "SMTPDataError")
        self.assertEqual(stored["smtp_code"], 550)
        self.assertEqual(stored["smtp_category"], "rejet_policy_spam")
        self.assertEqual(stored["retryable"], 0)

        legacy = {
            "schema_version": 2,
            "settings": {},
            "subscribers": [],
            "send_logs": [{
                "created_at": "2026-07-06T10:02:00",
                "trigger": "manual",
                "status": "ok",
                "items_count": 4,
                "recipients": 1,
                "detail": "legacy",
            }],
            "archives": [],
        }
        legacy_result = self.import_payload(legacy)
        legacy_row = database.list_logs()[0]
        self.assertEqual(legacy_result["imported"]["send_logs"], 1)
        self.assertEqual(legacy_row["detail"], "legacy")
        self.assertEqual(legacy_row["error_class"], "")
        self.assertIsNone(legacy_row["smtp_code"])

    def test_imported_send_logs_are_sanitized_before_storage_and_export(self):
        payload = {
            "schema_version": 2,
            "settings": {},
            "subscribers": [],
            "send_logs": [{
                "created_at": "2026-07-06T10:02:00",
                "trigger": "manual",
                "status": "error",
                "items_count": 0,
                "recipients": 1,
                "detail": "SMTP refused victim@example.test\r\npassword=secret token=abcdef <script>alert(1)</script>",
                "error_class": "<script>SMTPDataError</script>",
                "smtp_code": 550,
                "smtp_error": "550 victim@example.test password=secret token=abcdef <img src=x onerror=alert(1)>",
                "smtp_category": "policy\r\n<script>",
                "smtp_hint": "secret=supersecret for victim@example.test",
                "retryable": False,
            }],
            "archives": [],
        }

        result = self.import_payload(payload)
        second = self.import_payload(payload)
        stored = database.list_logs()[0]
        exported = database.export_backup("test")["send_logs"][0]

        self.assertEqual(result["imported"]["send_logs"], 1)
        self.assertEqual(second["skipped"]["send_logs"], 1)
        self.assertEqual(len(database.list_logs()), 1)
        for row in (stored, exported):
            dump = json.dumps(row, ensure_ascii=False)
            self.assertNotIn("victim@example.test", dump)
            self.assertNotIn("password=secret", dump)
            self.assertNotIn("token=abcdef", dump)
            self.assertNotIn("secret=supersecret", dump)
            self.assertNotIn("\r", dump)
            self.assertNotIn("\n", dump)
            self.assertNotIn("<script>", dump)
            self.assertNotIn("<img", dump)
            self.assertNotIn("onerror", dump)
            self.assertIn("v***@example.test", dump)
            self.assertIn("[redacted]", dump)

    def test_imported_send_logs_redact_quoted_smtp_secrets_before_storage_and_export(self):
        payload = {
            "schema_version": 2,
            "settings": {},
            "subscribers": [],
            "send_logs": [{
                "created_at": "2026-07-06T10:02:00",
                "trigger": "manual",
                "status": "error",
                "items_count": 0,
                "recipients": 1,
                "detail": 'SMTP auth failed victim@example.test password="secret" token="abcdef" api_key="supersecret"',
                "error_class": "SMTPAuthenticationError",
                "smtp_code": 535,
                "smtp_error": '535 5.7.8 auth failed password="secret" token="abcdef" api_key="supersecret"',
                "smtp_category": "smtp_auth",
                "smtp_hint": "check password='secret' token='abcdef' for victim@example.test",
                "retryable": False,
            }],
            "archives": [],
        }

        result = self.import_payload(payload)
        stored = database.list_logs()[0]
        exported = database.export_backup("test")["send_logs"][0]

        self.assertEqual(result["imported"]["send_logs"], 1)
        for row in (stored, exported):
            dump = json.dumps(row, ensure_ascii=False)
            self.assertNotIn("victim@example.test", dump)
            self.assertNotIn('password="secret"', dump)
            self.assertNotIn('token="abcdef"', dump)
            self.assertNotIn('api_key="supersecret"', dump)
            self.assertNotIn("password='secret'", dump)
            self.assertNotIn("token='abcdef'", dump)
            self.assertNotIn("secret", dump)
            self.assertNotIn("abcdef", dump)
            self.assertNotIn("supersecret", dump)
            self.assertIn("v***@example.test", dump)
            self.assertIn("password=[redacted]", dump)
            self.assertIn("token=[redacted]", dump)
            self.assertIn("api_key=[redacted]", dump)

    def test_reimport_export_with_existing_local_archive_is_idempotent(self):
        database.add_archive("JellyNews", 4, 1, "<h1>Archive locale</h1>")
        backup = json.loads(bytes(api.export_settings().body).decode("utf-8"))

        result = self.import_payload(backup)
        stored = database.get_archive(1)

        self.assertEqual(result["skipped"]["archives"], 1)
        self.assertEqual(result["imported"]["archives"], 0)
        self.assertEqual(len(database.list_archives()), 1)
        self.assertEqual(stored["html"], "<h1>Archive locale</h1>")

    def test_imported_archive_html_is_not_served_as_executable_same_origin(self):
        payload = {
            "schema_version": 2,
            "app_version": "1.0.2",
            "settings": {},
            "subscribers": [],
            "send_logs": [],
            "archives": [{
                "created_at": "2026-07-06T10:03:00",
                "subject": "XSS",
                "items_count": 0,
                "recipients": 0,
                "html": "<!doctype html><script>alert(1)</script><h1>x</h1>",
            }],
        }

        result = self.import_payload(payload)
        response = api.view_archive(1)
        body = bytes(response.body).decode("utf-8")

        self.assertEqual(result["imported"]["archives"], 1)
        self.assertEqual(response.media_type, "text/html")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)

    def test_invalid_history_entry_rejects_import_without_partial_restore(self):
        payload = {
            "schema_version": 2,
            "settings": {"timezone": "Europe/Paris", "schedule_hour": "9"},
            "subscribers": [{"email": "user@example.test", "created_at": "2026-07-06T10:00:00"}],
            "send_logs": [{"created_at": "not-a-date", "trigger": "manual", "status": "ok"}],
            "archives": [],
        }

        with self.assertRaises(HTTPException) as ctx:
            self.import_payload(payload)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(database.get_settings()["schedule_hour"], database.DEFAULTS["schedule_hour"])
        self.assertEqual(database.list_subscribers(), [])
        self.assertEqual(database.list_logs(), [])

    def test_import_rejects_dangerous_public_urls_without_partial_restore(self):
        payload = {
            "schema_version": 2,
            "settings": {
                "timezone": "Europe/Paris",
                "jellyfin_url": "https://jellyfin.example.test",
                "jellyfin_external_url": "data:text/html,<b>x</b>",
            },
            "subscribers": [],
            "send_logs": [],
            "archives": [],
        }

        with patch.object(api.scheduler, "reschedule") as reschedule:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(api.import_settings(cast(Any, DummyUpload(payload))))

        self.assertEqual(ctx.exception.status_code, 400)
        reschedule.assert_not_called()
        self.assertEqual(database.get_settings()["timezone"], database.DEFAULTS["timezone"])
        self.assertEqual(database.get_settings()["jellyfin_external_url"], "")


if __name__ == "__main__":
    unittest.main()
