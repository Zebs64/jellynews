import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _BOOTSTRAP_DATA_DIR.name

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.routers import api


class DashboardSummaryTests(unittest.TestCase):
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

    def test_dashboard_summary_returns_admin_metrics(self):
        database.set_settings({"lookback_days": "14"})
        database.add_subscriber("user@example.test")
        database.add_log("manual", "ok", 3, 1, "sent")

        with (
            patch.object(api.scheduler, "next_run_iso", return_value="2026-07-10T18:00+02:00"),
            patch.object(api.jellyfin, "fetch_recent_items", return_value=[{"name": "A"}, {"name": "B"}]),
        ):
            summary = api.dashboard_summary()

        self.assertEqual(summary["next_run"], "2026-07-10T18:00+02:00")
        self.assertEqual(summary["lookback_days"], 14)
        self.assertEqual(summary["recent_items_count"], 2)
        self.assertEqual(summary["recent_items_error"], "")
        self.assertEqual(summary["subscribers_count"], 1)
        self.assertEqual(summary["last_send"]["status"], "ok")
        self.assertEqual(summary["last_send"]["items_count"], 3)

    def test_dashboard_summary_keeps_explicit_state_when_jellyfin_unavailable(self):
        with patch.object(api.jellyfin, "fetch_recent_items", side_effect=RuntimeError("boom")):
            summary = api.dashboard_summary()

        self.assertIsNone(summary["recent_items_count"])
        self.assertIn("Nouveautés indisponibles", summary["recent_items_error"])

    def test_dashboard_summary_endpoint_requires_admin_session(self):
        response = TestClient(app).get("/api/dashboard-summary")

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
