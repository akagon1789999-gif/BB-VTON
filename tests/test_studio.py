"""The studio: two uploads, a composed instruction, one call to tryon-max.

Nothing here reaches FASHN. `fashn.run`, `fashn.status` and `fashn.credits`
are stubbed, so these tests assert the payload we *would* send — which is the
part that costs money to get wrong.
"""
import io
import json
import unittest

from flask import Flask
from PIL import Image

from . import context  # noqa: F401  (sets DATA_DIR first)
from studio import credits, errors, fashn, images, prompts, register, storage
from studio.routes import read_params, resolve_image


def png_bytes(width=800, height=1200, color=(120, 90, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class PromptTest(unittest.TestCase):
    """A template must read correctly for the piece it names, and only that piece."""

    def test_a_dress_prompt_never_mentions_trousers(self):
        prompt = prompts.fabric_prompt("dress", "strict", "full-set")
        self.assertIn("the same dress", prompt)
        self.assertIn("headwrap", prompt)
        self.assertNotIn("trouser", prompt)

    def test_an_agbada_prompt_names_its_own_layers(self):
        prompt = prompts.fabric_prompt("agbada", "strict", "full-set")
        for layer in ("outer agbada", "inner buba", "sokoto trousers", "fila cap"):
            self.assertIn(layer, prompt)

    def test_full_set_remakes_every_layer(self):
        prompt = prompts.fabric_prompt("agbada", "strict", "full-set")
        self.assertIn("COORDINATED SET", prompt)
        self.assertIn("No garment element keeps the colour it had", prompt)

    def test_outer_only_leaves_the_rest_alone(self):
        prompt = prompts.fabric_prompt("agbada", "strict", "outer-only")
        self.assertIn("Change the main garment only", prompt)
        self.assertIn("stay exactly as they appear in the reference photo", prompt)
        self.assertNotIn("COORDINATED SET", prompt)

    def test_the_designer_brief_ignores_coverage(self):
        # The coordinated brief is inherently full-set, so both scopes agree.
        self.assertEqual(
            prompts.fabric_prompt("suit", "coordinated", "full-set"),
            prompts.fabric_prompt("suit", "coordinated", "outer-only"),
        )
        self.assertFalse(prompts.scope_applies("coordinated"))

    def test_concise_is_one_sentence_shorter_than_the_directive(self):
        concise = prompts.fabric_prompt("kaftan", "concise", "outer-only")
        strict = prompts.fabric_prompt("kaftan", "strict", "outer-only")
        self.assertLess(len(concise), len(strict) / 4)

    def test_an_unknown_template_falls_back_to_the_default(self):
        self.assertEqual(read_params({"fabricTemplate": "haiku"})["fabricTemplate"], "universal")

    def test_an_unknown_garment_falls_back_to_the_custom_vocabulary(self):
        self.assertIn("outfit", prompts.fabric_prompt("balaclava", "strict", "full-set"))

    def test_the_edit_directive_frames_it_as_a_retexture(self):
        prompt = prompts.fabric_edit_prompt("senator", "strict", "full-set")
        self.assertTrue(prompt.startswith("Retexture the senator top and trousers"))


class UniversalPromptTest(unittest.TestCase):
    """The shop's own brief: garment-agnostic, and it ignores both axes."""

    def test_it_is_the_default(self):
        self.assertEqual(read_params({})["fabricTemplate"], "universal")
        self.assertEqual(prompts.fabric_prompt("agbada"), prompts.universal_prompt())

    def test_it_reads_the_same_for_every_garment_without_its_own_brief(self):
        for garment in ("agbada", "kaftan", "suit", "shirt"):
            self.assertFalse(prompts.has_garment_brief(garment))
            self.assertEqual(prompts.fabric_prompt(garment, "universal"),
                             prompts.UNIVERSAL_PROMPT)

    def test_coverage_does_not_change_it(self):
        self.assertEqual(prompts.fabric_prompt("dress", "universal", "full-set"),
                         prompts.fabric_prompt("dress", "universal", "outer-only"))

    def test_coverage_never_applies_but_garment_type_always_does(self):
        self.assertFalse(prompts.scope_applies("universal"))
        self.assertTrue(prompts.scope_applies("concise"))
        # Universal reads the garment type to choose a brief; the composed
        # templates read it to interpolate their vocabulary.
        for template in prompts.TEMPLATE_VALUES:
            self.assertTrue(prompts.garment_applies(template), template)

    def test_it_carries_the_clauses_the_failures_needed(self):
        prompt = prompts.universal_prompt()
        # The run that substituted a different Ankara:
        self.assertIn("Do not substitute it with a generic fabric.", prompt)
        self.assertIn("Do not replace the pattern with an AI-generated approximation.", prompt)
        # The run that changed her face and the backdrop:
        self.assertIn("Preserve the same person from the reference image.", prompt)
        self.assertIn("Do not turn the image into a different photoshoot.", prompt)
        # Leftover reference colours:
        self.assertIn("Do not leave accidental remnants of the original garment colors.", prompt)

    def test_every_template_declares_its_applicability(self):
        for template in prompts.FABRIC_TEMPLATES:
            self.assertIn("scopeApplies", template)
            self.assertIn("garmentApplies", template)
            self.assertEqual(template["scopeApplies"], prompts.scope_applies(template["value"]))
            self.assertEqual(template["garmentApplies"], prompts.garment_applies(template["value"]))

    def test_the_edit_strategy_uses_it_unchanged(self):
        self.assertEqual(prompts.fabric_edit_prompt("kaftan", "universal"),
                         prompts.UNIVERSAL_PROMPT)
        self.assertEqual(prompts.fabric_edit_prompt("dress", "universal"),
                         prompts.DRESS_MODE_PROMPT)


class DressModeTest(unittest.TestCase):
    """A dress fails differently: the model reads bodice and skirt as two
    garments and re-textures one. The dress brief exists to stop that."""

    def test_picking_dress_selects_the_dress_brief(self):
        self.assertTrue(prompts.has_garment_brief("dress"))
        self.assertEqual(prompts.fabric_prompt("dress", "universal"),
                         prompts.DRESS_MODE_PROMPT)
        self.assertEqual(read_params({"garmentType": "dress"})["garmentType"], "dress")

    def test_it_forbids_splitting_the_dress(self):
        """The first failure: bodice and skirt read as two garments, one
        re-textured, the other left in the reference print."""
        prompt = prompts.DRESS_MODE_PROMPT
        self.assertIn("convert the dress into a two-piece", prompt)
        self.assertIn("The reference garment's construction is LOCKED.", prompt)

    def test_it_forbids_flattening_the_material_zones(self):
        """The opposite failure: told to cover everything, the model turns a
        solid-plus-lace-plus-print dress into one uniform print."""
        prompt = prompts.DRESS_MODE_PROMPT
        self.assertIn("MATERIAL ZONES MUST BE PRESERVED", prompt)
        self.assertIn("Do not flatten multiple materials into one material.", prompt)
        self.assertIn("Do NOT assume that every visible part of the dress must become "
                      "the uploaded fabric.", prompt)
        self.assertIn("material hierarchy", prompt)

    def test_it_keeps_sheer_sections_sheer(self):
        prompt = prompts.DRESS_MODE_PROMPT
        self.assertIn("LACE AND TRANSPARENT MATERIAL LOCK", prompt)
        self.assertIn("DO NOT convert these areas into opaque printed fabric.", prompt)
        self.assertIn("KEEP LACE AS LACE.", prompt)
        self.assertIn("KEEP SHEER AS SHEER.", prompt)

    def test_it_recolours_solid_sections_from_the_fabric_palette(self):
        prompt = prompts.DRESS_MODE_PROMPT
        self.assertIn("Do not replace a solid section with a printed section", prompt)
        self.assertIn("preserve the original solid section's location and construction", prompt)

    def test_coverage_still_does_not_apply(self):
        self.assertEqual(prompts.fabric_prompt("dress", "universal", "full-set"),
                         prompts.fabric_prompt("dress", "universal", "outer-only"))

    def test_the_other_templates_are_unaffected_by_it(self):
        for template in ("strict", "coordinated", "concise"):
            self.assertNotEqual(prompts.fabric_prompt("dress", template),
                                prompts.DRESS_MODE_PROMPT)
        # The composed dress vocabulary still works.
        self.assertIn("the same dress", prompts.fabric_prompt("dress", "strict"))


class CreditsTest(unittest.TestCase):
    def test_the_matrix_matches_fashn(self):
        # FASHN's published tryon-max table, exactly.
        self.assertEqual(credits.credit_cost("balanced", "1k", 1), 2)
        self.assertEqual(credits.credit_cost("balanced", "2k", 1), 3)
        self.assertEqual(credits.credit_cost("balanced", "4k", 1), 4)
        self.assertEqual(credits.credit_cost("quality", "1k", 1), 3)
        self.assertEqual(credits.credit_cost("quality", "2k", 1), 4)
        self.assertEqual(credits.credit_cost("quality", "4k", 1), 5)

    def test_there_is_no_fast_mode_on_tryon_max(self):
        """`fast` is not a tryon-max mode. Offering it quotes 1 credit for a
        job the API bills as balanced, so it normalises rather than passing."""
        self.assertNotIn("fast", credits.MATRIX)
        self.assertEqual(credits.GENERATION_MODES, ("balanced", "quality"))
        self.assertEqual(credits.normalize_mode("fast"), "balanced")
        self.assertEqual(credits.credit_cost("fast", "1k", 1), 2)

    def test_no_preset_quotes_a_price_it_cannot_charge(self):
        for preset in credits.QUALITY_PRESETS:
            self.assertIn(preset["generationMode"], credits.MATRIX)
            cost = credits.credit_cost(preset["generationMode"], preset["resolution"], 1)
            self.assertIn("%d cr" % cost, preset["note"])

    def test_image_count_multiplies_and_is_clamped(self):
        self.assertEqual(credits.credit_cost("balanced", "2k", 3), 9)
        self.assertEqual(credits.credit_cost("balanced", "2k", 99), 12)
        self.assertEqual(credits.credit_cost("balanced", "2k", 0), 3)

    def test_unknown_settings_fall_back_rather_than_raising(self):
        self.assertEqual(credits.credit_cost("turbo", "8k", 1), 2)

    def test_presets_round_trip(self):
        self.assertEqual(credits.match_preset("balanced", "2k"), "standard")
        self.assertIsNone(credits.match_preset("fast", "4k"))


class ImageTest(unittest.TestCase):
    def test_it_downscales_past_the_long_edge_ceiling(self):
        result = images.preprocess(png_bytes(4000, 3000), "wide.png")
        self.assertEqual(max(result["width"], result["height"]), images.MAX_LONG_EDGE)
        self.assertEqual(result["contentType"], "image/jpeg")

    def test_lossless_keeps_png(self):
        result = images.preprocess(png_bytes(400, 600), "small.png", lossless=True)
        self.assertEqual(result["contentType"], "image/png")
        self.assertEqual(result["extension"], "png")

    def test_a_crop_rect_is_applied_in_normalised_space(self):
        result = images.preprocess(
            png_bytes(1000, 1000), "square.png",
            crop={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5})
        self.assertEqual((result["width"], result["height"]), (500, 500))

    def test_it_refuses_a_file_past_the_size_limit(self):
        with self.assertRaises(errors.StudioError) as caught:
            images.validate_file("huge.jpg", images.MAX_FILE_BYTES + 1, "image/jpeg")
        self.assertEqual(caught.exception.code, errors.INPUT_VALIDATION)
        self.assertIn("30 MB", caught.exception.message)

    def test_it_refuses_an_unsupported_type(self):
        with self.assertRaises(errors.StudioError):
            images.validate_file("scan.tiff", 1000, "image/tiff")

    def test_it_refuses_a_sliver(self):
        with self.assertRaises(errors.StudioError) as caught:
            images.preprocess(png_bytes(2000, 40), "sliver.png")
        self.assertIn("aspect ratio", caught.exception.message)

    def test_it_refuses_bytes_that_are_not_an_image(self):
        with self.assertRaises(errors.StudioError):
            images.preprocess(b"not an image at all", "nope.png")

    def test_the_fabric_hint_fires_on_a_swatch_too_small_to_scale(self):
        self.assertIsNone(images.fabric_hint(960, 1280))
        self.assertIsNone(images.fabric_hint(800, 600))
        hint = images.fabric_hint(241, 424)
        self.assertIn("241 x 424", hint)
        self.assertIn("approximated rather than reproduced", hint)

    def test_the_aspect_hint_only_fires_away_from_2_to_3(self):
        self.assertIsNone(images.aspect_hint(800, 1200))
        self.assertIn("wider", images.aspect_hint(1200, 800))
        self.assertIn("taller", images.aspect_hint(400, 1200))


class StorageTest(unittest.TestCase):
    def test_it_round_trips_bytes_and_their_type(self):
        key = storage.new_key("product", "jpg")
        storage.put(key, b"cloth", "image/jpeg")
        stored = storage.get(key)
        self.assertEqual(stored["body"], b"cloth")
        self.assertEqual(stored["contentType"], "image/jpeg")
        storage.delete(key)
        self.assertIsNone(storage.get(key))

    def test_a_key_cannot_escape_the_tree(self):
        self.assertIsNone(storage.get("../../../etc/passwd"))

    def test_localhost_is_not_publicly_reachable(self):
        import os
        previous = os.environ.get("APP_URL")
        try:
            os.environ["APP_URL"] = "http://localhost:8000"
            self.assertFalse(storage.is_publicly_reachable())
            os.environ["APP_URL"] = "https://bb.example.com"
            self.assertTrue(storage.is_publicly_reachable())
        finally:
            if previous is None:
                os.environ.pop("APP_URL", None)
            else:
                os.environ["APP_URL"] = previous


class ParamsTest(unittest.TestCase):
    def test_it_completes_and_clamps_whatever_the_browser_sent(self):
        params = read_params({"garmentType": "nonsense", "seed": 10 ** 12,
                              "numImages": 99, "resolution": "8k",
                              "generationMode": "turbo", "outputFormat": "gif"})
        self.assertEqual(params["garmentType"], "agbada")
        self.assertEqual(params["seed"], 4294967295)
        self.assertEqual(params["numImages"], 4)
        self.assertEqual(params["resolution"], "1k")
        self.assertEqual(params["generationMode"], "balanced")
        self.assertEqual(params["outputFormat"], "png")

    def test_an_empty_body_still_yields_a_complete_set(self):
        params = read_params(None)
        self.assertEqual(params["seed"], 42)
        self.assertEqual(params["fabricScope"], "full-set")

    def test_a_missing_image_names_the_slot_it_wants(self):
        with self.assertRaises(errors.StudioError) as caught:
            resolve_image(None, "fabric swatch", False)
        self.assertIn("fabric swatch", caught.exception.message)


class FashnErrorMappingTest(unittest.TestCase):
    """FASHN has several error shapes. The UI only ever sees one."""

    def test_401_becomes_an_actionable_key_problem(self):
        error = fashn.map_api_error(401, {})
        self.assertEqual(error.code, errors.UNAUTHORIZED)
        self.assertIn("FASHN_API_KEY", error.fix)

    def test_429_is_retryable_and_carries_the_delay(self):
        error = fashn.map_api_error(429, {}, retry_after=11)
        self.assertTrue(error.retryable)
        self.assertEqual(error.retry_after, 11)

    def test_a_credit_message_is_recognised_wherever_it_appears(self):
        error = fashn.map_api_error(400, {"error": {"message": "insufficient credits"}})
        self.assertEqual(error.code, errors.INSUFFICIENT_CREDITS)

    def test_validation_errors_explain_the_input_limits(self):
        error = fashn.map_api_error(422, {"error": {"name": "InputValidationError"}})
        self.assertIn("16:1", error.fix)

    def test_5xx_is_retryable(self):
        self.assertTrue(fashn.map_api_error(503, {}).retryable)


class RoutesTest(unittest.TestCase):
    """The HTTP contract the browser is written against."""

    @classmethod
    def setUpClass(cls):
        app = Flask(__name__)
        register(app)
        cls.client = app.test_client()

    def setUp(self):
        self.sent = {}

        def fake_run(model_name, inputs):
            self.sent["model"] = model_name
            self.sent["inputs"] = inputs
            return "pred_test"

        self._real = (fashn.run, fashn.credits, fashn.status)
        fashn.run = fake_run
        fashn.credits = lambda: {"total": 500, "subscription": 500, "onDemand": 0}
        fashn.status = lambda pid: {"id": pid, "status": "completed",
                                    "output": ["https://cdn/x.png"], "error": None}

    def tearDown(self):
        fashn.run, fashn.credits, fashn.status = self._real

    def upload(self, slot="product", privacy=False, **extra):
        data = {"file": (io.BytesIO(png_bytes()), "cloth.png"), "slot": slot,
                "privacy": "true" if privacy else "false"}
        data.update(extra)
        return self.client.post("/api/studio/upload", data=data,
                                content_type="multipart/form-data")

    def test_config_ships_the_vocabulary_the_rail_renders(self):
        payload = self.client.get("/api/studio/config").get_json()
        self.assertEqual(len(payload["garmentTypes"]), 8)
        briefed = [g["value"] for g in payload["garmentTypes"] if g["hasBrief"]]
        self.assertEqual(briefed, ["dress"])
        self.assertEqual([p["id"] for p in payload["qualityPresets"]],
                         ["draft", "standard", "final"])
        self.assertIn("maxFileBytes", payload["limits"])

    def test_prompt_endpoint_flags_a_dedicated_brief(self):
        dress = self.client.get(
            "/api/studio/prompt?garment=dress&template=universal").get_json()
        self.assertTrue(dress["dedicatedBrief"])
        # Assert the identity, not the title — the brief gets revised.
        self.assertEqual(dress["prompt"], prompts.DRESS_MODE_PROMPT)
        self.assertNotEqual(dress["prompt"], prompts.UNIVERSAL_PROMPT)

        agbada = self.client.get(
            "/api/studio/prompt?garment=agbada&template=universal").get_json()
        self.assertFalse(agbada["dedicatedBrief"])

        # Only the universal template dispatches on garment briefs.
        strict = self.client.get(
            "/api/studio/prompt?garment=dress&template=strict").get_json()
        self.assertFalse(strict["dedicatedBrief"])

    def test_prompt_endpoint_composes_from_the_three_axes(self):
        payload = self.client.get(
            "/api/studio/prompt?garment=dress&template=strict&scope=outer-only").get_json()
        self.assertIn("the same dress", payload["prompt"])
        self.assertTrue(payload["scopeApplies"])

    def test_prompt_endpoint_ignores_nonsense_arguments(self):
        payload = self.client.get(
            "/api/studio/prompt?garment=x&template=y&scope=z").get_json()
        # Falls back to the default template and the default garment, which
        # between them give the general universal brief.
        self.assertEqual(payload["prompt"], prompts.UNIVERSAL_PROMPT)
        self.assertFalse(payload["scopeApplies"])
        self.assertTrue(payload["garmentApplies"])
        self.assertFalse(payload["dedicatedBrief"])

    def test_prompt_endpoint_reports_applicability_per_template(self):
        strict = self.client.get(
            "/api/studio/prompt?garment=agbada&template=strict&scope=full-set").get_json()
        self.assertIn("agbada", strict["prompt"])
        self.assertTrue(strict["scopeApplies"])
        self.assertTrue(strict["garmentApplies"])

    def test_each_slot_gets_the_advice_that_suits_it(self):
        """Cropping fixes a wide photo; it would only shrink a small swatch."""
        tiny = self.client.post("/api/studio/upload", data={
            "file": (io.BytesIO(png_bytes(240, 420)), "swatch.png"),
            "slot": "product", "privacy": "false",
        }, content_type="multipart/form-data").get_json()
        self.assertEqual(tiny["hintKind"], "resolution")
        self.assertIn("240 x 420", tiny["hint"])

        wide = self.client.post("/api/studio/upload", data={
            "file": (io.BytesIO(png_bytes(1200, 800)), "person.png"),
            "slot": "model", "privacy": "false",
        }, content_type="multipart/form-data").get_json()
        self.assertEqual(wide["hintKind"], "aspect")
        self.assertIn("wider than 2:3", wide["hint"])

        # A good swatch says nothing at all.
        fine = self.upload("product").get_json()
        self.assertIsNone(fine["hint"])
        self.assertIsNone(fine["hintKind"])

    def test_upload_returns_something_the_browser_can_render(self):
        payload = self.upload(slot="model").get_json()
        self.assertEqual(payload["contentType"], "image/jpeg")
        self.assertEqual((payload["width"], payload["height"]), (800, 1200))
        self.assertTrue(payload["previewUrl"].startswith("/api/studio/files/"))
        served = self.client.get(payload["previewUrl"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["Content-Type"], "image/jpeg")

    def test_privacy_mode_keeps_the_bytes_off_our_disk(self):
        payload = self.upload(privacy=True).get_json()
        self.assertTrue(payload["dataUri"].startswith("data:image/png;base64,"))
        self.assertEqual(payload["url"], "")
        self.assertNotIn("key", payload)

    def test_a_malformed_crop_is_ignored_rather_than_fatal(self):
        response = self.upload(crop="{not json")
        self.assertEqual(response.status_code, 200)

    def test_upload_with_no_file_says_so(self):
        response = self.client.post("/api/studio/upload", data={"slot": "product"},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], errors.INPUT_VALIDATION)

    def test_generate_nests_every_parameter_inside_inputs(self):
        product = self.upload("product").get_json()
        model = self.upload("model").get_json()
        response = self.client.post("/api/studio/generate", json={
            "operation": "tryon",
            "params": {"garmentType": "kaftan", "fabricTemplate": "strict",
                       "fabricScope": "full-set", "resolution": "2k",
                       "generationMode": "balanced", "seed": 7, "numImages": 2,
                       "outputFormat": "jpeg", "privacy": False},
            "product": {"key": product["key"], "url": product["url"], "fileName": "c.png"},
            "model": {"key": model["key"], "url": model["url"], "fileName": "m.png"},
        })
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["modelName"], "tryon-max")
        self.assertEqual(payload["creditCost"], 6)  # balanced/2k = 3, twice

        self.assertEqual(self.sent["model"], "tryon-max")
        inputs = self.sent["inputs"]
        # Omitting generation_mode silently bills as `balanced`, so it is always sent.
        self.assertEqual(inputs["generation_mode"], "balanced")
        self.assertEqual(inputs["resolution"], "2k")
        self.assertEqual(inputs["seed"], 7)
        self.assertEqual(inputs["num_images"], 2)
        self.assertIn("kaftan", inputs["prompt"])

    def test_a_hand_written_instruction_wins(self):
        product = self.upload("product").get_json()
        model = self.upload("model").get_json()
        self.client.post("/api/studio/generate", json={
            "params": {"prompt": "  make it green  ", "promptOverridden": True},
            "product": {"key": product["key"], "fileName": "c.png"},
            "model": {"key": model["key"], "fileName": "m.png"},
        })
        self.assertEqual(self.sent["inputs"]["prompt"], "make it green")

    def test_generate_without_a_fabric_names_the_missing_slot(self):
        response = self.client.post("/api/studio/generate", json={"params": {}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("fabric swatch", response.get_json()["message"])

    def test_generate_with_no_parameters_at_all(self):
        response = self.client.post("/api/studio/generate", json={})
        self.assertEqual(response.status_code, 400)

    def test_it_refuses_to_start_a_job_it_knows_is_unaffordable(self):
        fashn.credits = lambda: {"total": 1, "subscription": 1, "onDemand": 0}
        product = self.upload("product").get_json()
        model = self.upload("model").get_json()
        response = self.client.post("/api/studio/generate", json={
            "params": {"generationMode": "quality", "resolution": "4k", "numImages": 4},
            "product": {"key": product["key"], "fileName": "c.png"},
            "model": {"key": model["key"], "fileName": "m.png"},
        })
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.get_json()["code"], errors.INSUFFICIENT_CREDITS)
        self.assertIn("19 short", response.get_json()["message"])

    def test_a_flaky_balance_lookup_never_blocks_a_generation(self):
        def broken():
            raise errors.StudioError(errors.NETWORK_ERROR, "down", http_status=502)

        fashn.credits = broken
        product = self.upload("product").get_json()
        model = self.upload("model").get_json()
        response = self.client.post("/api/studio/generate", json={
            "params": {},
            "product": {"key": product["key"], "fileName": "c.png"},
            "model": {"key": model["key"], "fileName": "m.png"},
        })
        self.assertEqual(response.status_code, 200)

    def test_post_processing_maps_onto_its_own_model(self):
        cases = {
            "upscale": "reframe",
            "image-to-video": "image-to-video",
            "swap-face": "model-swap",
            "background-change": "background-change",
            "background-remove": "background-remove",
        }
        for operation, model_name in cases.items():
            response = self.client.post("/api/studio/generate", json={
                "operation": operation, "params": {},
                "source": "https://cdn/x.png", "options": {"duration": 10}})
            self.assertEqual(response.status_code, 200, operation)
            self.assertEqual(self.sent["model"], model_name, operation)
            # Post-processing always runs one image, whatever numImages says.
            self.assertEqual(response.get_json()["creditCost"], 2, operation)

    def test_post_processing_needs_something_to_work_on(self):
        response = self.client.post("/api/studio/generate",
                                    json={"operation": "upscale", "params": {}})
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_operation_is_refused(self):
        response = self.client.post("/api/studio/generate", json={
            "operation": "colourise", "params": {}, "source": "https://cdn/x.png"})
        self.assertEqual(response.status_code, 400)

    def test_status_passes_the_result_through(self):
        payload = self.client.get("/api/studio/status/pred_test").get_json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["output"], ["https://cdn/x.png"])

    def test_a_status_failure_keeps_the_prediction_id(self):
        def broken(pid):
            raise errors.StudioError(errors.NETWORK_ERROR, "dropped",
                                     http_status=502, retryable=True)

        fashn.status = broken
        response = self.client.get("/api/studio/status/pred_test")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["predictionId"], "pred_test")

    def test_a_missing_file_is_a_clean_404(self):
        response = self.client.get("/api/studio/files/product/nope.jpg")
        self.assertEqual(response.status_code, 404)


