"""Self-hosted FASHN VTON 1.5 provider (migration target).

Enable with:

    VTON_PROVIDER=fashn_vton_15
    FASHN_VTON15_URL=https://gpu-host.internal      # no trailing slash
    FASHN_VTON15_TOKEN=<shared secret>              # optional

It speaks the same submit/poll envelope as the cloud API — `POST {url}/run`
with `{model_name, inputs}` and `GET {url}/status/{id}` returning
`{id, status, output[], error}` — because that is the contract the inference
server is expected to expose. Nothing else in Fabric Studio changes when the
switch is made: catalogues, processing, composition, history and UI all sit
above this interface.

STATUS: written against the documented envelope but NOT yet exercised against a
real deployment (there is no GPU host to point it at). Verify the input names
your build expects before switching production traffic to it.
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

_STATUS_MAP = {
    "starting": STATUS_QUEUED,
    "in_queue": STATUS_QUEUED,
    "queued": STATUS_QUEUED,
    "processing": STATUS_PROCESSING,
    "completed": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "canceled": STATUS_FAILED,
    "time_out": STATUS_FAILED,
}


class FashnVton15Provider(VirtualTryOnProvider):
    name = "fashn_vton_15"
    supports_prompt = False

    def __init__(self, base_url=None, token=None, model_name="vton-1.5"):
        self._base_url = base_url
        self._token = token
        self.model_name = model_name

    @property
    def base_url(self):
        return (self._base_url or config.vton15_url()).rstrip("/")

    @property
    def token(self):
        return self._token or config.vton15_token()

    def is_configured(self):
        return bool(self.base_url)

    def _headers(self):
        if not self.is_configured():
            raise ProviderConfigError(
                detail="FASHN_VTON15_URL is not set; point it at the self-hosted inference server."
            )
        headers = {}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        return headers

    def build_inputs(self, request):
        inputs = {
            "model_image": request.person_image,
            "garment_image": request.garment_image,
            "category": request.category,
            "garment_photo_type": "flat-lay",
        }
        if request.options.get("seed") is not None:
            inputs["seed"] = int(request.options["seed"])
        # A self-hosted deployment may expose the segmentation masks we already
        # computed; passing them lets it skip its own human parsing.
        masks = request.garment_metadata.get("masks")
        if masks:
            inputs["masks"] = masks
        return inputs

    def generate(self, request):
        status_code, body, _headers = request_json(
            "%s/run" % self.base_url,
            method="POST",
            payload={"model_name": self.model_name, "inputs": self.build_inputs(request)},
            headers=self._headers(),
            timeout=config.vton_timeout_seconds(),
        )
        if status_code >= 400:
            raise ProviderError(detail="VTON 1.5 error %s: %s" % (status_code, body))
        prediction_id = (body or {}).get("id")
        if not prediction_id:
            raise ProviderError(detail="VTON 1.5 /run returned no id: %s" % body)
        return TryOnResult(
            status=STATUS_QUEUED,
            provider=self.name,
            generation_id=prediction_id,
            metadata={"model": self.model_name, "mode": request.mode, "selfHosted": True},
        )

    def get_status(self, generation_id):
        status_code, body, _headers = request_json(
            "%s/status/%s" % (self.base_url, generation_id),
            headers=self._headers(),
            timeout=60,
        )
        if status_code >= 400:
            raise ProviderError(detail="VTON 1.5 status error %s: %s" % (status_code, body))
        raw_status = (body or {}).get("status") or "processing"
        status = _STATUS_MAP.get(raw_status, STATUS_PROCESSING)
        output = (body or {}).get("output") or []
        result = TryOnResult(
            status=status,
            provider=self.name,
            generation_id=generation_id,
            result_image=output[0] if output else None,
            metadata={"providerStatus": raw_status, "selfHosted": True},
        )
        if status == STATUS_FAILED:
            error = (body or {}).get("error") or {}
            error_name = error.get("name") if isinstance(error, dict) else None
            result.error = friendly_runtime_message(error_name)
            result.error_code = error_name or raw_status
        return result
