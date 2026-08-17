import unittest

from . import context  # noqa: F401  (sets DATA_DIR first)
from fabric_studio import storage


class JsonStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = storage.JsonStore("test_store.json", key_field="id", indexes=("category",))
        self.store.replace_all([])

    def test_insert_get_update_delete(self):
        self.store.insert({"id": "a", "category": "Ankara", "name": "One"})
        self.assertEqual(self.store.get("a")["name"], "One")
        self.store.update("a", {"name": "Two"})
        self.assertEqual(self.store.get("a")["name"], "Two")
        self.assertTrue(self.store.delete("a"))
        self.assertIsNone(self.store.get("a"))

    def test_duplicate_insert_rejected(self):
        self.store.insert({"id": "a"})
        with self.assertRaises(KeyError):
            self.store.insert({"id": "a"})

    def test_index_lookup_is_case_insensitive(self):
        self.store.insert({"id": "a", "category": "Ankara"})
        self.store.insert({"id": "b", "category": "Lace"})
        self.assertEqual([r["id"] for r in self.store.find_by("category", "ankara")], ["a"])

    def test_returned_records_are_copies(self):
        self.store.insert({"id": "a", "name": "One"})
        record = self.store.get("a")
        record["name"] = "mutated"
        self.assertEqual(self.store.get("a")["name"], "One")

    def test_upsert_merges(self):
        self.store.insert({"id": "a", "name": "One", "keep": True})
        merged = self.store.upsert({"id": "a", "name": "Two"})
        self.assertEqual(merged["name"], "Two")
        self.assertTrue(merged["keep"])

    def test_trim_keeps_newest(self):
        for index in range(5):
            self.store.insert({"id": str(index), "created_at": "2026-01-0%d" % (index + 1)})
        self.store.trim_to(2, "created_at")
        self.assertEqual(sorted(r["id"] for r in self.store.all()), ["3", "4"])

    def test_corrupt_file_does_not_raise(self):
        self.store.path.write_text("{not json", encoding="utf-8")
        self.store._cache = None
        self.assertEqual(self.store.all(), [])


class MediaPathTest(unittest.TestCase):
    def test_traversal_is_blocked(self):
        for bad in ("../secrets.json", "fabrics/../../etc/passwd", "fabrics/original/../../../.."):
            with self.assertRaises(ValueError):
                storage.media_path(bad)

    def test_absolute_paths_are_treated_as_media_relative(self):
        # A leading slash must not reach the filesystem root; it is resolved
        # inside the media tree instead.
        resolved = storage.media_path("/etc/passwd")
        self.assertTrue(str(resolved).startswith(str(storage.media_dir().resolve())))

    def test_normal_path_resolves_inside_media(self):
        path = storage.media_path("fabrics/original/x.jpg")
        self.assertIn("media", str(path))

    def test_media_url_passes_through_absolute(self):
        self.assertEqual(storage.media_url("https://cdn/x.jpg"), "https://cdn/x.jpg")
        self.assertEqual(storage.media_url("fabrics/x.jpg"), "/media/fabrics/x.jpg")


if __name__ == "__main__":
    unittest.main()
