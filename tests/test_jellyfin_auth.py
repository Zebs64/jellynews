import unittest
from unittest.mock import Mock, patch

from app.services import jellyfin


SETTINGS = {
    "jellyfin_url": "http://jellyfin.local:8096",
    "jellyfin_api_key": "test-api-key",
}


def _status_error(status: int) -> jellyfin.httpx.HTTPStatusError:
    request = jellyfin.httpx.Request("GET", "http://jellyfin.local:8096/Items/abc/Images/Primary")
    response = jellyfin.httpx.Response(status, request=request)
    return jellyfin.httpx.HTTPStatusError("error", request=request, response=response)


POSTER_ITEM = {"poster_path": "/Items/abc/Images/Primary", "name": "Film"}


class JellyfinPosterErrorTests(unittest.TestCase):
    def _download_with(self, side_effect):
        response = Mock()
        response.raise_for_status.side_effect = side_effect
        with patch.object(jellyfin.httpx, "get", return_value=response), \
             self.assertLogs("jellynews.jellyfin", level="WARNING") as captured:
            result = jellyfin.download_poster(SETTINGS, POSTER_ITEM)
        self.assertIsNone(result)
        return captured

    def test_auth_errors_are_logged_as_errors_with_hint(self):
        for status in (401, 403):
            with self.subTest(status=status):
                captured = self._download_with(_status_error(status))
                self.assertEqual(captured.records[0].levelname, "ERROR")
                self.assertIn(f"HTTP {status}", captured.output[0])
                self.assertIn("clé API", captured.output[0])
                self.assertNotIn("test-api-key", "\n".join(captured.output))

    def test_other_http_errors_are_warnings_with_status(self):
        captured = self._download_with(_status_error(404))
        self.assertEqual(captured.records[0].levelname, "WARNING")
        self.assertIn("HTTP 404", captured.output[0])

    def test_network_errors_are_warnings(self):
        captured = self._download_with(jellyfin.httpx.ConnectError("down"))
        self.assertEqual(captured.records[0].levelname, "WARNING")
        self.assertIn("ConnectError", captured.output[0])


class JellyfinAuthHeaderTests(unittest.TestCase):
    def test_get_uses_mediabrowser_authorization_header(self):
        response = Mock()
        response.json.return_value = {"Items": []}

        with patch.object(jellyfin.httpx, "get", return_value=response) as http_get:
            jellyfin._get(SETTINGS, "/Library/MediaFolders")

        headers = http_get.call_args.kwargs["headers"]
        self.assertNotIn("X-Emby-Token", headers)
        self.assertNotIn("X-MediaBrowser-Token", headers)
        self.assertEqual(set(headers), {"Authorization"})
        self.assertEqual(
            headers["Authorization"],
            'MediaBrowser Client="JellyNews", Device="JellyNews", '
            'DeviceId="jellynews", Version="1.1.3", Token="test-api-key"',
        )
        response.raise_for_status.assert_called_once()

    def test_download_poster_uses_same_authorization_header_without_query_token(self):
        response = Mock()
        response.content = b"poster"
        response.headers = {"content-type": "image/jpeg"}
        item = {"poster_path": "/Items/abc/Images/Primary", "name": "Film"}

        with patch.object(jellyfin.httpx, "get", return_value=response) as http_get:
            result = jellyfin.download_poster(SETTINGS, item)

        self.assertEqual(result, (b"poster", "jpeg"))
        url = http_get.call_args.args[0]
        headers = http_get.call_args.kwargs["headers"]
        self.assertNotIn("api_key=", url)
        self.assertEqual(
            headers["Authorization"],
            'MediaBrowser Client="JellyNews", Device="JellyNews", '
            'DeviceId="jellynews", Version="1.1.3", Token="test-api-key"',
        )
        response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
