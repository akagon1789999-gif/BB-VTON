"""FASHN cloud API provider.

Implemented against the documented FASHN prediction API: a single
`POST /v1/run` taking `{model_name, inputs}`, polled with `GET /v1/status/{id}`,
authenticated with `Authorization: Bearer $FASHN_API_KEY`. No endpoint or
parameter here is invented — see .agents/skills/fashn/reference.md.

The model is chosen by *strategy* (how the garment reaches the model) and
*mode* (how much to spend), never by the caller naming a model:

  composite -> tryon-max  `product_image` is the outfit template filled with the
                          chosen fabric — one flat-lay carrying both the cut and
                          the cloth. The default, and the intended workflow:
                          person + garment template + fabric swatch -> tryon-max.
  fabric    -> tryon-max  `product_image` is the bare fabric swatch; the prompt
                          alone describes the garment to tailor from it.
  template  -> tryon-v1.6 the same composite on the cheap legacy model, which
                          takes a category and a photo-type hint instead of a
                          prompt.
  edit      -> edit       `image` is the person and `image_context` is the
                          fabric; the prompt does the dressing.

Overridable with VTON_TRYON_MODEL / VTON_FAST_MODEL / VTON_EDIT_MODEL.
"""
from .. import config
from ..errors import ProviderConfigError, ProviderError, friendly_runtime_message
from .http import request_json
from .provider import VirtualTryOnProvider
from .types import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    TryOnResult,
)

# FASHN's in-flight statuses, mapped onto ours.
_STATUS_MAP = {
    "starting": STATUS_QUEUED,
    "in_queue": STATUS_QUEUED,
    "processing": STATUS_PROCESSING,
    "completed": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "canceled": STATUS_FAILED,
    "time_out": STATUS_FAILED,
}

VALID_CATEGORIES = ("auto", "tops", "bottoms", "one-pieces")

# Matches prompts.MAX_PROMPT_CHARS; duplicated here so the provider never
# depends on the prompt builder.
MAX_PROMPT_CHARS = 900


