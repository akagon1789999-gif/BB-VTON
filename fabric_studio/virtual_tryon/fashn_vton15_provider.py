"""Self-hosted FASHN VTON 1.5 provider (PAI-EAS).

Enable with:

    VTON_PROVIDER=fashn_vton_15
    FASHN_VTON15_URL=http://<service>.<uid>.<region>.pai-eas.aliyuncs.com
    FASHN_VTON15_TOKEN=<the EAS access token from `eascmd desc <service>`>

The URL is the service root; `/v1/tryon` is appended. Both EAS address forms
work — the per-service `InternetEndpoint` from `eascmd desc`, or the gateway
form `https://<host>/api/predict/<service>`.

## Why this does not look like the cloud provider

The cloud API is submit-then-poll: `POST /run` hands back an id, `GET
/status/{id}` reports on it. Our own service (deploy/pai-eas/app.py) is
**synchronous** — one `POST /v1/tryon`, and the reply carries the finished
images. It has no job ids and nothing to poll.

The provider interface is the polling shape, because that is what the browser
already speaks. So this adapter runs the blocking call on a worker thread and
answers polls from an in-process table. `generate()` returns immediately with
`queued`; `get_status()` reports `processing` until the thread lands.

Doing it inline instead would mean holding a request thread for the length of a
**cold start** — the service scales to zero, so the first call after idle pays
an image pull, a 2 GB read off OSS and CUDA warm-up. Budget 2-4 minutes. No
browser waits that long, and a synchronous provider would turn every cold start
into a timeout.

## The limitation that follows from that

Job state lives in this process's memory. Under a multi-worker server
(gunicorn with `--workers 2+`), a poll can land on a worker that never saw the
submission and will be told the job is unknown. Run a single worker, pin
sessions to one, or move `_JOBS` to shared storage before scaling out. It is
recorded here rather than solved because the deployment is single-process
today, and the wrong fix (a database round-trip per poll) is worse than the
honest note.
"""
import threading
import time
import uuid

from .. import config
from ..errors import ProviderConfigError, ProviderError
from .http import request_json
from .provider import VirtualTryOnProvider
from .types import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    TryOnResult,
)

# num_timesteps by mode. The service caps these at MAX_TIMESTEPS server-side,
# so these are requests, not guarantees: 20 fast, 30 balanced, 50 quality.
_TIMESTEPS = {"fast": 20, "quality": 50}
_DEFAULT_TIMESTEPS = 30

# How many finished jobs to keep answering for after they complete. The browser
# polls until it sees a terminal status, so this only needs to outlive one poll
# interval; it is generous to survive a reload.
_JOB_RETENTION = 256


class _Job(object):
    __slots__ = ("status", "result", "created")

    def __init__(self):
        self.status = STATUS_QUEUED
        self.result = None
        self.created = time.time()


