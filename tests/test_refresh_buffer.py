import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import radarr_sonarr_jellyfin_notifier.webhooks as webhooks


class RefreshBufferTests(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS": "1",
                "JELLYFIN_NOTIFIER_REFRESH_MAX_WAIT_SECONDS": "2",
            },
            clear=False,
        )
        self.env_patcher.start()
        with webhooks._REFRESH_COND:
            webhooks._REFRESH_QUEUE.clear()

    def tearDown(self):
        self.env_patcher.stop()
        with webhooks._REFRESH_COND:
            webhooks._REFRESH_QUEUE.clear()

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_buffer_coalesces_requests(self, mock_client_cls):
        done = threading.Event()
        calls = []

        def refresh(library_ids=None):
            calls.append(library_ids)
            done.set()
            return True, "ok", 200

        mock_client_cls.return_value = SimpleNamespace(refresh=Mock(side_effect=refresh))

        result1 = webhooks._enqueue_refresh_request("http://jf", "key", ["a"])
        result2 = webhooks._enqueue_refresh_request("http://jf", "key", ["b", "a"])

        self.assertEqual(result1[2], 202)
        self.assertEqual(result2[2], 202)
        self.assertTrue(done.wait(timeout=2))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ["a", "b"])

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_buffer_all_overrides_ids(self, mock_client_cls):
        done = threading.Event()
        calls = []

        def refresh(library_ids=None):
            calls.append(library_ids)
            done.set()
            return True, "ok", 200

        mock_client_cls.return_value = SimpleNamespace(refresh=Mock(side_effect=refresh))

        webhooks._enqueue_refresh_request("http://jf", "key", ["a"])
        webhooks._enqueue_refresh_request("http://jf", "key", None)

        self.assertTrue(done.wait(timeout=2))
        self.assertEqual(calls, [None])

    @patch("radarr_sonarr_jellyfin_notifier.webhooks.JellyfinClient")
    def test_buffer_max_wait_caps_delay(self, mock_client_cls):
        done = threading.Event()

        def refresh(library_ids=None):
            done.set()
            return True, "ok", 200

        mock_client_cls.return_value = SimpleNamespace(refresh=Mock(side_effect=refresh))

        with patch.dict(
            os.environ,
            {
                "JELLYFIN_NOTIFIER_REFRESH_DEBOUNCE_SECONDS": "5",
                "JELLYFIN_NOTIFIER_REFRESH_MAX_WAIT_SECONDS": "1",
            },
        ):
            webhooks._enqueue_refresh_request("http://jf", "key", ["a"])

        self.assertTrue(done.wait(timeout=2))


if __name__ == "__main__":
    unittest.main()
