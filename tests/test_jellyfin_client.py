import unittest
from unittest.mock import Mock, patch

import requests

from radarr_sonarr_jellyfin_notifier.jellyfin import JellyfinClient


def _make_response(status_code=200, json_data=None, json_exc=None):
    resp = Mock()
    resp.status_code = status_code
    if json_exc is not None:
        resp.json.side_effect = json_exc
    else:
        resp.json.return_value = json_data
    return resp


class JellyfinClientTests(unittest.TestCase):
    def setUp(self):
        self.client = JellyfinClient("http://jf/", "key")

    def test_base_url_strips_trailing_slash(self):
        self.assertEqual(self.client.base_url, "http://jf")

    def test_headers_include_token(self):
        self.assertEqual(self.client.headers, {"X-Emby-Token": "key"})

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_ping_success(self, mock_get):
        mock_get.side_effect = [Mock(), _make_response(status_code=200)]
        ok, message, status = self.client.ping()
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertEqual(message, "Jellyfin connection and API key OK")
        mock_get.assert_any_call("http://jf", timeout=5)
        mock_get.assert_any_call(
            "http://jf/System/Info",
            headers={"X-Emby-Token": "key"},
            timeout=5,
        )

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_ping_api_key_rejected(self, mock_get):
        mock_get.side_effect = [Mock(), _make_response(status_code=401)]
        ok, message, status = self.client.ping()
        self.assertFalse(ok)
        self.assertEqual(status, 401)
        self.assertIn("API key rejected", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_ping_system_info_failure(self, mock_get):
        mock_get.side_effect = [Mock(), _make_response(status_code=500)]
        ok, message, status = self.client.ping()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIn("Failed to reach Jellyfin", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_ping_first_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("boom")
        ok, message, status = self.client.ping()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIn("Failed to reach Jellyfin", message)
        self.assertEqual(mock_get.call_count, 1)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_ping_system_info_exception(self, mock_get):
        mock_get.side_effect = [Mock(), requests.RequestException("boom")]
        ok, message, status = self.client.ping()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIn("Failed to reach Jellyfin", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_fetch_virtual_folders_success_sorted(self, mock_get):
        resp = _make_response(
            json_data=[
                {"Name": "b", "ItemId": "2", "CollectionType": "movies"},
                {"Name": "A", "ItemId": "1", "CollectionType": "tvshows"},
            ]
        )
        mock_get.return_value = resp
        ok, message, status, folders = self.client.fetch_virtual_folders()
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertEqual(message, "Jellyfin virtual folders listed")
        self.assertEqual([f["Name"] for f in folders], ["A", "b"])

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_fetch_virtual_folders_handles_dict(self, mock_get):
        resp = _make_response(json_data={"Name": "Only", "ItemId": "1"})
        mock_get.return_value = resp
        ok, message, status, folders = self.client.fetch_virtual_folders()
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["Name"], "Only")

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_fetch_virtual_folders_json_error(self, mock_get):
        resp = _make_response(json_exc=ValueError("bad json"))
        mock_get.return_value = resp
        ok, message, status, folders = self.client.fetch_virtual_folders()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIsNone(folders)
        self.assertIn("Failed to parse Jellyfin virtual folders response", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_fetch_virtual_folders_api_key_rejected(self, mock_get):
        resp = _make_response(status_code=401, json_data=[])
        mock_get.return_value = resp
        ok, message, status, folders = self.client.fetch_virtual_folders()
        self.assertFalse(ok)
        self.assertEqual(status, 401)
        self.assertIsNone(folders)
        self.assertIn("API key rejected", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_fetch_virtual_folders_bad_status(self, mock_get):
        resp = _make_response(status_code=500, json_data=[])
        mock_get.return_value = resp
        ok, message, status, folders = self.client.fetch_virtual_folders()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIsNone(folders)
        self.assertIn("Failed to fetch Jellyfin virtual folders", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.get")
    def test_fetch_virtual_folders_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("boom")
        ok, message, status, folders = self.client.fetch_virtual_folders()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIsNone(folders)
        self.assertIn("Failed to fetch Jellyfin virtual folders", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_selected_libraries_success(self, mock_post):
        mock_post.side_effect = [
            _make_response(status_code=204),
            _make_response(status_code=204),
        ]
        ok, message, status = self.client.refresh(["a", "b"])
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertIn("selected libraries", message)
        mock_post.assert_any_call(
            "http://jf/Items/a/Refresh",
            headers={"X-Emby-Token": "key"},
            params={"Recursive": "true"},
            timeout=10,
        )
        mock_post.assert_any_call(
            "http://jf/Items/b/Refresh",
            headers={"X-Emby-Token": "key"},
            params={"Recursive": "true"},
            timeout=10,
        )

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_selected_libraries_failure_status(self, mock_post):
        mock_post.return_value = _make_response(status_code=500)
        ok, message, status = self.client.refresh(["bad"])
        self.assertFalse(ok)
        self.assertEqual(status, 500)
        self.assertIn("bad (status 500)", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_selected_libraries_failure_exception(self, mock_post):
        mock_post.side_effect = requests.RequestException("boom")
        ok, message, status = self.client.refresh(["bad"])
        self.assertFalse(ok)
        self.assertEqual(status, 500)
        self.assertIn("bad (error)", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_all_success(self, mock_post):
        mock_post.return_value = _make_response(status_code=204)
        ok, message, status = self.client.refresh()
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertIn("Triggered Jellyfin refresh", message)
        mock_post.assert_called_once_with(
            "http://jf/Library/Refresh",
            headers={"X-Emby-Token": "key"},
            timeout=10,
        )

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_all_failure_status(self, mock_post):
        mock_post.return_value = _make_response(status_code=500)
        ok, message, status = self.client.refresh()
        self.assertFalse(ok)
        self.assertEqual(status, 500)
        self.assertIn("Failed to trigger Jellyfin", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_all_exception(self, mock_post):
        mock_post.side_effect = requests.RequestException("boom")
        ok, message, status = self.client.refresh()
        self.assertFalse(ok)
        self.assertEqual(status, 502)
        self.assertIn("Failed to trigger Jellyfin", message)

    @patch("radarr_sonarr_jellyfin_notifier.jellyfin.requests.post")
    def test_refresh_empty_list_triggers_full_refresh(self, mock_post):
        mock_post.return_value = _make_response(status_code=204)
        ok, message, status = self.client.refresh([])
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        mock_post.assert_called_once_with(
            "http://jf/Library/Refresh",
            headers={"X-Emby-Token": "key"},
            timeout=10,
        )


if __name__ == "__main__":
    unittest.main()
