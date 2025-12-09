import unittest

from jellyfin import merge_ids, select_library_ids_by_collection


class JellyfinUtilsTest(unittest.TestCase):
    def test_merge_ids_deduplicates_preserves_order(self):
        merged = merge_ids(["a", "b"], ["b", "c"], None, ["c", "d"])
        self.assertEqual(merged, ["a", "b", "c", "d"])

    def test_select_library_ids_by_collection(self):
        folders = [
            {"Name": "Movies", "ItemId": "1", "CollectionType": "movies"},
            {"Name": "TV", "ItemId": "2", "CollectionType": "tvshows"},
            {"Name": "Music", "ItemId": "3", "CollectionType": "music"},
        ]
        selected, missing, available = select_library_ids_by_collection(
            folders, ["tvshows", "unknown"]
        )
        self.assertEqual(selected, ["2"])
        self.assertEqual(missing, ["unknown"])
        self.assertEqual(sorted(available), ["movies", "music", "tvshows"])


if __name__ == "__main__":
    unittest.main()
