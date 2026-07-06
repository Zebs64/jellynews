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
        self.assertIn("jellynews-backup-v1.0.3-secrets.json", response.headers["content-disposition"])

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


if __name__ == "__main__":
    unittest.main()