class FashnVton15Provider(VirtualTryOnProvider):
    name = "fashn_vton_15"
    supports_prompt = False
    # VTON 1.5 puts an existing garment onto a person. It cannot remake a
    # garment in a new fabric, so the pipeline composites locally instead.
    supports_garment_remake = False

    def __init__(self, base_url=None, token=None, timeout=None):
        self._base_url = base_url
        self._token = token
        self._timeout = timeout
        self._jobs = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ config
    @property
    def base_url(self):
        return (self._base_url or config.vton15_url() or "").rstrip("/")

    @property
    def token(self):
        return self._token or config.vton15_token()

    @property
    def timeout(self):
        return self._timeout or config.vton15_timeout_seconds()

    def is_configured(self):
        return bool(self.base_url)

    def _headers(self):
        if not self.is_configured():
            raise ProviderConfigError(
                detail="FASHN_VTON15_URL is not set; point it at the PAI-EAS service."
            )
        headers = {}
        if self.token:
            # EAS wants the bare token. `Bearer <token>` is rejected.
            headers["Authorization"] = self.token
        return headers

    # ----------------------------------------------------------- payload
    def build_payload(self, request):
        """Map a provider-neutral request onto the service's JSON body.

        The service declares `extra: forbid`, so an unrecognised key is a 422
        rather than something quietly ignored. Send only what it accepts.
        """
        mode = request.mode
        payload = {
            "person_image": request.person_image,
            "garment_image": request.garment_image,
            "category": request.category,
            # Every strategy in this app hands the engine a flat garment image
            # -- a composed template, or the bare swatch -- never a photo of
            # someone already wearing it.
            "garment_photo_type": "flat-lay",
            "num_samples": 1,
            "num_timesteps": _TIMESTEPS.get(mode, _DEFAULT_TIMESTEPS),
            "response_format": "base64",
        }
        seed = request.options.get("seed")
        if seed is not None:
            payload["seed"] = int(seed)
        guidance = request.options.get("guidance_scale")
        if guidance is not None:
            payload["guidance_scale"] = float(guidance)
        segmentation_free = request.options.get("segmentation_free")
        if segmentation_free is not None:
            payload["segmentation_free"] = bool(segmentation_free)
        return payload

    # --------------------------------------------------------- lifecycle
    def generate(self, request):
        payload = self.build_payload(request)
        headers = self._headers()  # raises before a thread is spawned
        generation_id = "vt15_%s" % uuid.uuid4().hex[:16]

        with self._lock:
            self._prune()
            self._jobs[generation_id] = _Job()

        thread = threading.Thread(
            target=self._run,
            args=(generation_id, payload, headers),
            name="vton15-%s" % generation_id,
        )
        thread.daemon = True
        thread.start()

        return TryOnResult(
            status=STATUS_QUEUED,
            provider=self.name,
            generation_id=generation_id,
            metadata={
                "model": "fashn-vton-1.5",
                "mode": request.mode,
                "selfHosted": True,
                "creditsUsed": 0,  # our own GPU; no per-call billing
            },
        )

    def get_status(self, generation_id):
        with self._lock:
            job = self._jobs.get(generation_id)

        if job is None:
            # Unknown id: a restart, an eviction, or a poll that landed on
            # another worker. Report failure rather than polling forever.
            return TryOnResult(
                status=STATUS_FAILED,
                provider=self.name,
                generation_id=generation_id,
                error="That generation is no longer being tracked. Please try again.",
                error_code="UnknownGeneration",
            )
        if job.result is not None:
            return job.result
        return TryOnResult(
            status=job.status,
            provider=self.name,
            generation_id=generation_id,
            metadata={"selfHosted": True, "waitedSeconds": round(time.time() - job.created, 1)},
        )

    # ------------------------------------------------------------ worker
    def _run(self, generation_id, payload, headers):
        """Blocking call, on a worker thread. Never raises into the thread."""
        with self._lock:
            job = self._jobs.get(generation_id)
            if job is not None:
                job.status = STATUS_PROCESSING

        try:
            status_code, body, _headers = request_json(
                "%s/v1/tryon" % self.base_url,
                method="POST",
                payload=payload,
                headers=headers,
                timeout=self.timeout,
            )
            result = self._interpret(generation_id, status_code, body)
        except Exception as exc:  # noqa: BLE001 - a thread must not die silently
            result = TryOnResult(
                status=STATUS_FAILED,
                provider=self.name,
                generation_id=generation_id,
                error=getattr(exc, "detail", None) or str(exc),
                error_code=type(exc).__name__,
            )

        with self._lock:
            job = self._jobs.get(generation_id)
            if job is not None:
                job.status = result.status
                job.result = result

    def _interpret(self, generation_id, status_code, body):
        body = body or {}
        if status_code >= 400:
            detail = body.get("error") or "HTTP %s" % status_code
            # 503 is the service shedding load rather than failing: one GPU
            # serves one request at a time, and past MAX_QUEUE it says so.
            if status_code == 503:
                detail = "The try-on service is busy. Please try again in a moment."
            return TryOnResult(
                status=STATUS_FAILED,
                provider=self.name,
                generation_id=generation_id,
                error=detail,
                error_code="HTTP%s" % status_code,
            )

        images = body.get("images") or []
        if not images:
            return TryOnResult(
                status=STATUS_FAILED,
                provider=self.name,
                generation_id=generation_id,
                error="The try-on service returned no image.",
                error_code="EmptyOutput",
            )

        return TryOnResult(
            status=STATUS_COMPLETED,
            provider=self.name,
            generation_id=generation_id,
            # Already a `data:image/png;base64,...` URI, which is what the rest
            # of the pipeline accepts.
            result_image=images[0],
            metadata={
                "selfHosted": True,
                "creditsUsed": 0,
                "model": body.get("model") or "fashn-vton-1.5",
                "seed": body.get("seed"),
                "elapsedSeconds": body.get("elapsed_seconds"),
                "requestId": body.get("request_id"),
            },
        )

    # ------------------------------------------------------------- misc
    def _prune(self):
        """Caller holds the lock. Drop the oldest jobs past the retention cap."""
        if len(self._jobs) <= _JOB_RETENTION:
            return
        ordered = sorted(self._jobs.items(), key=lambda item: item[1].created)
        for key, _job in ordered[: len(self._jobs) - _JOB_RETENTION]:
            self._jobs.pop(key, None)

    def health(self):
        """Ask the service how it is. Returns the parsed body, or raises.

        Useful for a readiness check, and for warming a scaled-to-zero replica
        before a customer pays the cold start.
        """
        status_code, body, _headers = request_json(
            "%s/health" % self.base_url,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if status_code >= 400:
            raise ProviderError(detail="VTON 1.5 health check failed: HTTP %s" % status_code)
        return body or {}
