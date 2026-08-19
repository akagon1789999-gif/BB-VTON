"""FabricProcessor, garment composition and the segmentation gate."""
import unittest

from . import context
from fabric_studio import catalog, garment_composer, garment_templates, imaging, segmentation, storage
from fabric_studio.errors import ValidationError
from fabric_studio.fabric_processor import PROCESSOR_VERSION, processor


class FabricProcessorTest(unittest.TestCase):
    def setUp(self):
        context.reset_stores()
        self.fabric = context.make_fabric("fab_proc", "geometric")

    def test_processing_produces_all_assets(self):
        processed = self.fabric["processed"]
        for key in ("normalizedPath", "tilePath", "thumbnailPath"):
            self.assertTrue(storage.media_path(processed[key]).exists(), key)
        self.assertEqual(processed["processorVersion"], PROCESSOR_VERSION)
        self.assertIn("patternType", processed["metadata"])

    def test_original_image_is_never_modified(self):
        original = storage.media_path(self.fabric["image_path"])
        before = original.read_bytes()
        catalog.ensure_fabric_processed("fab_proc", force=True)
        self.assertEqual(original.read_bytes(), before)

    def test_cache_is_reused(self):
        self.assertTrue(processor.is_current(self.fabric))
        first = self.fabric["processed"]["processedAt"]
        again = catalog.ensure_fabric_processed("fab_proc")
        self.assertEqual(again["processed"]["processedAt"], first)

    def test_cache_invalidated_when_source_changes(self):
        from fabric_studio import swatches
        replacement = swatches.render("floral", 640, ["#0f4d3a", "#e0678a", "#f0c94b"])
        storage.write_media(self.fabric["image_path"], imaging.encode_image(replacement, "JPEG", 92))
        self.assertFalse(processor.is_current(catalog.get_fabric("fab_proc")))
        updated = catalog.ensure_fabric_processed("fab_proc")
        self.assertNotEqual(updated["processed"]["sourceHash"], self.fabric["processed"]["sourceHash"])

    def test_tiny_fabric_image_is_rejected(self):
        tiny = imaging.Image.new("RGB", (100, 100), (120, 80, 60))
        storage.write_media("fabrics/original/tiny.jpg", imaging.encode_image(tiny, "JPEG"))
        record = {"id": "fab_tiny", "name": "Tiny", "image_path": "fabrics/original/tiny.jpg", "is_active": True}
        catalog.save_fabric(record)
        with self.assertRaises(ValidationError):
            catalog.ensure_fabric_processed("fab_tiny")

    def test_missing_source_file_reports_friendly_error(self):
        catalog.save_fabric({"id": "fab_gone", "name": "Gone", "image_path": "fabrics/original/nope.jpg"})
        with self.assertRaises(ValidationError) as caught:
            catalog.ensure_fabric_processed("fab_gone")
        self.assertNotIn("nope.jpg", caught.exception.user_message)


class GarmentComposerTest(unittest.TestCase):
    def setUp(self):
        context.reset_stores()
        self.fabric = context.make_fabric("fab_compose", "geometric")
        self.outfit = context.make_outfit("out_compose", "modern-senator")

    def test_compose_writes_and_caches(self):
        first = garment_composer.compose(self.fabric, self.outfit)
        self.assertFalse(first["cached"])
        self.assertTrue(storage.media_path(first["path"]).exists())
        second = garment_composer.compose(self.fabric, self.outfit)
        self.assertTrue(second["cached"])
        self.assertEqual(first["path"], second["path"])

    def test_cache_key_changes_with_fabric_and_outfit(self):
        other_fabric = context.make_fabric("fab_compose2", "floral", ["#0f4d3a", "#e0678a", "#f0c94b"])
        other_outfit = context.make_outfit("out_compose2", "ankara-gown")
        keys = {
            garment_composer.cache_key(self.fabric, self.outfit),
            garment_composer.cache_key(other_fabric, self.outfit),
            garment_composer.cache_key(self.fabric, other_outfit),
        }
        self.assertEqual(len(keys), 3)

    def test_unknown_template_is_rejected(self):
        broken = context.make_outfit("out_broken", "modern-senator")
        broken["template_id"] = "no-such-template"
        with self.assertRaises(ValidationError):
            garment_composer.render(self.fabric, broken)

    def test_composed_garment_carries_the_fabric_colours(self):
        """The point of composing rather than generating: the cloth survives."""
        image = garment_composer.render(self.fabric, self.outfit)
        mask, _shading, _details = garment_templates.build(
            self.outfit["template_id"], image.size
        )
        numpy = imaging.numpy_module()
        pixels = numpy.asarray(image)
        inside = numpy.asarray(mask) > 200
        garment_pixels = pixels[inside]
        # The fabric is a saturated blue/red/gold print; the backdrop is near-white.
        self.assertGreater(garment_pixels.std(), 18)
        self.assertLess(garment_pixels.mean(), 215)

    def test_every_seeded_template_renders(self):
        for template_id in garment_templates.ids():
            with self.subTest(template=template_id):
                mask, shading, details = garment_templates.build(template_id, (300, 386))
                self.assertEqual(mask.mode, "L")
                self.assertEqual(shading.mode, "L")
                self.assertEqual(details.mode, "RGBA")
                coverage = (imaging.numpy_module().asarray(mask) > 128).mean()
                self.assertGreater(coverage, 0.15)
                self.assertLess(coverage, 0.85)


