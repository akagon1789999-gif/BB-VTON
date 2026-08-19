"""HTTP surface: catalogue endpoints, generation lifecycle, history, admin."""
import functools
import json
import os
import time
import unittest

from flask import Flask, Response

from . import context
from fabric_studio import catalog, garment_composer, imaging, register, storage
from fabric_studio.generations import GENERATION_STORE

ADMIN_HEADER = {"X-Test-Admin": "yes"}


def fake_admin_required(function):
    """Stand-in for server.py's HTTP-basic guard."""
    from flask import request

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Test-Admin") != "yes":
            return Response(json.dumps({"message": "Unauthorized"}), status=401,
                            mimetype="application/json")
        return function(*args, **kwargs)
    return wrapper


def build_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    register(app, admin_required=fake_admin_required)
    return app


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = build_app()
        cls.client = cls.app.test_client()

    def setUp(self):
        context.reset_stores()
        self.fabric = context.make_fabric("fab_api", "geometric", name="Royal Blue Ankara")
        self.outfit = context.make_outfit("out_api", "modern-senator", name="Modern Senator")

    def get_json(self, path, client_id="testclient1", **kwargs):
        headers = kwargs.pop("headers", {})
        headers.setdefault("X-BB-Client-Id", client_id)
        response = self.client.get(path, headers=headers, **kwargs)
        return response.status_code, response.get_json()

    def post_json(self, path, payload, client_id="testclient1", **kwargs):
        headers = kwargs.pop("headers", {})
        headers.setdefault("X-BB-Client-Id", client_id)
        response = self.client.post(path, json=payload, headers=headers, **kwargs)
        return response.status_code, response.get_json()


class ConfigAndCatalogApiTest(ApiTestCase):
    def test_config_reports_the_active_provider(self):
        status, body = self.get_json("/api/fabric-studio/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["provider"], "mock")
        self.assertTrue(body["mockMode"])
        self.assertIn("stageLabels", body)

    def test_fabric_list_includes_facets(self):
        status, body = self.get_json("/api/fabrics")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)
        self.assertIn("facets", body)
        item = body["items"][0]
        for key in ("id", "name", "category", "patternType", "thumbnailUrl", "primaryColors"):
            self.assertIn(key, item)

    def test_fabric_search_filters(self):
        _status, body = self.get_json("/api/fabrics?search=zzz")
        self.assertEqual(body["total"], 0)

    def test_missing_fabric_returns_a_friendly_404(self):
        status, body = self.get_json("/api/fabrics/nope")
        self.assertEqual(status, 404)
        self.assertIn("couldn't find", body["message"])

    def test_outfit_list(self):
        status, body = self.get_json("/api/outfits")
        self.assertEqual(status, 200)
        self.assertEqual(body["items"][0]["templateId"], "modern-senator")

    def test_media_is_served_and_traversal_blocked(self):
        url = self.fabric["processed"]["thumbnailUrl"]
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertIn(self.client.get("/media/../fabric_catalog.json").status_code, (301, 404))


class PhotoAndPreviewApiTest(ApiTestCase):
    def test_photo_validation_reports_warnings(self):
        status, body = self.post_json("/api/fabric-studio/validate-photo",
                                      {"personImage": context.person_data_url()})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("metrics", body)

    def test_bad_photo_is_rejected_with_a_safe_message(self):
        status, body = self.post_json("/api/fabric-studio/validate-photo",
                                      {"personImage": context.person_data_url(width=150, height=200)})
        self.assertEqual(status, 400)
        self.assertIn("small", body["message"])

    def test_non_image_payload_is_rejected(self):
        status, body = self.post_json("/api/fabric-studio/validate-photo",
                                      {"personImage": "data:text/plain;base64,aGk="})
        self.assertEqual(status, 400)
        self.assertIn("message", body)

    def test_preview_composes_the_garment(self):
        status, body = self.get_json(
            "/api/fabric-studio/preview?fabricId=fab_api&outfitId=out_api")
        self.assertEqual(status, 200)
        self.assertTrue(body["garmentImageUrl"].startswith("/media/fabrics/garments/"))
        self.assertEqual(self.client.get(body["garmentImageUrl"]).status_code, 200)


