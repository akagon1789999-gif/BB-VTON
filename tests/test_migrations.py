"""Seeding and repair. Slower than the rest: it renders the whole catalogue."""
import os
import shutil
import tempfile
import unittest

from . import context
from fabric_studio import catalog, migrations, storage
from fabric_studio.catalog import FABRIC_STORE, OUTFIT_STORE


class MigrationTest(unittest.TestCase):
    """Runs against its own DATA_DIR so it cannot disturb the other tests."""

    @classmethod
    def setUpClass(cls):
        cls.previous_dir = os.environ["DATA_DIR"]
        cls.temp_dir = tempfile.mkdtemp(prefix="fabric-studio-migrations-")
        os.environ["DATA_DIR"] = cls.temp_dir
        storage.ensure_dirs()
        cls.result = migrations.run_migrations()

    @classmethod
    def tearDownClass(cls):
        os.environ["DATA_DIR"] = cls.previous_dir
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_all_migrations_applied(self):
        self.assertEqual(
            self.result["applied"],
            [name for name, _fn in migrations.MIGRATIONS],
        )
        self.assertEqual(migrations.status()["pending"], [])

    def test_catalogues_are_seeded(self):
        self.assertGreaterEqual(FABRIC_STORE.count(), 20)
        self.assertGreaterEqual(OUTFIT_STORE.count(), 10)

    def test_every_seed_fabric_is_processed_and_has_metadata(self):
        seeded = [r for r in FABRIC_STORE.all() if r.get("is_seed")]
        self.assertGreaterEqual(len(seeded), 20)
        for record in seeded:
            with self.subTest(fabric=record["id"]):
                processed = record.get("processed") or {}
                self.assertTrue(processed.get("normalizedPath"))
                self.assertTrue(storage.media_path(processed["tilePath"]).exists())
                self.assertTrue(record.get("primary_colors"))
                self.assertTrue(record.get("license"))

    def test_every_seed_outfit_has_a_preview_and_a_valid_template(self):
        from fabric_studio import garment_templates
        for record in OUTFIT_STORE.all():
            with self.subTest(outfit=record["id"]):
                self.assertIsNotNone(garment_templates.get(record["template_id"]))
                self.assertTrue(storage.media_path(record["preview_image_path"]).exists())

    def test_migrations_are_idempotent(self):
        before = FABRIC_STORE.count()
        migrations.run_migrations()
        self.assertEqual(FABRIC_STORE.count(), before)

    def test_admin_records_survive_a_rerun(self):
        catalog.save_fabric({"id": "fab_admin_added", "name": "Admin Fabric", "category": "Lace"})
        migrations.run_migrations(force=True)
        self.assertIsNotNone(catalog.get_fabric("fab_admin_added"))

    def test_repair_regenerates_missing_seed_swatches(self):
        record = FABRIC_STORE.all()[0]
        storage.media_path(record["image_path"]).unlink()
        report = migrations.repair_assets()
        self.assertIn(record["id"], report["repaired"])
        self.assertTrue(storage.media_path(record["image_path"]).exists())

    def test_repair_reports_uploads_it_cannot_regenerate(self):
        catalog.save_fabric({"id": "fab_uploaded", "name": "Uploaded",
                             "image_path": "fabrics/original/missing-upload.jpg"})
        report = migrations.repair_assets()
        self.assertIn("fab_uploaded", report["missingSourceImage"])


if __name__ == "__main__":
    unittest.main()