class EngineTest(unittest.TestCase):
    """tryon-max replaces one garment region; edit rewrites the whole picture.

    A two-piece outfit whose skirt must also change needs edit, so the engine
    is a per-run choice rather than a deploy-wide environment variable.
    """

    @classmethod
    def setUpClass(cls):
        app = Flask(__name__)
        register(app)
        cls.client = app.test_client()

    def setUp(self):
        self.sent = {}

        def fake_run(model_name, inputs):
            self.sent["model"] = model_name
            self.sent["inputs"] = inputs
            return "pred_test"

        self._real = (fashn.run, fashn.credits)
        fashn.run = fake_run
        fashn.credits = lambda: {"total": 500, "subscription": 500, "onDemand": 0}

    def tearDown(self):
        fashn.run, fashn.credits = self._real

    def upload(self, slot):
        return self.client.post("/api/studio/upload", data={
            "file": (io.BytesIO(png_bytes()), "x.png"), "slot": slot, "privacy": "false",
        }, content_type="multipart/form-data").get_json()

    def generate(self, engine=None):
        params = {"garmentType": "two-piece"}
        if engine:
            params["engine"] = engine
        product = self.upload("product")
        model = self.upload("model")
        return self.client.post("/api/studio/generate", json={
            "params": params,
            "product": {"key": product["key"], "fileName": "c.png"},
            "model": {"key": model["key"], "fileName": "m.png"},
        })

    def test_it_defaults_to_tryon_max(self):
        self.assertEqual(read_params({})["engine"], "tryon-max")
        self.generate()
        self.assertEqual(self.sent["model"], "tryon-max")

    def test_an_unknown_engine_falls_back(self):
        self.assertEqual(read_params({"engine": "diffusion"})["engine"], "tryon-max")

    def test_choosing_whole_outfit_runs_the_edit_endpoint(self):
        response = self.generate("edit")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["modelName"], "edit")
        self.assertEqual(self.sent["model"], "edit")

    def test_the_edit_endpoint_gets_the_fabric_as_image_context(self):
        """FASHN reads `image_context`. `reference_image` is not a parameter
        it knows, so sending that ran the edit with no fabric at all."""
        self.generate("edit")
        inputs = self.sent["inputs"]
        self.assertIn("image_context", inputs)
        self.assertNotIn("reference_image", inputs)
        # The person is the canvas, the swatch is the reference.
        self.assertTrue(inputs["image"].startswith("data:"))
        self.assertTrue(inputs["image_context"].startswith("data:"))

    def test_neither_engine_ever_sends_fast_on_the_wire(self):
        for engine in ("tryon-max", "edit"):
            self.client.post("/api/studio/generate", json={
                "params": {"generationMode": "fast", "engine": engine},
                "product": {"key": self.upload("product")["key"], "fileName": "c.png"},
                "model": {"key": self.upload("model")["key"], "fileName": "m.png"},
            })
            self.assertEqual(self.sent["inputs"]["generation_mode"], "balanced", engine)

    def test_config_advertises_both_engines(self):
        payload = self.client.get("/api/studio/config").get_json()
        self.assertEqual([e["value"] for e in payload["engines"]], ["tryon-max", "edit"])
        self.assertEqual(payload["defaultEngine"], "tryon-max")
        self.assertEqual(payload["generationModes"], ["balanced", "quality"])


class RenderableOutputTest(unittest.TestCase):
    """Privacy mode returns bare base64. The browser needs a data URI."""

    def test_bare_base64_becomes_a_data_uri(self):
        self.assertTrue(fashn._as_renderable_image("iVBORw0KGgo").startswith("data:image/png"))
        self.assertTrue(fashn._as_renderable_image("/9j/4AAQ").startswith("data:image/jpeg"))

    def test_urls_are_left_alone(self):
        self.assertEqual(fashn._as_renderable_image("https://cdn/x.png"), "https://cdn/x.png")
        self.assertEqual(fashn._as_renderable_image("data:image/png;base64,AA"),
                         "data:image/png;base64,AA")


if __name__ == "__main__":
    unittest.main()
