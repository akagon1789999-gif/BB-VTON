"""Provider abstraction: switching, input mapping, status and error mapping."""
import os
import unittest

from . import context
from fabric_studio import config
from fabric_studio.errors import ProviderConfigError, ProviderError, RateLimitError
from fabric_studio.virtual_tryon import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    TryOnRequest,
    available_providers,
    get_provider,
    reset_providers,
)
from fabric_studio.virtual_tryon.fashn_api_provider import FashnApiProvider
from fabric_studio.virtual_tryon.fashn_vton15_provider import FashnVton15Provider
from fabric_studio.virtual_tryon.mock_provider import MockProvider


class ProviderSwitchingTest(unittest.TestCase):
    def tearDown(self):
        os.environ["VTON_PROVIDER"] = "mock"
        reset_providers()

    def test_env_var_selects_the_provider(self):
        for name, expected in (("mock", "mock"), ("fashn_api", "fashn_api"), ("fashn_vton_15", "fashn_vton_15")):
            os.environ["VTON_PROVIDER"] = name
            reset_providers()
            self.assertEqual(get_provider().name, expected)

    def test_unknown_provider_is_rejected(self):
        os.environ["VTON_PROVIDER"] = "not_a_provider"
        reset_providers()
        with self.assertRaises(ProviderConfigError):
            get_provider()

    def test_all_providers_share_the_interface(self):
        for name in available_providers():
            os.environ["VTON_PROVIDER"] = name
            reset_providers()
            provider = get_provider()
            for method in ("generate", "get_status", "is_configured", "describe"):
                self.assertTrue(callable(getattr(provider, method)), "%s.%s" % (name, method))
            self.assertIn("provider", provider.describe())


class FashnInputMappingTest(unittest.TestCase):
    """The documented FASHN input names, per strategy. No invented parameters."""

    def setUp(self):
        self.provider = FashnApiProvider(api_key="test-key")

    def request(self, strategy="composite", mode="fast", prompt="Wear this exact garment.", **options):
        opts = {"strategy": strategy, "mode": mode, "prompt": prompt}
        opts.update(options)
        return TryOnRequest("PERSON", "GARMENT", {"category": "one-pieces"}, opts)

    def test_composite_is_the_default_and_goes_to_tryon_max(self):
        """person + garment template + fabric swatch -> tryon-max."""
        request = self.request()
        self.assertEqual(request.strategy, "composite")
        model = self.provider.model_for(request)
        self.assertEqual(model, config.vton_tryon_model())
        self.assertEqual(model, "tryon-max")
        inputs = self.provider.build_inputs(request, model)
        self.assertEqual(inputs["product_image"], "GARMENT")
        self.assertEqual(inputs["model_image"], "PERSON")
        self.assertIn("prompt", inputs)
        self.assertEqual(inputs["generation_mode"], "balanced")
        self.assertNotIn("garment_image", inputs)
        self.assertNotIn("category", inputs)

    def test_a_request_with_no_strategy_still_composites(self):
        request = TryOnRequest("PERSON", "GARMENT", {}, {"prompt": "Wear this."})
        self.assertEqual(request.strategy, "composite")
        self.assertEqual(self.provider.model_for(request), "tryon-max")

    def test_fabric_strategy_sends_the_bare_swatch_to_tryon_max(self):
        request = self.request(strategy="fabric", prompt="Tailor it into an agbada.")
        model = self.provider.model_for(request)
        self.assertEqual(model, "tryon-max")
        inputs = self.provider.build_inputs(request, model)
        self.assertEqual(inputs["product_image"], "GARMENT")
        self.assertIn("agbada", inputs["prompt"])

    def test_fabric_strategy_in_design_mode_asks_for_quality(self):
        inputs = self.provider.build_inputs(self.request(mode="quality"), "tryon-max")
        self.assertEqual(inputs["generation_mode"], "quality")

    def test_template_strategy_uses_the_cheap_model_with_a_category(self):
        request = self.request(strategy="template")
        model = self.provider.model_for(request)
        self.assertEqual(model, config.vton_fast_model())
        self.assertEqual(model, "tryon-v1.6")
        inputs = self.provider.build_inputs(request, model)
        self.assertEqual(
            set(inputs),
            {"model_image", "garment_image", "category", "garment_photo_type", "mode", "output_format"},
        )
        self.assertEqual(inputs["category"], "one-pieces")
        self.assertEqual(inputs["garment_photo_type"], "flat-lay")

    def test_template_strategy_in_quality_mode_moves_to_the_flagship(self):
        request = self.request(strategy="template", mode="quality")
        model = self.provider.model_for(request)
        self.assertEqual(model, config.vton_quality_model())
        inputs = self.provider.build_inputs(request, model)
        self.assertIn("product_image", inputs)

    def test_edit_strategy_puts_the_fabric_in_image_context(self):
        request = self.request(strategy="edit")
        model = self.provider.model_for(request)
        self.assertEqual(model, "edit")
        inputs = self.provider.build_inputs(request, model)
        self.assertEqual(inputs["image"], "PERSON")
        self.assertEqual(inputs["image_context"], "GARMENT")
        self.assertIn("prompt", inputs)
        self.assertNotIn("model_image", inputs)

    def test_edit_strategy_without_a_prompt_is_refused(self):
        request = self.request(strategy="edit", prompt="")
        with self.assertRaises(ProviderError):
            self.provider.build_inputs(request, "edit")

    def test_invalid_category_falls_back_to_auto(self):
        request = self.request(strategy="template")
        request.garment_metadata["category"] = "hats"
        inputs = self.provider.build_inputs(request, "tryon-v1.6")
        self.assertEqual(inputs["category"], "auto")

    def test_prompts_are_clipped_to_the_documented_ceiling(self):
        request = self.request(prompt="x" * 5000)
        inputs = self.provider.build_inputs(request, "tryon-max")
        self.assertLessEqual(len(inputs["prompt"]), 900)

    def test_seed_is_passed_through_when_set(self):
        inputs = self.provider.build_inputs(self.request(seed=7), "tryon-max")
        self.assertEqual(inputs["seed"], 7)

    def test_missing_key_is_a_config_error(self):
        provider = FashnApiProvider(api_key="")
        os.environ.pop("FASHN_API_KEY", None)
        self.assertFalse(provider.is_configured())
        with self.assertRaises(ProviderConfigError):
            provider.generate(TryOnRequest("p", "g"))


