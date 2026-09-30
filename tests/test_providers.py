"""Provider abstraction: switching, input mapping, status and error mapping."""
import os
import time
import unittest
from unittest import mock

from . import context
from fabric_studio import config
from fabric_studio.errors import (
    ProviderConfigError,
    ProviderError,
    RateLimitError,
    TimeoutError_,
)
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
from fabric_studio.virtual_tryon import fashn_vton15_provider as vton15_module
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
    """The service is deploy/pai-eas/app.py: synchronous POST /v1/tryon."""

    def setUp(self):
        self.provider = FashnVton15Provider(base_url="https://gpu.internal", token="tok")

    # ------------------------------------------------------------- payload
    def test_payload_uses_the_field_names_the_service_declares(self):
        payload = self.provider.build_payload(TryOnRequest("p", "g", {"category": "tops"}))
        self.assertEqual(payload["person_image"], "p")
        self.assertEqual(payload["garment_image"], "g")
        self.assertEqual(payload["category"], "tops")
        self.assertEqual(payload["garment_photo_type"], "flat-lay")

    def test_payload_carries_no_field_the_service_would_reject(self):
        # app.py sets model_config = {"extra": "forbid"}, so an unknown key is
        # a 422, not something quietly dropped. This is the test that would
        # have caught the old provider sending model_name/inputs/masks.
        allowed = {
            "person_image", "garment_image", "category", "garment_photo_type",
            "num_samples", "num_timesteps", "guidance_scale", "seed",
            "segmentation_free", "response_format",
        }
        request = TryOnRequest(
            "p", "g",
            {"category": "tops", "masks": {"person": "data:..."}},
            {"seed": 7, "guidance_scale": 2.0, "segmentation_free": False},
        )
        self.assertTrue(set(self.provider.build_payload(request)) <= allowed)

    def test_mode_selects_timesteps(self):
        fast = self.provider.build_payload(TryOnRequest("p", "g", {}, {"mode": "fast"}))
        quality = self.provider.build_payload(TryOnRequest("p", "g", {}, {"mode": "quality"}))
        self.assertEqual(fast["num_timesteps"], 20)
        self.assertEqual(quality["num_timesteps"], 50)

    # ---------------------------------------------------------------- auth
    def test_token_is_sent_bare_because_eas_rejects_bearer(self):
        self.assertEqual(self.provider._headers()["Authorization"], "tok")

    def test_unconfigured_url_is_a_config_error(self):
        provider = FashnVton15Provider(base_url="")
        os.environ.pop("FASHN_VTON15_URL", None)
        self.assertFalse(provider.is_configured())
        with self.assertRaises(ProviderConfigError):
            provider.generate(TryOnRequest("p", "g"))

    # ------------------------------------------------------------ dispatch
    def _await_terminal(self, generation_id, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.provider.get_status(generation_id)
            if result.is_terminal:
                return result
            time.sleep(0.01)
        self.fail("job %s never reached a terminal status" % generation_id)

    def test_a_successful_call_completes_off_the_request_thread(self):
        calls = []

        def fake_request_json(url, method="GET", payload=None, headers=None, timeout=60):
            calls.append((url, method, payload, headers, timeout))
            return 200, {
                "request_id": "req-1",
                "model": "fashn-vton-1.5",
                "elapsed_seconds": 12.5,
                "seed": 42,
                "images": ["data:image/png;base64,AAAA"],
            }, {}

        with mock.patch.object(vton15_module, "request_json", fake_request_json):
            submitted = self.provider.generate(TryOnRequest("p", "g", {"category": "tops"}))
            # Returns immediately, non-terminal: a cold start is 2-4 minutes and
            # must not block the caller.
            self.assertEqual(submitted.status, STATUS_QUEUED)
            self.assertFalse(submitted.is_terminal)
            result = self._await_terminal(submitted.generation_id)

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(result.result_image, "data:image/png;base64,AAAA")
        self.assertEqual(result.metadata["creditsUsed"], 0)
        self.assertEqual(result.metadata["elapsedSeconds"], 12.5)

        url, method, _payload, headers, timeout = calls[0]
        self.assertEqual(url, "https://gpu.internal/v1/tryon")
        self.assertEqual(method, "POST")
        self.assertEqual(headers["Authorization"], "tok")
        self.assertGreaterEqual(timeout, 300)  # must outlast a cold start

    def test_busy_service_is_reported_as_busy_not_as_a_crash(self):
        def overloaded(*args, **kwargs):
            return 503, {"error": "queue full", "status": 503}, {}

        with mock.patch.object(vton15_module, "request_json", overloaded):
            submitted = self.provider.generate(TryOnRequest("p", "g"))
            result = self._await_terminal(submitted.generation_id)

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error_code, "HTTP503")
        self.assertIn("busy", result.error.lower())

    def test_a_thrown_error_lands_as_a_failed_job_rather_than_a_lost_thread(self):
        def explode(*args, **kwargs):
            raise TimeoutError_(detail="Request timed out")

        with mock.patch.object(vton15_module, "request_json", explode):
            submitted = self.provider.generate(TryOnRequest("p", "g"))
            result = self._await_terminal(submitted.generation_id)

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertIn("timed out", result.error.lower())

    def test_an_empty_image_list_is_a_failure_not_a_blank_success(self):
        with mock.patch.object(
            vton15_module, "request_json", lambda *a, **k: (200, {"images": []}, {})
        ):
            submitted = self.provider.generate(TryOnRequest("p", "g"))
            result = self._await_terminal(submitted.generation_id)

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error_code, "EmptyOutput")

    def test_unknown_generation_fails_rather_than_polling_forever(self):
        result = self.provider.get_status("vt15_missing")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error_code, "UnknownGeneration")

    # -------------------------------------------------------------- health
    def test_health_hits_the_health_path(self):
        seen = {}

        def fake(url, method="GET", payload=None, headers=None, timeout=60):
            seen.update(url=url, timeout=timeout, headers=headers)
            return 200, {"queue": 0, "uptime": 12}, {}

        with mock.patch.object(vton15_module, "request_json", fake):
            body = self.provider.health(timeout=10)

        self.assertEqual(seen["url"], "https://gpu.internal/health")
        self.assertEqual(seen["timeout"], 10)      # short probe, not the warm-up
        self.assertEqual(seen["headers"]["Authorization"], "tok")
        self.assertEqual(body["queue"], 0)

    def test_health_defaults_to_the_cold_start_timeout(self):
        seen = {}

        def fake(url, method="GET", payload=None, headers=None, timeout=60):
            seen["timeout"] = timeout
            return 200, {}, {}

        with mock.patch.object(vton15_module, "request_json", fake):
            self.provider.health()
        self.assertGreaterEqual(seen["timeout"], 300)

    def test_health_error_status_raises(self):
        with mock.patch.object(
            vton15_module, "request_json", lambda *a, **k: (500, {"error": "boom"}, {})
        ):
            with self.assertRaises(ProviderError):
                self.provider.health(timeout=1)

    # ---------------------------------------------------------------- warm
    def _await_warm(self, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.provider.warm_state()
            if state.get("status") in ("ready", "error"):
                return state
            time.sleep(0.01)
        self.fail("warm never settled")

    def test_warm_returns_immediately_and_settles_in_the_background(self):
        with mock.patch.object(
            vton15_module, "request_json", lambda *a, **k: (200, {"uptime": 3}, {})
        ):
            state = self.provider.warm()
            self.assertEqual(state["status"], "warming")   # does not block
            settled = self._await_warm()

        self.assertEqual(settled["status"], "ready")
        self.assertEqual(settled["service"]["uptime"], 3)

    def test_a_failed_warm_is_recorded_not_raised(self):
        def explode(*args, **kwargs):
            raise TimeoutError_(detail="cold start exceeded")

        with mock.patch.object(vton15_module, "request_json", explode):
            self.provider.warm()
            settled = self._await_warm()

        self.assertEqual(settled["status"], "error")
        self.assertIn("cold start", settled["error"])

    def test_concurrent_warms_collapse_into_one(self):
        started = []

        def slow(*args, **kwargs):
            started.append(1)
            time.sleep(0.2)
            return 200, {}, {}

        with mock.patch.object(vton15_module, "request_json", slow):
            self.provider.warm()
            second = self.provider.warm()
            # The second call joins the in-flight warm rather than starting a
            # second replica spin-up.
            self.assertEqual(second["status"], "warming")
            self._await_warm()

        self.assertEqual(len(started), 1)

    def test_describe_advertises_the_capabilities(self):
        described = self.provider.describe()
        self.assertTrue(described["supportsHealth"])
        self.assertTrue(described["supportsWarm"])


class ProviderHealthContractTest(unittest.TestCase):
    """Engines we do not host have nothing useful to answer."""

    def test_hosted_providers_do_not_claim_health_or_warm(self):
        for name in ("fashn_api", "mock"):
            provider = get_provider(name)
            self.assertFalse(provider.supports_health, name)
            self.assertFalse(provider.supports_warm, name)
            with self.assertRaises(NotImplementedError):
                provider.health()
            with self.assertRaises(NotImplementedError):
                provider.warm()


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
