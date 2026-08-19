"""Provider interface and factory.

    VirtualTryOnProvider
      |
      +-- FashnApiProvider     (now: FASHN cloud API)
      +-- FashnVton15Provider  (later: self-hosted FASHN VTON 1.5)
      +-- MockProvider         (development and tests, zero credits)

Application code calls `get_provider()` and never imports a concrete provider,
so switching engines is the VTON_PROVIDER environment variable and nothing
else.
"""
import threading

from .. import config
from ..errors import ProviderConfigError
from .types import GarmentRemakeRequest, TryOnRequest, TryOnResult  # noqa: F401


class VirtualTryOnProvider(object):
    """Contract every try-on engine implements."""

    name = "abstract"
    supports_prompt = False
    # Whether the engine can remake a garment in a new fabric (step one of the
    # two-step pipeline). Engines that cannot are still usable: the pipeline
    # composites locally instead.
    supports_garment_remake = False

    def generate(self, request):
        """Submit a generation. Returns a TryOnResult (usually non-terminal)."""
        raise NotImplementedError

    def get_status(self, generation_id):
        """Poll a previously submitted generation."""
        raise NotImplementedError

    def remake_garment(self, request):
        """Remake a garment in a new fabric. Returns a TryOnResult whose
        result_image is the new *garment*, not a person wearing it."""
        raise NotImplementedError(
            "%s cannot remake garments; composite the fabric locally instead" % self.name
        )

    def is_configured(self):
        """False when required credentials/URLs are missing."""
        return True

    def describe(self):
        return {
            "provider": self.name,
            "configured": self.is_configured(),
            "supportsPrompt": self.supports_prompt,
            "supportsGarmentRemake": self.supports_garment_remake,
        }


_registry_lock = threading.Lock()
_instances = {}


def _build(name):
    if name == "mock":
        from .mock_provider import MockProvider
        return MockProvider()
    if name in ("fashn_vton_15", "fashn_vton15", "vton15"):
        from .fashn_vton15_provider import FashnVton15Provider
        return FashnVton15Provider()
    if name in ("fashn_api", "fashn", ""):
        from .fashn_api_provider import FashnApiProvider
        return FashnApiProvider()
    raise ProviderConfigError(
        detail="Unknown VTON_PROVIDER '%s'. Use fashn_api, fashn_vton_15, or mock." % name
    )


def get_provider(name=None):
    """Return the configured provider instance (cached per name)."""
    resolved = (name or config.vton_provider_name() or "fashn_api").lower()
    with _registry_lock:
        instance = _instances.get(resolved)
        if instance is None:
            instance = _build(resolved)
            _instances[resolved] = instance
        return instance


def reset_providers():
    """Drop cached instances — used by tests that flip environment variables."""
    with _registry_lock:
        _instances.clear()


def available_providers():
    return ("fashn_api", "fashn_vton_15", "mock")