class FashnResponseMappingTest(unittest.TestCase):
    def setUp(self):
        self.provider = FashnApiProvider(api_key="test-key")
        self.calls = []

    def _patch(self, responses):
        """Replace the HTTP layer with scripted (status, body, headers) tuples."""
        from fabric_studio.virtual_tryon import fashn_api_provider

        queue = list(responses)

        def fake_request(url, method="GET", payload=None, headers=None, timeout=60):
            self.calls.append({"url": url, "method": method, "payload": payload})
            return queue.pop(0)

        self.addCleanup(setattr, fashn_api_provider, "request_json", fashn_api_provider.request_json)
        fashn_api_provider.request_json = fake_request

    def test_run_returns_queued_with_the_prediction_id(self):
        self._patch([(200, {"id": "pred-1", "error": None}, {"x-fashn-credits-used": "2"})])
        result = self.provider.generate(TryOnRequest(
            "p", "g", {"category": "one-pieces"}, {"prompt": "Tailor it into an agbada."}))
        self.assertEqual(result.status, STATUS_QUEUED)
        self.assertEqual(result.generation_id, "pred-1")
        self.assertEqual(result.metadata["creditsUsed"], 2.0)
        self.assertTrue(self.calls[0]["url"].endswith("/run"))
        self.assertEqual(self.calls[0]["payload"]["model_name"], config.vton_tryon_model())

    def test_in_flight_statuses_map_to_processing(self):
        self._patch([
            (200, {"status": "starting"}, {}),
            (200, {"status": "in_queue"}, {}),
            (200, {"status": "processing"}, {}),
        ])
        self.assertEqual(self.provider.get_status("id").status, STATUS_QUEUED)
        self.assertEqual(self.provider.get_status("id").status, STATUS_QUEUED)
        self.assertEqual(self.provider.get_status("id").status, STATUS_PROCESSING)

    def test_completed_status_carries_the_output_url(self):
        self._patch([(200, {"status": "completed", "output": ["https://cdn/x.png"]}, {})])
        result = self.provider.get_status("id")
        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.result_image, "https://cdn/x.png")

    def test_completed_without_output_is_treated_as_failure(self):
        self._patch([(200, {"status": "completed", "output": []}, {})])
        self.assertEqual(self.provider.get_status("id").status, STATUS_FAILED)

    def test_runtime_errors_become_friendly_messages(self):
        cases = {
            "PoseError": "full body",
            "ContentModerationError": "clear, fully-clothed",
            "ImageLoadError": "couldn't read",
        }
        for name, fragment in cases.items():
            with self.subTest(error=name):
                self._patch([(200, {"status": "failed", "error": {"name": name, "message": "raw internal text"}}, {})])
                result = self.provider.get_status("id")
                self.assertEqual(result.status, STATUS_FAILED)
                self.assertEqual(result.error_code, name)
                self.assertIn(fragment, result.error)
                self.assertNotIn("raw internal text", result.error)

    def test_unauthorized_is_a_config_error(self):
        self._patch([(401, {"error": "UnauthorizedAccess", "message": "bad key"}, {})])
        with self.assertRaises(ProviderConfigError):
            self.provider.generate(TryOnRequest("p", "g"))

    def test_api_error_is_a_provider_error(self):
        self._patch([(400, {"error": "BadRequest", "message": "nope"}, {})])
        with self.assertRaises(ProviderError):
            self.provider.generate(TryOnRequest("p", "g"))

    def test_rate_limit_maps_to_its_own_error(self):
        from fabric_studio.virtual_tryon import http
        import urllib.error
        import io

        def raise_429(*args, **kwargs):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b'{"error":"RateLimitExceeded"}'))

        original = http.urllib.request.urlopen
        http.urllib.request.urlopen = raise_429
        self.addCleanup(setattr, http.urllib.request, "urlopen", original)
        with self.assertRaises(RateLimitError):
            http.request_json("https://example.invalid/run")


