import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _BOOTSTRAP_DATA_DIR.name

from app.routers import api


class SendNowApiTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
