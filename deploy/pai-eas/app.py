"""FASHN VTON v1.5 as a PAI-EAS custom-container service.

Two things about this file are shaped by EAS rather than by FastAPI:

1.  The pipeline is loaded inside the lifespan handler, which Uvicorn runs to
    completion *before* it binds the listening socket. EAS probes the container
    port, so a replica that is still loading weights is simply unreachable and
    EAS keeps waiting -- it never sees a fast 200 from a process that cannot
    actually serve. ``/health`` is therefore honest by construction.

2.  Exactly one inference runs at a time. A diffusion model on a single GPU
    gains nothing from concurrency and loses a lot to VRAM fragmentation, so
    requests queue on a semaphore and shed load with 503 once the queue is
    deeper than the autoscaler would take to add a replica.

Weights live on the OSS volume mounted at ``/mnt/models``; the human-parser
weights are baked into the image instead (see Dockerfile) so that a cold start
performs no network I/O at all.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import io
import ipaddress
import json
import logging
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Optional
from urllib.parse import urlparse

import anyio
import httpx
import torch
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

from fashn_vton import TryOnPipeline

Category = Literal["tops", "bottoms", "one-pieces"]
PhotoType = Literal["model", "flat-lay"]

# A 24 MP ceiling well under Pillow's own bomb threshold. Anything larger is a
# decompression bomb or a mistake; either way we refuse before decoding.
MAX_PIXELS: Final[int] = 24_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Everything tunable, resolved once at import."""

    weights_dir: str = os.environ.get("WEIGHTS_DIR", "/mnt/models")
    device: str = os.environ.get("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

    # Load shedding. max_queue is what separates "the autoscaler is adding a
    # replica" from "we are silently accumulating a 40-minute backlog".
    max_queue: int = _env_int("MAX_QUEUE", 16)
    queue_timeout_s: float = _env_float("QUEUE_TIMEOUT_S", 300.0)

    # Inference defaults and the hard ceilings a caller cannot exceed.
    default_timesteps: int = _env_int("DEFAULT_TIMESTEPS", 30)
    max_timesteps: int = _env_int("MAX_TIMESTEPS", 50)
    max_samples: int = _env_int("MAX_SAMPLES", 4)

    # Ingress limits for caller-supplied images.
    max_image_bytes: int = _env_int("MAX_IMAGE_BYTES", 20 * 1024 * 1024)
    fetch_timeout_s: float = _env_float("FETCH_TIMEOUT_S", 15.0)
    max_redirects: int = _env_int("MAX_REDIRECTS", 3)
    # Comma-separated hostname allowlist for URL inputs. Empty means "any
    # public address", which is still SSRF-guarded; set it in production.
    url_allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset(
            h.strip().lower()
            for h in os.environ.get("URL_ALLOWLIST", "").split(",")
            if h.strip()
        )
    )

    warmup: bool = _env_bool("WARMUP", True)
    empty_cache_between_requests: bool = _env_bool("EMPTY_CACHE", True)


SETTINGS = Settings()


# --------------------------------------------------------------- logging
class JsonFormatter(logging.Formatter):
    """One JSON object per line -- EAS ships stdout straight to SLS."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if extra := getattr(record, "extra", None):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), handlers=[_handler], force=True)
log = logging.getLogger("vton")


def _log(level: int, msg: str, **fields: Any) -> None:
    log.log(level, msg, extra={"extra": fields})


# ------------------------------------------------------------ model state
class ModelState:
    """The pipeline plus the lock that keeps it single-flight."""

    def __init__(self) -> None:
        self.pipeline: Optional[TryOnPipeline] = None
        self.gate = asyncio.Semaphore(1)
        self.queued = 0
        self.served = 0
        self.failed = 0
        self.loaded_at: Optional[float] = None


STATE = ModelState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load weights before the socket opens; see the module docstring."""
    started = time.monotonic()
    weights = SETTINGS.weights_dir

    if not os.path.isfile(os.path.join(weights, "model.safetensors")):
        # Fail loudly and immediately. A replica that cannot find its weights
        # must die during startup so EAS reports a deployment failure, rather
        # than come up and 500 on every request.
        raise RuntimeError(
            f"model.safetensors not found under {weights!r}. "
            "Check that the OSS volume is mounted and populated."
        )

    _log(logging.INFO, "loading pipeline", weights_dir=weights, device=SETTINGS.device)
    STATE.pipeline = await anyio.to_thread.run_sync(
        functools.partial(TryOnPipeline, weights_dir=weights, device=SETTINGS.device)
    )
    STATE.loaded_at = time.time()
    _log(
        logging.INFO,
        "pipeline ready",
        load_seconds=round(time.monotonic() - started, 2),
        **_gpu_stats(),
    )

    if SETTINGS.warmup and SETTINGS.device.startswith("cuda"):
        await _warmup()

    yield

    STATE.pipeline = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    _log(logging.INFO, "pipeline released")


