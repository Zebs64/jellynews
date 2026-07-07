import unittest
from unittest.mock import Mock, patch

from app.services import jellyfin


SETTINGS = {
    "jellyfin_url": "http://jellyfin.local:8096",
    "jellyfin_api_key": "test-api-key",
}


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
            'DeviceId="jellynews", Version="1.0.4", Token="test-api-key"',
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
            'DeviceId="jellynews", Version="1.0.4", Token="test-api-key"',
        )
        response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
