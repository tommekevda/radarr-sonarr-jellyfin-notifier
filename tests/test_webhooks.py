import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import radarr_sonarr_jellyfin_notifier.webhooks as webhooks
from radarr_sonarr_jellyfin_notifier.main import create_app


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.env_patcher = patch.dict(
            os.environ,
            {
                "JELLYFIN_API_KEY": "",
                "JELLYFIN_NOTIFIER_ALLOWLIST": "",
                "JELLYFIN_NOTIFIER_RATE_LIMIT_PER_MINUTE": "0",
                "JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS": "0",
                "JELLYFIN_NOTIFIER_REFRESH_MAX_WAIT_SECONDS": "0",
                "JELLYFIN_URL": "",
            },
            clear=False,
        )
        self.env_patcher.start()
        webhooks._RATE_LIMIT_STATE.clear()
        with webhooks._REFRESH_COND:
            webhooks._REFRESH_QUEUE.clear()

    def tearDown(self):
        self.env_patcher.stop()
        webhooks._RATE_LIMIT_STATE.clear()
        with webhooks._REFRESH_COND:
            webhooks._REFRESH_QUEUE.clear()

    def test_health_endpoint_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["status"], "ok")

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_refresh_merges_ids_and_collection_types(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [{"Name": "Movies", "ItemId": "movie123", "CollectionType": "movies"}],
            ),
        )
        mock_client_cls.return_value = fake_client

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            mock_enqueue.return_value = (True, "queued", 202)
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

        self.assertEqual(resp.status_code, 202)
        mock_enqueue.assert_called_once_with(
            "http://jf", "key", ["libA", "libB", "movie123"]
        )

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
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

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_missing_headers_returns_400(self, mock_client_cls):
        resp = self.client.post("/radarr-webhook", json={"eventType": "Download"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Missing credentials", resp.get_data(as_text=True))
        mock_client_cls.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_uses_env_credentials_when_headers_missing(self, mock_client_cls):
        mock_client_cls.return_value = SimpleNamespace()

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            mock_enqueue.return_value = (True, "queued", 202)
            with patch.dict(
                os.environ, {"JELLYFIN_URL": "http://jf", "JELLYFIN_API_KEY": "key"}
            ):
                resp = self.client.post(
                    "/radarr-webhook",
                    json={"eventType": "Download"},
                )

        self.assertEqual(resp.status_code, 202)
        mock_client_cls.assert_called_once_with("http://jf", "key")
        mock_enqueue.assert_called_once_with("http://jf", "key", None)

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_allowlist_blocks_request(self, mock_client_cls):
        with patch.dict(os.environ, {"JELLYFIN_NOTIFIER_ALLOWLIST": "10.0.0.1"}):
            resp = self.client.post(
                "/radarr-webhook",
                json={"eventType": "Download"},
                headers={
                    "X-Jellyfin-Url": "http://jf",
                    "X-Jellyfin-Api-Key": "key",
                },
            )

        self.assertEqual(resp.status_code, 403)
        mock_client_cls.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_allowlist_invalid_entry_returns_500(self, mock_client_cls):
        with patch.dict(os.environ, {"JELLYFIN_NOTIFIER_ALLOWLIST": "nope"}):
            resp = self.client.post(
                "/radarr-webhook",
                json={"eventType": "Download"},
                headers={
                    "X-Jellyfin-Url": "http://jf",
                    "X-Jellyfin-Api-Key": "key",
                },
            )

        self.assertEqual(resp.status_code, 500)
        self.assertIn("Invalid allowlist entry", resp.get_data(as_text=True))
        mock_client_cls.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_allowlist_allows_request(self, mock_client_cls):
        mock_client_cls.return_value = SimpleNamespace()

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            mock_enqueue.return_value = (True, "queued", 202)
            with patch.dict(
                os.environ, {"JELLYFIN_NOTIFIER_ALLOWLIST": "127.0.0.0/24"}
            ):
                resp = self.client.post(
                    "/radarr-webhook",
                    json={"eventType": "Download"},
                    headers={
                        "X-Jellyfin-Url": "http://jf",
                        "X-Jellyfin-Api-Key": "key",
                    },
                )

        self.assertEqual(resp.status_code, 202)
        mock_enqueue.assert_called_once_with("http://jf", "key", None)

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_rate_limit_exceeded_returns_429(self, mock_client_cls):
        mock_client_cls.return_value = SimpleNamespace()

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            mock_enqueue.return_value = (True, "queued", 202)
            with patch.dict(
                os.environ, {"JELLYFIN_NOTIFIER_RATE_LIMIT_PER_MINUTE": "1"}
            ):
                resp1 = self.client.post(
                    "/radarr-webhook",
                    json={"eventType": "Download"},
                    headers={
                        "X-Jellyfin-Url": "http://jf",
                        "X-Jellyfin-Api-Key": "key",
                    },
                )
                resp2 = self.client.post(
                    "/radarr-webhook",
                    json={"eventType": "Download"},
                    headers={
                        "X-Jellyfin-Url": "http://jf",
                        "X-Jellyfin-Api-Key": "key",
                    },
                )

        self.assertEqual(resp1.status_code, 202)
        self.assertEqual(resp2.status_code, 429)
        self.assertEqual(resp2.headers.get("Retry-After"), "60")
        self.assertEqual(mock_enqueue.call_count, 1)

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_test_event_does_not_refresh(self, mock_client_cls):
        fake_client = SimpleNamespace(
            ping=Mock(return_value=(True, "ping ok", 200)),
            fetch_virtual_folders=Mock(return_value=(True, "vf ok", 200, [])),
            refresh=Mock(return_value=(True, "refresh", 200)),
        )
        mock_client_cls.return_value = fake_client

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            resp = self.client.post(
                "/radarr-webhook",
                json={"eventType": "Test"},
                headers={
                    "X-Jellyfin-Url": "http://jf",
                    "X-Jellyfin-Api-Key": "key",
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("ping ok; vf ok", resp.get_data(as_text=True))
        fake_client.refresh.assert_not_called()
        mock_enqueue.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_collection_types_fetch_folders_error(self, mock_client_cls):
        refresh = Mock(return_value=(True, "refresh", 200))
        fake_client = SimpleNamespace(
            fetch_virtual_folders=Mock(return_value=(False, "vf error", 502, None)),
            refresh=refresh,
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.post(
            "/radarr-webhook",
            json={"eventType": "Download"},
            headers={
                "X-Jellyfin-Url": "http://jf",
                "X-Jellyfin-Api-Key": "key",
                "X-Jellyfin-Collection-Types": "movies",
            },
        )

        self.assertEqual(resp.status_code, 502)
        self.assertIn("vf error", resp.get_data(as_text=True))
        refresh.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_collection_types_no_matching_ids_returns_400(
        self, mock_client_cls
    ):
        refresh = Mock(return_value=(True, "refresh", 200))
        fake_client = SimpleNamespace(
            fetch_virtual_folders=Mock(
                return_value=(
                    True,
                    "ok",
                    200,
                    [{"Name": "Movies", "CollectionType": "movies"}],
                )
            ),
            refresh=refresh,
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.post(
            "/radarr-webhook",
            json={"eventType": "Download"},
            headers={
                "X-Jellyfin-Url": "http://jf",
                "X-Jellyfin-Api-Key": "key",
                "X-Jellyfin-Collection-Types": "movies",
            },
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("No libraries matched collection types", resp.get_data(as_text=True))
        refresh.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_radarr_refresh_when_no_targets_refreshes_all(self, mock_client_cls):
        mock_client_cls.return_value = SimpleNamespace()

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            mock_enqueue.return_value = (True, "queued", 202)
            resp = self.client.post(
                "/radarr-webhook",
                json={"eventType": "Download"},
                headers={
                    "X-Jellyfin-Url": "http://jf",
                    "X-Jellyfin-Api-Key": "key",
                },
            )

        self.assertEqual(resp.status_code, 202)
        mock_enqueue.assert_called_once_with("http://jf", "key", None)

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_sonarr_unknown_collection_type_returns_400(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [{"Name": "TV", "ItemId": "tv123", "CollectionType": "tvshows"}],
            )
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.post(
            "/sonarr-webhook",
            json={"eventType": "Download"},
            headers={
                "X-Jellyfin-Url": "http://jf",
                "X-Jellyfin-Api-Key": "key",
                "X-Jellyfin-Collection-Types": "unknown",
            },
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown collection types", resp.get_data(as_text=True))

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_sonarr_refresh_merges_ids_and_collection_types(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [{"Name": "TV", "ItemId": "tv123", "CollectionType": "tvshows"}],
            )
        )
        mock_client_cls.return_value = fake_client

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            mock_enqueue.return_value = (True, "queued", 202)
            resp = self.client.post(
                "/sonarr-webhook",
                json={"eventType": "Download"},
                headers={
                    "X-Jellyfin-Url": "http://jf",
                    "X-Jellyfin-Api-Key": "key",
                    "X-Jellyfin-Library-Ids": "libA",
                    "X-Jellyfin-Collection-Types": "tvshows",
                },
            )

        self.assertEqual(resp.status_code, 202)
        mock_enqueue.assert_called_once_with("http://jf", "key", ["libA", "tv123"])

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_sonarr_missing_headers_returns_400(self, mock_client_cls):
        resp = self.client.post("/sonarr-webhook", json={"eventType": "Download"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Missing credentials", resp.get_data(as_text=True))
        mock_client_cls.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_sonarr_test_event_ping_failure(self, mock_client_cls):
        fake_client = SimpleNamespace(
            ping=Mock(return_value=(False, "ping failed", 502)),
            fetch_virtual_folders=Mock(return_value=(True, "vf ok", 200, [])),
            refresh=Mock(return_value=(True, "refresh", 200)),
        )
        mock_client_cls.return_value = fake_client

        with patch("radarr_sonarr_jellyfin_notifier.webhooks._enqueue_refresh_request") as mock_enqueue:
            resp = self.client.post(
                "/sonarr-webhook",
                json={"eventType": "Test"},
                headers={
                    "X-Jellyfin-Url": "http://jf",
                    "X-Jellyfin-Api-Key": "key",
                },
            )

        self.assertEqual(resp.status_code, 502)
        self.assertIn("ping failed", resp.get_data(as_text=True))
        fake_client.fetch_virtual_folders.assert_not_called()
        fake_client.refresh.assert_not_called()
        mock_enqueue.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_libraries_endpoint_requires_credentials(self, mock_client_cls):
        resp = self.client.get("/libraries")
        self.assertEqual(resp.status_code, 400)
        mock_client_cls.assert_not_called()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_libraries_endpoint_uses_env_credentials(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (True, "ok", 200, [])
        )
        mock_client_cls.return_value = fake_client

        with patch.dict(
            os.environ, {"JELLYFIN_URL": "http://jf", "JELLYFIN_API_KEY": "key"}
        ):
            resp = self.client.get("/libraries")

        self.assertEqual(resp.status_code, 200)
        mock_client_cls.assert_called_once_with("http://jf", "key")

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_libraries_endpoint_propagates_fetch_error(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (False, "nope", 401, None)
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.get("/libraries?url=http://jf&api_key=key")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("nope", resp.get_data(as_text=True))

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
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

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_libraries_endpoint_uses_headers(self, mock_client_cls):
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
            "/libraries",
            headers={"X-Jellyfin-Url": "http://jf", "X-Jellyfin-Api-Key": "key"},
        )
        self.assertEqual(resp.status_code, 200)

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_libraries_endpoint_uses_path_infos_when_locations_missing(
        self, mock_client_cls
    ):
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
                        "Locations": [],
                        "LibraryOptions": {"PathInfos": [{"Path": "/data/movies"}]},
                    }
                ],
            )
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.get("/libraries?url=http://jf&api_key=key")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.get_data(as_text=True))
        lib = data["libraries"][0]
        self.assertEqual(lib["locations"], ["/data/movies"])

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_libraries_endpoint_uses_id_when_itemid_missing(self, mock_client_cls):
        fake_client = SimpleNamespace(
            fetch_virtual_folders=lambda: (
                True,
                "ok",
                200,
                [{"Name": "Movies", "Id": "movie123", "CollectionType": "movies"}],
            )
        )
        mock_client_cls.return_value = fake_client

        resp = self.client.get("/libraries?url=http://jf&api_key=key")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.get_data(as_text=True))
        lib = data["libraries"][0]
        self.assertEqual(lib["itemId"], "movie123")


if __name__ == "__main__":
    unittest.main()