class GenerationApiTest(ApiTestCase):
    def _wait_for(self, generation_id, client_id="testclient1", timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _status, body = self.get_json("/api/fabric-studio/generations/" + generation_id,
                                          client_id=client_id)
            if body["status"] in ("completed", "failed"):
                return body
            time.sleep(0.2)
        self.fail("generation %s did not finish" % generation_id)

    def test_end_to_end_generation(self):
        status, body = self.post_json("/api/fabric-studio/generate", {
            "personImage": context.person_data_url(),
            "fabricId": "fab_api",
            "outfitId": "out_api",
            "mode": "fast",
        })
        self.assertEqual(status, 202)
        self.assertIn("generationId", body)
        self.assertTrue(body["stageLabel"])

        final = self._wait_for(body["generationId"])
        self.assertEqual(final["status"], "completed")
        self.assertTrue(final["resultImageUrl"])
        self.assertEqual(self.client.get(final["resultImageUrl"]).status_code, 200)

        record = GENERATION_STORE.get(body["generationId"])
        self.assertEqual(record["provider"], "mock")
        self.assertIn("totalMs", record["timings"])
        self.assertIn("garmentImageUrl", record["metadata"])

    def test_design_mode_records_the_prompt(self):
        _status, body = self.post_json("/api/fabric-studio/generate", {
            "personImage": context.person_data_url(),
            "fabricId": "fab_api", "outfitId": "out_api",
            "mode": "design", "prompt": "mandarin collar with embroidery",
        })
        self._wait_for(body["generationId"])
        record = GENERATION_STORE.get(body["generationId"])
        self.assertEqual(record["mode"], "design")
        self.assertIn("mandarin collar", record["prompt"])

    def test_fast_mode_drops_any_prompt(self):
        _status, body = self.post_json("/api/fabric-studio/generate", {
            "personImage": context.person_data_url(),
            "fabricId": "fab_api", "outfitId": "out_api",
            "mode": "fast", "prompt": "ignore me",
        })
        self._wait_for(body["generationId"])
        self.assertEqual(GENERATION_STORE.get(body["generationId"])["prompt"], "")

    def test_missing_inputs_are_rejected(self):
        cases = [
            ({}, "photo"),
            ({"personImage": context.person_data_url()}, "fabric"),
            ({"personImage": context.person_data_url(), "fabricId": "fab_api"}, "outfit"),
        ]
        for payload, fragment in cases:
            with self.subTest(payload=sorted(payload)):
                status, body = self.post_json("/api/fabric-studio/generate", payload)
                self.assertEqual(status, 400)
                self.assertIn(fragment, body["message"])

    def test_unknown_fabric_returns_404(self):
        status, body = self.post_json("/api/fabric-studio/generate", {
            "personImage": context.person_data_url(), "fabricId": "nope", "outfitId": "out_api"})
        self.assertEqual(status, 404)

    def test_history_is_scoped_to_the_client(self):
        _status, body = self.post_json("/api/fabric-studio/generate", {
            "personImage": context.person_data_url(),
            "fabricId": "fab_api", "outfitId": "out_api"}, client_id="clientone1")
        self._wait_for(body["generationId"], client_id="clientone1")

        _status, mine = self.get_json("/api/fabric-studio/generations", client_id="clientone1")
        self.assertEqual(len(mine["items"]), 1)

        _status, theirs = self.get_json("/api/fabric-studio/generations", client_id="clienttwo2")
        self.assertEqual(theirs["items"], [])

        status, _body = self.get_json("/api/fabric-studio/generations/" + body["generationId"],
                                      client_id="clienttwo2")
        self.assertEqual(status, 404)


class AdminApiTest(ApiTestCase):
    def test_admin_endpoints_require_auth(self):
        for path in ("/api/admin/fabrics", "/api/admin/outfits", "/api/admin/fabric-imports",
                     "/api/admin/fabric-studio/status"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_admin_status(self):
        response = self.client.get("/api/admin/fabric-studio/status", headers=ADMIN_HEADER)
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("templates", body)
        self.assertIn("generations", body)
        self.assertEqual(body["provider"]["provider"], "mock")

    def test_admin_can_deactivate_and_reactivate_a_fabric(self):
        response = self.client.delete("/api/admin/fabrics/fab_api", headers=ADMIN_HEADER)
        self.assertFalse(response.get_json()["isActive"])
        _status, body = self.get_json("/api/fabrics")
        self.assertEqual(body["total"], 0)

        response = self.client.post("/api/admin/fabrics/fab_api/activate", headers=ADMIN_HEADER)
        self.assertTrue(response.get_json()["isActive"])

    def test_admin_can_create_an_outfit(self):
        response = self.client.post("/api/admin/outfits", headers=ADMIN_HEADER, data={
            "name": "Test Kaftan", "template_id": "classic-kaftan",
            "category": "Men", "garment_type": "one-pieces",
        })
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["templateId"], "classic-kaftan")
        self.assertTrue(body["previewImageUrl"])
        self.assertEqual(self.client.get(body["previewImageUrl"]).status_code, 200)

    def test_admin_outfit_validation_errors_are_reported(self):
        response = self.client.post("/api/admin/outfits", headers=ADMIN_HEADER,
                                    data={"name": "Bad", "template_id": "nope"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("template", response.get_json()["message"])


if __name__ == "__main__":
    unittest.main()


class GarmentStrategyTest(ApiTestCase):
    """Which image reaches the provider, and what the prompt says about it."""

    def _capture_request(self, payload):
        """Run a generation and return the TryOnRequest the provider received."""
        from fabric_studio.virtual_tryon import get_provider
        provider = get_provider()
        captured = {}
        original = provider.generate

        def spy(request):
            captured["request"] = request
            return original(request)

        provider.generate = spy
        self.addCleanup(setattr, provider, "generate", original)

        base = {"personImage": context.person_data_url(),
                "fabricId": "fab_api", "outfitId": "out_api"}
        base.update(payload)
        status, body = self.post_json("/api/fabric-studio/generate", base)
        self.assertEqual(status, 202)
        deadline = time.time() + 20
        while time.time() < deadline:
            _s, polled = self.get_json("/api/fabric-studio/generations/" + body["generationId"])
            if polled["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        return captured.get("request"), polled

    def test_default_sends_the_template_filled_with_the_fabric(self):
        """person + garment template + fabric swatch -> one flat-lay."""
        request, final = self._capture_request({})
        self.assertEqual(final["status"], "completed")
        self.assertEqual(request.strategy, "composite")

        fabric = catalog.get_fabric("fab_api")
        outfit = catalog.get_outfit("out_api")
        composed = garment_composer.compose(fabric, outfit)
        expected = imaging.to_data_url(
            storage.media_path(composed["path"]).read_bytes(), "JPEG")
        self.assertEqual(request.garment_image, expected)

        # It is already the garment in the right cloth, so the prompt asks for
        # fidelity rather than re-describing the cut from scratch.
        self.assertIn("already made in the customer's chosen fabric", request.prompt)
        self.assertNotIn("flat length of fabric", request.prompt)

    def test_fabric_strategy_sends_the_bare_swatch(self):
        os.environ["VTON_GARMENT_STRATEGY"] = "fabric"
        self.addCleanup(os.environ.pop, "VTON_GARMENT_STRATEGY", None)
        request, final = self._capture_request({})
        self.assertEqual(final["status"], "completed")
        self.assertEqual(request.strategy, "fabric")
        fabric = catalog.get_fabric("fab_api")
        expected = imaging.to_data_url(
            storage.media_path(fabric["processed"]["normalizedPath"]).read_bytes(), "JPEG")
        self.assertEqual(request.garment_image, expected)
        self.assertIn("flat length of fabric", request.prompt)

    def test_design_mode_folds_the_customer_brief_into_the_prompt(self):
        request, _final = self._capture_request(
            {"mode": "design", "prompt": "mandarin collar with gold piping"})
        self.assertIn("Mandarin collar with gold piping.", request.prompt)
        self.assertEqual(request.mode, "quality")

    def test_the_built_prompt_is_recorded_on_the_generation(self):
        _request, final = self._capture_request({})
        record = GENERATION_STORE.get(final["generationId"])
        self.assertEqual(record["metadata"]["strategy"], "composite")
        self.assertIn("already made in the customer's chosen fabric",
                      record["metadata"]["builtPrompt"])
