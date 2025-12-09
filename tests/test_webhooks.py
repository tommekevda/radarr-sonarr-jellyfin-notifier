import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import create_app


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    @patch("webhooks.JellyfinClient")
    def test_radarr_refresh_merges_ids_and_collection_types(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [{"Name": "Movies", "ItemId": "movie123", "CollectionType": "movies"}],
            ),
            refresh=lambda library_ids=None: (True, f"refresh:{library_ids}", 200),
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.post(
            "/radarr-webhook",
            json={"eventType": "Download"},
            headers={
                "X-Jellyfin-Url": "http://jf",
                "X-Jellyfin-Api-Key": "key",
                "X-Jellyfin-Library-Ids": "libA,libB",
                "X-Jellyfin-Collection-Types": "movies",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("refresh:['libA', 'libB', 'movie123']", resp.get_data(as_text=True))

    @patch("webhooks.JellyfinClient")
    def test_radarr_unknown_collection_type_returns_400(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [{"Name": "Movies", "ItemId": "movie123", "CollectionType": "movies"}],
            )
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.post(
            "/radarr-webhook",
            json={"eventType": "Download"},
            headers={
                "X-Jellyfin-Url": "http://jf",
                "X-Jellyfin-Api-Key": "key",
                "X-Jellyfin-Collection-Types": "unknown",
            },
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown collection types", resp.get_data(as_text=True))

    @patch("webhooks.JellyfinClient")
    def test_libraries_endpoint_requires_credentials(self, mock_client_cls):
        resp = self.client.get("/libraries")
        self.assertEqual(resp.status_code, 400)
        mock_client_cls.assert_not_called()

    @patch("webhooks.JellyfinClient")
    def test_libraries_endpoint_returns_payload(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [
                    {
                        "Name": "Movies",
                        "ItemId": "movie123",
                        "CollectionType": "movies",
                        "Locations": ["/data/movies"],
                    }
                ],
            )
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.get(
            "/libraries?url=http://jf&api_key=key",
            headers={},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(len(data["libraries"]), 1)
        lib = data["libraries"][0]
        self.assertEqual(lib["itemId"], "movie123")
        self.assertEqual(lib["collectionType"], "movies")
        self.assertEqual(lib["locations"], ["/data/movies"])


if __name__ == "__main__":
    unittest.main()