async def _warmup() -> None:
    """One synthetic pass so the first real caller does not pay for kernel
    autotuning and allocator growth. Matters far more under scale-to-zero,
    where 'the first caller' is a recurring event rather than a one-off."""
    blank = Image.new("RGB", (768, 1024), (128, 128, 128))
    swatch = Image.new("RGB", (768, 1024), (200, 180, 160))
    started = time.monotonic()
    try:
        await anyio.to_thread.run_sync(
            functools.partial(
                _infer,
                person_image=blank,
                garment_image=swatch,
                category="tops",
                garment_photo_type="model",
                num_samples=1,
                num_timesteps=4,
                guidance_scale=1.5,
                seed=0,
                segmentation_free=True,
            )
        )
        _log(logging.INFO, "warmup complete", seconds=round(time.monotonic() - started, 2))
    except Exception as exc:  # noqa: BLE001 - warmup must never block startup
        _log(logging.WARNING, "warmup failed, continuing", error=str(exc))


def _gpu_stats() -> dict[str, Any]:
    if not torch.cuda.is_available():
        return {"gpu": None}
    return {
        "gpu": torch.cuda.get_device_name(0),
        "vram_allocated_mb": round(torch.cuda.memory_allocated() / 1048576),
        "vram_reserved_mb": round(torch.cuda.memory_reserved() / 1048576),
    }


app = FastAPI(
    title="FASHN VTON v1.5",
    version="1.5.0",
    lifespan=lifespan,
    docs_url=os.environ.get("DOCS_URL") or None,
    redoc_url=None,
)


