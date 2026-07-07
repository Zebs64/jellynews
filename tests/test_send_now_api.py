import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _BOOTSTRAP_DATA_DIR.name

from app.routers import api


class SendNowApiTests(unittest.TestCase):
    DANGEROUS_URLS = [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//evil.test/path",
        "jellyfin.example.test",
    ]

    def test_send_now_queues_background_task_without_running_inline(self):
        background_tasks = BackgroundTasks()
        with (
            patch.object(api.newsletter, "claim_campaign", return_value=True) as claim,
            patch.object(api.newsletter, "run_claimed") as run_claimed,
        ):
            result = api.send_now(background_tasks)

        self.assertEqual(result, {"status": "queued", "queued": True})
        claim.assert_called_once_with()
        run_claimed.assert_not_called()
        self.assertEqual(len(background_tasks.tasks), 1)
        task = background_tasks.tasks[0]
        self.assertIs(task.func, run_claimed)
        self.assertEqual(task.kwargs, {"trigger": "manual"})

    def test_send_now_refuses_concurrent_campaign(self):
        with patch.object(api.newsletter, "claim_campaign", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                api.send_now(BackgroundTasks())

        self.assertEqual(ctx.exception.status_code, 409)

    def test_smtp_throttle_settings_validation_rejects_out_of_bounds_values(self):
        with self.assertRaises(HTTPException) as ctx:
            api._validate_settings({"smtp_batch_size": "0"})
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(HTTPException) as ctx:
            api._validate_settings({"smtp_batch_pause_seconds": "3601"})
        self.assertEqual(ctx.exception.status_code, 400)

        api._validate_settings({"smtp_batch_size": "1", "smtp_batch_pause_seconds": "0"})

    def test_url_settings_accept_only_http_or_https_with_host(self):
        for key in ("jellyfin_url", "jellyfin_external_url", "app_public_url"):
            for value in self.DANGEROUS_URLS:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(HTTPException) as ctx:
                        api._validate_settings({key: value})
                    self.assertEqual(ctx.exception.status_code, 400)

        api._validate_settings({
            "jellyfin_url": "http://jellyfin:8096",
            "jellyfin_external_url": "https://jellyfin.example.test",
            "app_public_url": "https://jellynews.example.test",
        })
        api._validate_settings({"jellyfin_external_url": "", "app_public_url": ""})

        with self.assertRaises(HTTPException):
            api._validate_settings({"jellyfin_url": ""})


if __name__ == "__main__":
    unittest.main()