class PersonPhotoValidatorTest(unittest.TestCase):
    def test_good_photo_passes(self):
        data_url, report = segmentation.validator.prepare(context.person_data_url())
        self.assertTrue(report["ok"])
        self.assertTrue(data_url.startswith("data:image/jpeg;base64,"))

    def test_small_photo_is_rejected(self):
        with self.assertRaises(ValidationError):
            segmentation.validator.prepare(context.person_data_url(width=200, height=300))

    def test_dark_photo_is_rejected(self):
        with self.assertRaises(ValidationError):
            segmentation.validator.prepare(context.person_data_url(color=(6, 6, 6)))

    def test_large_photo_is_downscaled_before_inference(self):
        from fabric_studio import config
        _data_url, report = segmentation.validator.prepare(
            context.person_data_url(width=2400, height=3600)
        )
        self.assertLessEqual(report["metrics"]["normalizedHeight"], config.person_image_max_edge())

    def test_wide_photo_warns_but_passes(self):
        _data_url, report = segmentation.validator.prepare(
            context.person_data_url(width=1200, height=600)
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["warnings"])

    def test_default_segmentation_provider_is_decoupled_from_the_engine(self):
        provider = segmentation.get_segmentation_provider()
        result = provider.segment(context.person_data_url())
        self.assertFalse(result.available)
        self.assertEqual(result.masks, {})
        self.assertIn("person", segmentation.LABELS)


if __name__ == "__main__":
    unittest.main()


class ResultStorageTest(unittest.TestCase):
    """The real providers return a CDN URL; we copy it into our own storage."""

    def setUp(self):
        context.reset_stores()

    def test_data_url_results_are_stored(self):
        from fabric_studio import generations
        image = imaging.Image.new("RGB", (400, 600), (120, 60, 40))
        url = generations._store_result("gen_data", imaging.to_data_url(image))
        self.assertEqual(url, "/media/generations/gen_data.jpg")
        self.assertTrue(storage.media_path("generations/gen_data.jpg").exists())

    def test_local_media_results_are_passed_through(self):
        from fabric_studio import generations
        self.assertEqual(
            generations._store_result("gen_local", "/media/generations/mock-x.jpg"),
            "/media/generations/mock-x.jpg",
        )

    def test_remote_results_are_downloaded(self):
        import http.server
        import threading

        from fabric_studio import generations

        payload = imaging.encode_image(imaging.Image.new("RGB", (300, 450), (30, 90, 160)), "JPEG")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib naming
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)

        url = "http://127.0.0.1:%d/output_0.jpg" % server.server_port
        stored = generations._store_result("gen_remote", url)
        self.assertEqual(stored, "/media/generations/gen_remote.jpg")
        with imaging.Image.open(str(storage.media_path("generations/gen_remote.jpg"))) as saved:
            self.assertEqual(saved.size, (300, 450))

    def test_non_http_result_urls_are_refused(self):
        from fabric_studio import generations
        from fabric_studio.errors import ProviderError
        with self.assertRaises(ProviderError):
            generations._store_result("gen_bad", "file:///etc/passwd")


class ReferencePhotoTest(unittest.TestCase):
    """A garment photograph is used only when it can actually be masked."""

    def setUp(self):
        context.reset_stores()
        self.fabric = context.make_fabric("fab_ref", "stripes", ["#b8232f", "#f4efe6"])
        self.outfit = context.make_outfit("out_ref", "modern-senator")

    def _store_reference(self, image):
        relative = "outfits/out_ref-reference.jpg"
        storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))
        return catalog.save_outfit(dict(self.outfit, reference_image_path=relative))

    def test_a_photo_with_a_model_in_it_is_refused(self):
        from fabric_studio import refabric
        report = refabric.usability(context.person_image())
        self.assertFalse(report["ok"])
        self.assertTrue(any("model" in reason for reason in report["reasons"]))

    def test_an_unusable_reference_falls_back_to_the_template(self):
        """It must fall back, never paint fabric over a face."""
        outfit = self._store_reference(context.person_image())
        composed = garment_composer.render(self.fabric, outfit)
        template_only = garment_composer._render_from_template(self.fabric, outfit)
        self.assertEqual(composed.size, template_only.size)

    def test_a_plain_garment_on_a_contrasting_ground_is_accepted(self):
        from fabric_studio import refabric
        # A solid mid-grey garment shape on a dark ground: no model, no print,
        # and clearly separable — the case the local path is for.
        photo = imaging.Image.new("RGB", (600, 800), (18, 18, 22))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(photo)
        draw.rounded_rectangle([150, 120, 450, 700], radius=40, fill=(178, 176, 170))
        report = refabric.usability(photo)
        self.assertTrue(report["ok"], report["reasons"])

    def test_re_fabric_keeps_the_garment_shape_and_changes_its_colour(self):
        from fabric_studio import refabric
        from PIL import ImageDraw
        photo = imaging.Image.new("RGB", (600, 800), (18, 18, 22))
        draw = ImageDraw.Draw(photo)
        draw.rounded_rectangle([150, 120, 450, 700], radius=40, fill=(178, 176, 170))
        tile = imaging.Image.new("RGB", (64, 64), (180, 30, 40))

        result = refabric.refabric(photo, tile, scale=0.4)
        numpy = imaging.numpy_module()
        before = numpy.asarray(photo, dtype=numpy.float32)
        after = numpy.asarray(result, dtype=numpy.float32)
        # Background untouched, garment now red.
        self.assertLess(abs(after[10, 10] - before[10, 10]).max(), 12)
        centre = after[400, 300]
        self.assertGreater(centre[0], centre[1] + 40)
