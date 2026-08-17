"""FASHN cloud API provider.

Implemented against the documented FASHN prediction API: a single
`POST /v1/run` taking `{model_name, inputs}`, polled with `GET /v1/status/{id}`,
authenticated with `Authorization: Bearer $FASHN_API_KEY`. No endpoint or
parameter here is invented — see .agents/skills/fashn/reference.md.

Model choice is a *mode*, not a caller decision:
  fast    -> tryon-v1.6  (cheapest; accepts `category` + `garment_photo_type`,
                          which is exactly what a composed flat-lay is)
  quality -> tryon-max   (flagship; accepts a refinement `prompt`)
Both are overridable with VTON_FAST_MODEL / VTON_QUALITY_MODEL.
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


class FashnApiProvider(VirtualTryOnProvider):
    name = "fashn_api"
    supports_prompt = True

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
        if request.mode == "quality":
            return config.vton_quality_model()
        return config.vton_fast_model()

    # ------------------------------------------------------------ inputs ---
    def build_inputs(self, request, model_name):
        """Map the neutral request onto this model's documented input names."""
        person = request.person_image
        garment = request.garment_image
        options = request.options

        if model_name.startswith("tryon-max"):
            inputs = {
                "model_image": person,
                "product_image": garment,
                "output_format": options.get("output_format", "jpeg"),
            }
            prompt = request.prompt
            if prompt:
                inputs["prompt"] = prompt[:600]
            if options.get("resolution"):
                inputs["resolution"] = options["resolution"]
            if options.get("generation_mode"):
                inputs["generation_mode"] = options["generation_mode"]
        else:
            # tryon-v1.6 (and anything else that follows its schema)
            category = request.category
            if category not in VALID_CATEGORIES:
                category = "auto"
            inputs = {
                "model_image": person,
                "garment_image": garment,
                "category": category,
                # The garment image is a composed flat-lay, so say so instead of
                # letting the model guess it is a photo of someone wearing it.
                "garment_photo_type": "flat-lay",
                "mode": options.get("speed_mode", "balanced"),
                "output_format": options.get("output_format", "jpeg"),
            }
            if options.get("moderation_level"):
                inputs["moderation_level"] = options["moderation_level"]

        if options.get("seed") is not None:
            inputs["seed"] = int(options["seed"])
        return inputs

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