# ------------------------------------------------------------ image intake
def _reject(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _decode(raw: bytes, label: str) -> Image.Image:
    """Bytes -> RGB PIL image, with the size checked before full decode."""
    if not raw:
        raise _reject(f"{label} is empty")
    if len(raw) > SETTINGS.max_image_bytes:
        raise _reject(
            f"{label} is {len(raw)} bytes, over the {SETTINGS.max_image_bytes} limit",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    try:
        probe = Image.open(io.BytesIO(raw))
        width, height = probe.size
        if width * height > MAX_PIXELS:
            raise _reject(f"{label} is {width}x{height}, over the {MAX_PIXELS} pixel limit")
        probe.close()
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except UnidentifiedImageError:
        raise _reject(f"{label} is not a readable image") from None
    except (OSError, ValueError) as exc:
        raise _reject(f"{label} could not be decoded: {exc}") from None


def _assert_public_host(host: str) -> None:
    """Refuse anything that resolves into private space.

    EAS replicas sit inside a VPC alongside the metadata service and whatever
    else the account runs, so a caller-supplied URL is an SSRF primitive until
    proven otherwise. Every resolved address must be global.
    """
    if SETTINGS.url_allowlist and host.lower() not in SETTINGS.url_allowlist:
        raise _reject(f"host {host!r} is not in URL_ALLOWLIST")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise _reject(f"host {host!r} does not resolve") from None
    if not infos:
        raise _reject(f"host {host!r} does not resolve")
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global or addr.is_multicast:
            raise _reject(f"host {host!r} resolves to non-public address {addr}")


async def _fetch(url: str, label: str) -> bytes:
    """GET an image URL, re-validating the host on every redirect hop."""
    current = url
    async with httpx.AsyncClient(
        timeout=SETTINGS.fetch_timeout_s,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=4),
    ) as client:
        for _ in range(SETTINGS.max_redirects + 1):
            parsed = urlparse(current)
            if parsed.scheme not in {"http", "https"}:
                raise _reject(f"{label} URL must be http or https")
            if not parsed.hostname:
                raise _reject(f"{label} URL has no host")
            _assert_public_host(parsed.hostname)

            try:
                response = await client.get(current, headers={"Accept": "image/*"})
            except httpx.HTTPError as exc:
                raise _reject(f"{label} URL could not be fetched: {exc}") from None

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise _reject(f"{label} URL redirected without a location")
                current = str(response.url.join(location))
                continue

            if response.status_code != 200:
                raise _reject(f"{label} URL returned HTTP {response.status_code}")

            declared = response.headers.get("content-length")
            if declared and int(declared) > SETTINGS.max_image_bytes:
                raise _reject(
                    f"{label} URL declares {declared} bytes, over the limit",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            return response.content

    raise _reject(f"{label} URL exceeded {SETTINGS.max_redirects} redirects")


def _from_data_uri(value: str, label: str) -> Optional[bytes]:
    if not value.startswith("data:"):
        return None
    _, _, payload = value.partition(",")
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, TypeError):
        raise _reject(f"{label} data URI is not valid base64") from None


async def _resolve_image(value: str, label: str) -> Image.Image:
    """A URL, a data URI, or bare base64 -- all three arrive as strings."""
    value = value.strip()
    if not value:
        raise _reject(f"{label} is empty")
    if (raw := _from_data_uri(value, label)) is not None:
        return _decode(raw, label)
    if value.lower().startswith(("http://", "https://")):
        return _decode(await _fetch(value, label), label)
    try:
        return _decode(base64.b64decode(value, validate=True), label)
    except (ValueError, TypeError):
        raise _reject(
            f"{label} must be an http(s) URL, a data URI, or base64-encoded image bytes"
        ) from None


# --------------------------------------------------------------- schemas
class TryOnRequest(BaseModel):
    """JSON body. Images are URLs, data URIs, or raw base64."""

    model_config = {"extra": "forbid"}

    person_image: str = Field(min_length=1)
    garment_image: str = Field(min_length=1)
    category: Category = "tops"
    garment_photo_type: PhotoType = "model"
    num_samples: int = Field(default=1, ge=1)
    num_timesteps: int = Field(default=SETTINGS.default_timesteps, ge=1)
    guidance_scale: float = Field(default=1.5, ge=0.0, le=10.0)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    segmentation_free: bool = True
    response_format: Literal["base64", "binary"] = "base64"

    @model_validator(mode="after")
    def _clamp(self) -> "TryOnRequest":
        # Ceilings are server policy, not caller preference: an unbounded
        # num_samples on a shared GPU is a denial-of-service knob.
        if self.num_samples > SETTINGS.max_samples:
            raise ValueError(f"num_samples may not exceed {SETTINGS.max_samples}")
        if self.num_timesteps > SETTINGS.max_timesteps:
            raise ValueError(f"num_timesteps may not exceed {SETTINGS.max_timesteps}")
        return self


# ------------------------------------------------------------- inference
def _infer(**kwargs: Any) -> list[Image.Image]:
    """Synchronous, GPU-bound, always called in a worker thread."""
    assert STATE.pipeline is not None, "pipeline not loaded"
    with torch.inference_mode():
        result = STATE.pipeline(**kwargs)
    return list(result.images)


async def _run_guarded(request_id: str, params: dict[str, Any]) -> list[Image.Image]:
    """Queue, run single-flight, shed load rather than accumulate a backlog."""
    if STATE.pipeline is None:
        raise _reject("model is not loaded", status.HTTP_503_SERVICE_UNAVAILABLE)
    if STATE.queued >= SETTINGS.max_queue:
        raise _reject(
            f"queue is full ({STATE.queued} waiting); retry shortly",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    STATE.queued += 1
    try:
        with anyio.fail_after(SETTINGS.queue_timeout_s):
            async with STATE.gate:
                started = time.monotonic()
                images = await anyio.to_thread.run_sync(
                    functools.partial(_infer, **params), abandon_on_cancel=False
                )
                _log(
                    logging.INFO,
                    "inference complete",
                    request_id=request_id,
                    seconds=round(time.monotonic() - started, 2),
                    samples=len(images),
                    **_gpu_stats(),
                )
                return images
    except TimeoutError:
        STATE.failed += 1
        raise _reject(
            f"timed out after {SETTINGS.queue_timeout_s}s waiting for the GPU",
            status.HTTP_504_GATEWAY_TIMEOUT,
        ) from None
    finally:
        STATE.queued -= 1
        if SETTINGS.empty_cache_between_requests and torch.cuda.is_available():
            torch.cuda.empty_cache()


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


# --------------------------------------------------------------- routes
@app.get("/health")
async def health() -> JSONResponse:
    """EAS health check.

    Reachable only once the pipeline is loaded, because Uvicorn binds the port
    after lifespan startup finishes. The 503 branch therefore covers shutdown
    and the pathological case, not ordinary cold start.
    """
    ready = STATE.pipeline is not None
    body = {
        "status": "ok" if ready else "loading",
        "model": "fashn-vton-1.5",
        "device": SETTINGS.device,
        "queued": STATE.queued,
        "served": STATE.served,
        "failed": STATE.failed,
        "loaded_at": STATE.loaded_at,
        **_gpu_stats(),
    }
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=code)


@app.post("/v1/tryon")
async def tryon(
    request: Request,
    person_image: Optional[UploadFile] = File(default=None),
    garment_image: Optional[UploadFile] = File(default=None),
    category: Category = Form(default="tops"),
    garment_photo_type: PhotoType = Form(default="model"),
    num_samples: int = Form(default=1),
    num_timesteps: int = Form(default=SETTINGS.default_timesteps),
    guidance_scale: float = Form(default=1.5),
    seed: int = Form(default=42),
    segmentation_free: bool = Form(default=True),
    response_format: Literal["base64", "binary"] = Form(default="base64"),
) -> Response:
    """Person image + garment image -> the person wearing the garment.

    Accepts ``application/json`` (URLs, data URIs or base64) or
    ``multipart/form-data`` (file uploads). The multipart parameters above are
    ignored on the JSON path.
    """
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    started = time.monotonic()

    if content_type == "application/json":
        try:
            payload = TryOnRequest.model_validate(await request.json())
        except ValueError as exc:
            raise _reject(f"invalid JSON body: {exc}", status.HTTP_422_UNPROCESSABLE_ENTITY) from None
        person = await _resolve_image(payload.person_image, "person_image")
        garment = await _resolve_image(payload.garment_image, "garment_image")
        params = payload.model_dump(
            exclude={"person_image", "garment_image", "response_format"}
        )
        wants = payload.response_format

    elif content_type == "multipart/form-data":
        if person_image is None or garment_image is None:
            raise _reject("multipart requests need both person_image and garment_image files")
        person = _decode(await person_image.read(), "person_image")
        garment = _decode(await garment_image.read(), "garment_image")
        try:
            validated = TryOnRequest(
                person_image="x",
                garment_image="x",
                category=category,
                garment_photo_type=garment_photo_type,
                num_samples=num_samples,
                num_timesteps=num_timesteps,
                guidance_scale=guidance_scale,
                seed=seed,
                segmentation_free=segmentation_free,
            )
        except ValueError as exc:
            raise _reject(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from None
        params = validated.model_dump(
            exclude={"person_image", "garment_image", "response_format"}
        )
        wants = response_format

    else:
        raise _reject(
            "Content-Type must be application/json or multipart/form-data",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    _log(
        logging.INFO,
        "request accepted",
        request_id=request_id,
        category=params["category"],
        timesteps=params["num_timesteps"],
        samples=params["num_samples"],
        person_size=person.size,
        garment_size=garment.size,
    )

    try:
        images = await _run_guarded(
            request_id, {"person_image": person, "garment_image": garment, **params}
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - pipeline faults become 500s
        STATE.failed += 1
        _log(logging.ERROR, "inference failed", request_id=request_id, error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"inference failed: {exc}"
        ) from None

    STATE.served += 1
    elapsed = round(time.monotonic() - started, 2)

    if wants == "binary":
        # One image on the wire; callers wanting the whole batch use base64.
        return Response(
            content=_encode_png(images[0]),
            media_type="image/png",
            headers={"x-request-id": request_id, "x-elapsed-seconds": str(elapsed)},
        )

    return JSONResponse(
        {
            "request_id": request_id,
            "model": "fashn-vton-1.5",
            "elapsed_seconds": elapsed,
            "seed": params["seed"],
            "images": [
                f"data:image/png;base64,{base64.b64encode(_encode_png(i)).decode()}"
                for i in images
            ],
        },
        headers={"x-request-id": request_id},
    )


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        {"error": exc.detail, "status": exc.status_code},
        status_code=exc.status_code,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - EAS routes to the container port
        port=_env_int("PORT", 8000),
        workers=1,  # one process, one GPU, one pipeline
        timeout_keep_alive=_env_int("KEEPALIVE_S", 620),
        access_log=False,  # structured logs above already cover it
    )