class FashnApiProvider(VirtualTryOnProvider):
    name = "fashn_api"
    supports_prompt = True
    supports_garment_remake = True

    def __init__(self, api_key=None, api_base=None):
        self._api_key = api_key
        self._api_base = api_base

    # ------------------------------------------------------------ config ---
    @property
    def api_key(self):
        return self._api_key or config.fashn_api_key()

    @property
    def api_base(self):
        return (self._api_base or config.fashn_api_base()).rstrip("/")

    def is_configured(self):
        return bool(self.api_key)

    def _headers(self):
        if not self.is_configured():
            raise ProviderConfigError(
                detail="FASHN_API_KEY is not set; add it to .env or the deployment environment."
            )
        return {"Authorization": "Bearer %s" % self.api_key}

    def model_for(self, request):
        strategy = request.strategy
        if strategy == "edit":
            return config.vton_edit_model()
        if strategy == "template" and request.mode != "quality":
            return config.vton_fast_model()
        return config.vton_tryon_model()

    # ------------------------------------------------------------ inputs ---
    def build_inputs(self, request, model_name):
        """Map the neutral request onto this model's documented input names."""
        options = request.options
        if model_name.startswith("edit"):
            inputs = self._edit_inputs(request)
        elif model_name.startswith("tryon-max"):
            inputs = self._tryon_max_inputs(request)
        else:
            inputs = self._tryon_v16_inputs(request)

        inputs["output_format"] = options.get("output_format", "jpeg")
        if options.get("seed") is not None:
            inputs["seed"] = int(options["seed"])
        return inputs

    def _tryon_max_inputs(self, request):
        """Flagship try-on. Carries the whole fabric brief in `prompt`."""
        inputs = {
            "model_image": request.person_image,
            "product_image": request.garment_image,
            "generation_mode": self._generation_mode(request, ("balanced", "quality")),
            "resolution": request.options.get("resolution") or config.vton_resolution(),
        }
        prompt = request.prompt
        if prompt:
            inputs["prompt"] = prompt[:MAX_PROMPT_CHARS]
        return inputs

    def _tryon_v16_inputs(self, request):
        """Legacy try-on: cheapest, and the only one taking an explicit category."""
        category = request.category
        if category not in VALID_CATEGORIES:
            category = "auto"
        inputs = {
            "model_image": request.person_image,
            "garment_image": request.garment_image,
            "category": category,
            # The garment image is a composed flat-lay, so say so instead of
            # letting the model guess it is a photo of someone wearing it.
            "garment_photo_type": "flat-lay",
            "mode": request.options.get("speed_mode", "balanced"),
        }
        if request.options.get("moderation_level"):
            inputs["moderation_level"] = request.options["moderation_level"]
        return inputs

    def _edit_inputs(self, request):
        """Person as the canvas, fabric as visual context."""
        if not request.prompt:
            raise ProviderError(detail="The edit model requires a prompt; none was built.")
        inputs = {
            "image": request.person_image,
            "prompt": request.prompt[:MAX_PROMPT_CHARS],
            "image_context": request.garment_image,
            "generation_mode": self._generation_mode(request, ("fast", "balanced", "quality")),
            "resolution": request.options.get("resolution") or config.vton_resolution(),
        }
        if request.options.get("mask"):
            inputs["mask"] = request.options["mask"]
        return inputs

    def _generation_mode(self, request, allowed):
        requested = request.options.get("generation_mode")
        if requested in allowed:
            return requested
        preferred = "quality" if request.mode == "quality" else "balanced"
        return preferred if preferred in allowed else allowed[0]

    # ------------------------------------------------------------ actions --
    def generate(self, request):
        model_name = self.model_for(request)
        payload = {"model_name": model_name, "inputs": self.build_inputs(request, model_name)}
        status_code, body, headers = request_json(
            "%s/run" % self.api_base,
            method="POST",
            payload=payload,
            headers=self._headers(),
            timeout=config.vton_timeout_seconds(),
        )
        if status_code >= 400:
            raise self._api_error(status_code, body)

        prediction_id = (body or {}).get("id")
        if not prediction_id:
            raise ProviderError(detail="FASHN /run returned no prediction id: %s" % body)

        return TryOnResult(
            status=STATUS_QUEUED,
            provider=self.name,
            generation_id=prediction_id,
            metadata={
                "model": model_name,
                "mode": request.mode,
                "creditsUsed": _credits(headers),
            },
        )

    def remake_garment(self, request):
        """Step one, on the `edit` model.

        `image` is the garment reference — flat-lay or worn — and
        `image_context` is the fabric; the prompt says to swap the material and
        keep everything else. The output is a garment image, which step two
        then puts on the customer.
        """
        model_name = config.vton_edit_model()
        inputs = {
            "image": request.garment_image,
            "image_context": request.fabric_image,
            "prompt": (request.prompt or "")[:MAX_PROMPT_CHARS],
            "generation_mode": "quality" if request.mode == "quality" else "balanced",
            "resolution": request.options.get("resolution") or config.vton_resolution(),
            "output_format": request.options.get("output_format", "jpeg"),
        }
        if not inputs["prompt"]:
            raise ProviderError(detail="Garment remake requires a prompt; none was built.")
        if request.options.get("seed") is not None:
            inputs["seed"] = int(request.options["seed"])

        status_code, body, headers = request_json(
            "%s/run" % self.api_base,
            method="POST",
            payload={"model_name": model_name, "inputs": inputs},
            headers=self._headers(),
            timeout=config.vton_timeout_seconds(),
        )
        if status_code >= 400:
            raise self._api_error(status_code, body)
        prediction_id = (body or {}).get("id")
        if not prediction_id:
            raise ProviderError(detail="FASHN /run returned no prediction id: %s" % body)
        return TryOnResult(
            status=STATUS_QUEUED,
            provider=self.name,
            generation_id=prediction_id,
            metadata={"model": model_name, "step": "remake", "creditsUsed": _credits(headers)},
        )

    def get_status(self, generation_id):
        status_code, body, headers = request_json(
            "%s/status/%s" % (self.api_base, generation_id),
            headers=self._headers(),
            timeout=60,
        )
        if status_code >= 400:
            raise self._api_error(status_code, body)

        raw_status = (body or {}).get("status") or "processing"
        status = _STATUS_MAP.get(raw_status, STATUS_PROCESSING)
        output = (body or {}).get("output") or []
        error = (body or {}).get("error") or None

        if status == STATUS_COMPLETED and not output:
            status = STATUS_FAILED
            error = {"name": "PipelineError", "message": "completed with no output"}

        result = TryOnResult(
            status=status,
            provider=self.name,
            generation_id=generation_id,
            result_image=output[0] if output else None,
            metadata={"providerStatus": raw_status, "creditsUsed": _credits(headers)},
        )
        if status == STATUS_FAILED:
            error_name = (error or {}).get("name") if isinstance(error, dict) else None
            if not error_name and raw_status in ("canceled", "time_out"):
                error_name = "PollingTimeout"
            result.error = friendly_runtime_message(error_name)
            result.error_code = error_name or raw_status
            result.metadata["providerError"] = error
        return result

    def _api_error(self, status_code, body):
        message = ""
        if isinstance(body, dict):
            message = body.get("message") or body.get("error") or ""
        if status_code in (401, 403):
            return ProviderConfigError(
                detail="FASHN rejected the API key (%s): %s" % (status_code, message)
            )
        return ProviderError(detail="FASHN API error %s: %s" % (status_code, message))


def _credits(headers):
    for key, value in (headers or {}).items():
        if key.lower() == "x-fashn-credits-used":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None
