"""Web catalogue importer: fetch guards, review gate, publish rules."""
import os
import unittest

from . import context
from fabric_studio import catalog, importer, imaging, storage, swatches
from fabric_studio.errors import ValidationError


class ImporterGuardTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FABRIC_IMPORT_ALLOWED_HOSTS", None)

    def tearDown(self):
        os.environ.pop("FABRIC_IMPORT_ALLOWED_HOSTS", None)

    def test_importer_is_off_until_hosts_are_approved(self):
        self.assertFalse(importer.importer_enabled())
        with self.assertRaises(ValidationError) as caught:
            importer.validate_url("https://images.example.com/a.jpg")
        self.assertIn("switched off", caught.exception.user_message)

    def test_plain_http_is_refused(self):
        os.environ["FABRIC_IMPORT_ALLOWED_HOSTS"] = "images.example.com"
        with self.assertRaises(ValidationError) as caught:
            importer.validate_url("http://images.example.com/a.jpg")
        self.assertIn("https", caught.exception.user_message)

    def test_hosts_outside_the_allow_list_are_refused(self):
        os.environ["FABRIC_IMPORT_ALLOWED_HOSTS"] = "images.example.com"
        with self.assertRaises(ValidationError) as caught:
            importer.validate_url("https://not-approved.example.org/a.jpg")
        self.assertIn("approved import list", caught.exception.user_message)

    def test_internal_addresses_are_refused(self):
        os.environ["FABRIC_IMPORT_ALLOWED_HOSTS"] = "localhost"
        with self.assertRaises(ValidationError):
            importer.validate_url("https://localhost/a.jpg")

    def test_status_reports_configuration(self):
        os.environ["FABRIC_IMPORT_ALLOWED_HOSTS"] = "images.example.com"
        status = importer.status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["allowedHosts"], ["images.example.com"])


class ImportReviewTest(unittest.TestCase):
    """The import itself is stubbed; the review gate is what is under test."""

    def setUp(self):
        context.reset_stores()
        self.fabric_id = "fab_imported"
        image = swatches.render("floral", 640, ["#0f4d3a", "#e0678a", "#f0c94b"])
        relative = "imports/%s.jpg" % self.fabric_id
        storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))
        catalog.save_fabric({
            "id": self.fabric_id,
            "name": "Imported Fabric",
            "category": "Ankara",
            "image_path": relative,
            "image_url": storage.media_url(relative),
            "source_url": "https://images.example.com/a.jpg",
            "review_status": catalog.REVIEW_PENDING,
            "is_active": False,
            "license": "",
        })

    def test_pending_imports_never_reach_customers(self):
        self.assertEqual(catalog.search_fabrics()["total"], 0)
        self.assertEqual([r["id"] for r in importer.list_pending()], [self.fabric_id])

    def test_publishing_requires_a_licence(self):
        with self.assertRaises(ValidationError) as caught:
            importer.publish(self.fabric_id)
        self.assertIn("licence", caught.exception.user_message.lower())

    def test_publishing_requires_a_source_url(self):
        catalog.save_fabric(dict(catalog.get_fabric(self.fabric_id), license="CC BY 4.0", source_url=""))
        with self.assertRaises(ValidationError) as caught:
            importer.publish(self.fabric_id)
        self.assertIn("source", caught.exception.user_message.lower())

    def test_publishing_with_a_licence_activates_and_processes(self):
        catalog.save_fabric(dict(catalog.get_fabric(self.fabric_id), license="CC BY-SA 4.0"))
        published = importer.publish(self.fabric_id)
        self.assertTrue(published["is_active"])
        self.assertEqual(published["review_status"], catalog.REVIEW_APPROVED)
        self.assertTrue(published["processed"]["normalizedPath"])
        self.assertEqual(catalog.search_fabrics()["total"], 1)

    def test_rejecting_keeps_it_hidden_and_records_the_reason(self):
        rejected = importer.reject(self.fabric_id, reason="Licence unclear")
        self.assertFalse(rejected["is_active"])
        self.assertEqual(rejected["review_status"], catalog.REVIEW_REJECTED)
        self.assertEqual(rejected["review_note"], "Licence unclear")
        self.assertEqual(catalog.search_fabrics()["total"], 0)


if __name__ == "__main__":
    unittest.main()
