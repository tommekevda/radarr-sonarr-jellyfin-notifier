import unittest
from types import SimpleNamespace

from radarr_sonarr_jellyfin_notifier.webhooks import (
    is_test_event,
    parse_collection_types_header,
    parse_library_ids_header,
)


class WebhookUtilsTests(unittest.TestCase):
    def test_is_test_event_case_insensitive(self):
        self.assertTrue(is_test_event("Test"))
        self.assertTrue(is_test_event("test"))
        self.assertFalse(is_test_event("Download"))
        self.assertFalse(is_test_event(123))

    def test_parse_library_ids_header(self):
        req = SimpleNamespace(headers={"X-Jellyfin-Library-Ids": " a, b ,, c "})
        self.assertEqual(parse_library_ids_header(req), ["a", "b", "c"])

    def test_parse_collection_types_header(self):
        req = SimpleNamespace(
            headers={"X-Jellyfin-Collection-Types": " Movies, TVShows , ,"}
        )
        self.assertEqual(parse_collection_types_header(req), ["movies", "tvshows"])


if __name__ == "__main__":
    unittest.main()
