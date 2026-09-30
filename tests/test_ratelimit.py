"""Rate limiting: the window itself, and the warm endpoint that depends on it."""
import json
import unittest

from flask import Flask

from . import context  # noqa: F401  (sets DATA_DIR first)
from fabric_studio import ratelimit
from fabric_studio.routes import create_blueprint
from fabric_studio.virtual_tryon import reset_providers


class RateLimiterTest(unittest.TestCase):
    def test_it_allows_up_to_the_limit_then_refuses(self):
        limiter = ratelimit.RateLimiter(limit=2, per_seconds=60)
        self.assertEqual(limiter.check("a", now=1000)[0], True)
        self.assertEqual(limiter.check("a", now=1001)[0], True)
        allowed, retry_after = limiter.check("a", now=1002)
        self.assertFalse(allowed)
        self.assertAlmostEqual(retry_after, 58.0, places=1)

    def test_the_window_slides_rather_than_resetting_in_steps(self):
        # A fixed bucket would let both hits land a second apart across a
        # boundary. A sliding window expires them one at a time.
        limiter = ratelimit.RateLimiter(limit=1, per_seconds=60)
        self.assertTrue(limiter.check("a", now=1000)[0])
        self.assertFalse(limiter.check("a", now=1059)[0])
        self.assertTrue(limiter.check("a", now=1061)[0])

    def test_keys_are_independent(self):
        limiter = ratelimit.RateLimiter(limit=1, per_seconds=60)
        self.assertTrue(limiter.check("a", now=1000)[0])
        self.assertTrue(limiter.check("b", now=1000)[0])
        self.assertFalse(limiter.check("a", now=1000)[0])

    def test_peek_does_not_consume(self):
        limiter = ratelimit.RateLimiter(limit=2, per_seconds=60)
        self.assertEqual(limiter.peek("a", now=1000), 2)
        limiter.check("a", now=1000)
        self.assertEqual(limiter.peek("a", now=1000), 1)
        self.assertEqual(limiter.peek("a", now=1000), 1)

    def test_rotating_keys_cannot_grow_memory_without_bound(self):
        # This is the abuse shape: a fresh client id every request.
        limiter = ratelimit.RateLimiter(limit=1, per_seconds=60, max_keys=10)
        for index in range(200):
            limiter.check("client-%d" % index, now=1000 + index)
        self.assertLessEqual(len(limiter._hits), 10)


class WarmEndpointTest(unittest.TestCase):
    """The public warm route. Warming can start a GPU, so this is a spending
    control, not a traffic one."""

    def setUp(self):
        context.reset_stores()
        reset_providers()
        app = Flask(__name__)
        app.register_blueprint(create_blueprint(lambda function: function))
        self.client = app.test_client()

    def _warm(self, client_id="client-0001"):
        return self.client.post(
            "/api/fabric-studio/warm", headers={"X-BB-Client-Id": client_id}
        )

    def test_a_provider_with_nothing_to_warm_answers_plainly(self):
        # Default provider is fashn_api, which is never cold. The studio page
        # should be able to call this unconditionally, so this is a 200 with
        # supported:false rather than an error.
        response = self._warm()
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.data)
        self.assertFalse(body["supported"])


class WarmRateLimitTest(unittest.TestCase):
    """Limits applied to a provider that *can* be warmed."""

    def setUp(self):
        context.reset_stores()
        reset_providers()
        os_env = context.os.environ
        os_env["VTON_PROVIDER"] = "fashn_vton_15"
        os_env["FASHN_VTON15_URL"] = "https://gpu.invalid"
        os_env["WARM_RATE_PER_CLIENT"] = "2"
        os_env["WARM_RATE_WINDOW_SECONDS"] = "300"
        os_env["WARM_RATE_GLOBAL"] = "3"
        os_env["WARM_RATE_GLOBAL_WINDOW_SECONDS"] = "60"
        self.addCleanup(self._restore)

        app = Flask(__name__)
        app.register_blueprint(create_blueprint(lambda function: function))
        self.client = app.test_client()

    def _restore(self):
        for key in ("VTON_PROVIDER", "FASHN_VTON15_URL", "WARM_RATE_PER_CLIENT",
                    "WARM_RATE_WINDOW_SECONDS", "WARM_RATE_GLOBAL",
                    "WARM_RATE_GLOBAL_WINDOW_SECONDS"):
            context.os.environ.pop(key, None)
        reset_providers()

    def _warm(self, client_id="client-0001"):
        return self.client.post(
            "/api/fabric-studio/warm", headers={"X-BB-Client-Id": client_id}
        )

    def test_a_client_is_cut_off_after_its_allowance(self):
        self.assertEqual(self._warm("client-0001").status_code, 202)
        self.assertEqual(self._warm("client-0001").status_code, 202)
        response = self._warm("client-0001")
        self.assertEqual(response.status_code, 429)
        body = json.loads(response.data)
        self.assertEqual(body["code"], "warm_rate_limited")
        self.assertEqual(body["scope"], "client")
        self.assertGreater(int(response.headers["Retry-After"]), 0)

    def test_rotating_the_client_id_does_not_escape_the_global_ceiling(self):
        # The point of the global window: client ids are self-asserted, so a
        # per-client limit alone is bypassed by sending a new header.
        self.assertEqual(self._warm("client-aaaa").status_code, 202)
        self.assertEqual(self._warm("client-bbbb").status_code, 202)
        self.assertEqual(self._warm("client-cccc").status_code, 202)
        response = self._warm("client-dddd")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(json.loads(response.data)["scope"], "global")

    def test_ids_too_short_to_be_valid_all_share_the_anonymous_bucket(self):
        # CLIENT_ID_RE requires 6-64 chars, so a junk id is not a free bucket:
        # it falls back to "anonymous" and shares one allowance with every
        # other junk id. Rotating *invalid* ids therefore buys nothing.
        self.assertEqual(self._warm("x").status_code, 202)
        self.assertEqual(self._warm("y").status_code, 202)
        response = self._warm("z")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(json.loads(response.data)["scope"], "client")

    def test_the_global_limit_is_checked_before_the_per_client_one(self):
        # Otherwise a rotating attacker would burn other clients' allowances
        # on their way to the ceiling.
        for name in ("client-aaaa", "client-bbbb", "client-cccc"):
            self._warm(name)
        self.assertEqual(json.loads(self._warm("client-fresh").data)["scope"], "global")


if __name__ == "__main__":
    unittest.main()