class SelfHostedProviderTest(unittest.TestCase):
    def test_it_implements_the_same_interface(self):
        provider = FashnVton15Provider(base_url="https://gpu.internal", token="t")
        self.assertTrue(provider.is_configured())
        inputs = provider.build_inputs(TryOnRequest("p", "g", {"category": "tops"}))
        self.assertEqual(inputs["model_image"], "p")
        self.assertEqual(inputs["category"], "tops")

    def test_masks_are_passed_through_when_available(self):
        provider = FashnVton15Provider(base_url="https://gpu.internal")
        request = TryOnRequest("p", "g", {"category": "tops", "masks": {"person": "data:..."}})
        self.assertIn("masks", provider.build_inputs(request))

    def test_unconfigured_url_is_a_config_error(self):
        provider = FashnVton15Provider(base_url="")
        os.environ.pop("FASHN_VTON15_URL", None)
        self.assertFalse(provider.is_configured())
        with self.assertRaises(ProviderConfigError):
            provider.generate(TryOnRequest("p", "g"))


class MockProviderTest(unittest.TestCase):
    def setUp(self):
        context.reset_stores()
        self.provider = MockProvider()

    def test_it_completes_without_network_or_credits(self):
        fabric = context.make_fabric("fab_mock", "geometric")
        outfit = context.make_outfit("out_mock", "modern-senator")
        from fabric_studio import garment_composer
        garment = garment_composer.compose(fabric, outfit)
        request = TryOnRequest(context.person_data_url(), garment["url"], {"category": "one-pieces"})
        result = self.provider.generate(request)
        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(result.metadata["creditsUsed"], 0)
        self.assertTrue(result.result_image.startswith("/media/generations/"))
        self.assertEqual(self.provider.get_status(result.generation_id).status, STATUS_COMPLETED)

    def test_unknown_job_reports_failure_rather_than_hanging(self):
        self.assertEqual(self.provider.get_status("mock_missing").status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
