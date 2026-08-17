"""Generation pipeline and history.

    person photo -> validate/normalise
                 -> processed fabric (cached)
                 -> composed garment template (cached)
                 -> segmentation hook (no-op by default)
                 -> VirtualTryOnProvider.generate + poll
                 -> store result -> history record

The pipeline runs on a background thread and writes its real stage into the
generation record, so the UI reports what is actually happening instead of an
invented progress bar. Every timing needed to benchmark cost per generation is
recorded on the record.
"""
import threading
import time
import urllib.error
import urllib.request

from . import catalog, config, garment_composer, imaging, segmentation, storage
from .errors import FabricStudioError, ProviderError, ValidationError, log, log_exception
from .virtual_tryon import STATUS_COMPLETED, STATUS_FAILED, TryOnRequest, get_provider

GENERATION_STORE = storage.JsonStore(
    "fabric_generations.json",
    key_field="id",
    indexes=("user_id",),
)

# Real pipeline stages. The UI maps these to copy; it never invents percentages.
STAGE_QUEUED = "queued"
STAGE_FABRIC = "preparing_fabric"
STAGE_GARMENT = "composing_garment"
STAGE_SEGMENT = "reading_photo"
STAGE_SUBMIT = "submitting"
STAGE_RENDER = "rendering"
STAGE_FINALIZE = "finalizing"
STAGE_DONE = "completed"
STAGE_FAILED = "failed"

STAGE_LABELS = {
    STAGE_QUEUED: "Getting ready…",
    STAGE_FABRIC: "Preparing fabric…",
    STAGE_GARMENT: "Cutting your outfit…",
    STAGE_SEGMENT: "Reading your photo…",
    STAGE_SUBMIT: "Sending to the studio…",
    STAGE_RENDER: "Fitting the outfit…",
    STAGE_FINALIZE: "Finalising your look…",
    STAGE_DONE: "Done",
    STAGE_FAILED: "Something went wrong",
}

MODE_FAST = "fast"
MODE_DESIGN = "design"

MAX_CONCURRENT = 4
_slots = threading.Semaphore(MAX_CONCURRENT)
POLL_INTERVAL_SECONDS = 2.0
RESULT_MAX_BYTES = 16 * 1024 * 1024


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------- API ----
def start_generation(person_image, fabric_id, outfit_id, user_id, mode=MODE_FAST,
                     prompt=None, options=None, run_async=True):
    """Validate inputs, create the history record, and kick off the pipeline."""
    imaging.require_pillow()
    fabric = catalog.require_fabric(fabric_id)
    outfit = catalog.require_outfit(outfit_id)
    mode = MODE_DESIGN if mode == MODE_DESIGN else MODE_FAST

    prompt = (prompt or "").strip()[:500]
    if mode == MODE_FAST:
        # MODE A never spends a generative step on free-text styling.
        prompt = ""

    person_data_url, photo_report = segmentation.validator.prepare(person_image)

    record = {
        "id": storage.new_id("gen"),
        "user_id": user_id or "anonymous",
        "fabric_id": fabric["id"],
        "fabric_name": fabric.get("name"),
        "outfit_id": outfit["id"],
        "outfit_name": outfit.get("name"),
        "mode": mode,
        "prompt": prompt,
        "status": "processing",
        "stage": STAGE_QUEUED,
        "stage_label": STAGE_LABELS[STAGE_QUEUED],
        "provider": get_provider().name,
        "provider_generation_id": None,
        "result_image_url": None,
        "person_image_stored": False,
        "error": None,
        "warnings": photo_report.get("warnings", []),
        "created_at": now(),
        "updated_at": now(),
        "metadata": {
            "photo": photo_report.get("metrics", {}),
            "garmentType": outfit.get("garment_type"),
            "templateId": outfit.get("template_id"),
        },
        "timings": {},
    }
    GENERATION_STORE.insert(record)
    _trim_history()

    if run_async:
        thread = threading.Thread(
            target=_run_pipeline,
            args=(record["id"], person_data_url, fabric["id"], outfit["id"], mode, prompt, dict(options or {})),
            name="fabric-studio-%s" % record["id"],
            daemon=True,
        )
        thread.start()
    else:
        _run_pipeline(record["id"], person_data_url, fabric["id"], outfit["id"], mode, prompt, dict(options or {}))
    return GENERATION_STORE.get(record["id"])


def get_generation(generation_id, user_id=None):
    record = GENERATION_STORE.get(generation_id)
    if record is None:
        return None
    if user_id and record.get("user_id") not in (user_id, "anonymous"):
        # Do not leak another client's generation.
        return None
    return record


def list_generations(user_id, limit=40):
    records = GENERATION_STORE.find_by("user_id", user_id) if user_id else []
    records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return records[:max(1, min(limit, 200))]


def generation_view(record):
    if not record:
        return None
    return {
        "generationId": record.get("id"),
        "status": record.get("status"),
        "stage": record.get("stage"),
        "stageLabel": record.get("stage_label") or STAGE_LABELS.get(record.get("stage"), ""),
        "resultImageUrl": record.get("result_image_url"),
        "fabricId": record.get("fabric_id"),
        "fabricName": record.get("fabric_name"),
        "outfitId": record.get("outfit_id"),
        "outfitName": record.get("outfit_name"),
        "mode": record.get("mode"),
        "prompt": record.get("prompt") or "",
        "provider": record.get("provider"),
        "error": record.get("error"),
        "warnings": record.get("warnings") or [],
        "createdAt": record.get("created_at"),
        "processingTimeMs": (record.get("timings") or {}).get("totalMs"),
        "garmentImageUrl": (record.get("metadata") or {}).get("garmentImageUrl"),
    }


def stats():
    """Aggregates for benchmarking cost/latency/failure rate (admin only)."""
    records = GENERATION_STORE.all()
    total = len(records)
    completed = [r for r in records if r.get("status") == "completed"]
    failed = [r for r in records if r.get("status") == "failed"]
    durations = [(r.get("timings") or {}).get("totalMs") for r in completed]
    durations = [d for d in durations if isinstance(d, (int, float))]
    credits = [(r.get("metadata") or {}).get("creditsUsed") for r in completed]
    credits = [c for c in credits if isinstance(c, (int, float))]
    by_outfit = {}
    by_fabric = {}
    for record in records:
        by_outfit[record.get("outfit_name") or "?"] = by_outfit.get(record.get("outfit_name") or "?", 0) + 1
        by_fabric[record.get("fabric_name") or "?"] = by_fabric.get(record.get("fabric_name") or "?", 0) + 1
    return {
        "total": total,
        "completed": len(completed),
        "failed": len(failed),
        "failureRate": round(len(failed) / float(total), 3) if total else 0.0,
        "avgProcessingMs": int(sum(durations) / len(durations)) if durations else None,
        "totalCreditsUsed": round(sum(credits), 2) if credits else None,
        "byOutfit": sorted(by_outfit.items(), key=lambda kv: -kv[1])[:10],
        "byFabric": sorted(by_fabric.items(), key=lambda kv: -kv[1])[:10],
    }


# -------------------------------------------------------------- pipeline ----
def _set_stage(generation_id, stage, **extra):
    updates = {"stage": stage, "stage_label": STAGE_LABELS.get(stage, ""), "updated_at": now()}
    updates.update(extra)
    GENERATION_STORE.update(generation_id, updates)


def _run_pipeline(generation_id, person_data_url, fabric_id, outfit_id, mode, prompt, options):
    started = time.time()
    timings = {}
    with _slots:
        try:
            # 1. Fabric: reuse the cached processed asset whenever possible.
            _set_stage(generation_id, STAGE_FABRIC)
            step = time.time()
            fabric = catalog.ensure_fabric_processed(fabric_id)
            timings["fabricMs"] = int((time.time() - step) * 1000)

            # 2. Garment: pour the fabric into the outfit template (cached).
            _set_stage(generation_id, STAGE_GARMENT)
            step = time.time()
            outfit = catalog.require_outfit(outfit_id)
            garment = garment_composer.compose(fabric, outfit)
            timings["garmentMs"] = int((time.time() - step) * 1000)
            timings["garmentCached"] = garment["cached"]

            # 3. Person: segmentation hook (no-op unless a parser is configured).
            _set_stage(generation_id, STAGE_SEGMENT)
            step = time.time()
            parsing = segmentation.get_segmentation_provider().segment(person_data_url)
            timings["segmentationMs"] = int((time.time() - step) * 1000)

            # 4. Hand off to whichever try-on engine is configured.
            _set_stage(generation_id, STAGE_SUBMIT)
            provider = get_provider()
            request = _build_request(
                generation_id, person_data_url, fabric, outfit, garment, parsing, mode, prompt, options
            )
            step = time.time()
            result = provider.generate(request)
            GENERATION_STORE.update(generation_id, {
                "provider": provider.name,
                "provider_generation_id": result.generation_id,
                "updated_at": now(),
            })

            if not result.is_terminal:
                _set_stage(generation_id, STAGE_RENDER)
                result = _poll_until_terminal(provider, result)
            timings["providerMs"] = int((time.time() - step) * 1000)

            if result.status != STATUS_COMPLETED or not result.result_image:
                raise ProviderError(
                    result.error or "We couldn't generate your outfit this time. Please try again.",
                    detail="Provider %s returned %s (%s)" % (provider.name, result.status, result.error_code),
                )

            # 5. Store the result ourselves so it outlives the provider's CDN.
            _set_stage(generation_id, STAGE_FINALIZE)
            step = time.time()
            stored_url = _store_result(generation_id, result.result_image)
            timings["downloadMs"] = int((time.time() - step) * 1000)
            timings["totalMs"] = int((time.time() - started) * 1000)

            metadata = GENERATION_STORE.get(generation_id).get("metadata") or {}
            metadata.update({
                "garmentImageUrl": garment["url"],
                "garmentCached": garment["cached"],
                "model": result.metadata.get("model"),
                "creditsUsed": result.metadata.get("creditsUsed"),
                "segmentation": parsing.to_dict(),
                "fabricPattern": ((fabric.get("processed") or {}).get("metadata") or {}).get("patternType"),
            })
            GENERATION_STORE.update(generation_id, {
                "status": "completed",
                "stage": STAGE_DONE,
                "stage_label": STAGE_LABELS[STAGE_DONE],
                "result_image_url": stored_url,
                "provider_result_url": result.result_image,
                "metadata": metadata,
                "timings": timings,
                "updated_at": now(),
            })
        except FabricStudioError as exc:
            log_exception("generation:%s" % generation_id, exc)
            _fail(generation_id, exc.user_message, timings, started, code=exc.code)
        except Exception as exc:  # pragma: no cover - defensive
            log_exception("generation:%s" % generation_id, exc)
            _fail(generation_id, "We couldn't generate your outfit this time. Please try again.",
                  timings, started, code="unexpected_error")


def _build_request(generation_id, person_data_url, fabric, outfit, garment, parsing, mode, prompt, options):
    metadata = (fabric.get("processed") or {}).get("metadata") or {}
    garment_metadata = {
        "category": outfit.get("garment_type") or "one-pieces",
        "maskType": outfit.get("mask_type"),
        "fabricName": fabric.get("name"),
        "fabricDescription": metadata.get("description"),
        "patternType": fabric.get("pattern_type") or metadata.get("patternType"),
        "dominantColors": [c.get("name") for c in metadata.get("dominantColors", [])],
    }
    if parsing.available:
        garment_metadata["masks"] = parsing.masks

    request_options = {
        "mode": "quality" if mode == MODE_DESIGN else "fast",
        "output_format": "jpeg",
    }
    request_options.update(options or {})
    if mode == MODE_DESIGN:
        # MODE B: the outfit's own description plus whatever the user asked for.
        pieces = [outfit.get("default_prompt") or "", prompt]
        request_options["prompt"] = ", ".join([p for p in pieces if p]).strip(", ")

    return TryOnRequest(
        person_image=person_data_url,
        garment_image=_garment_reference(garment),
        garment_metadata=garment_metadata,
        options=request_options,
        request_id=generation_id,
    )


def _garment_reference(garment):
    """Give the provider the garment as a data URL.

    A local /media path is not reachable from a cloud provider, and this app
    has no public asset host of its own, so the composed garment travels inline.
    """
    path = storage.media_path(garment["path"])
    with open(str(path), "rb") as handle:
        return imaging.to_data_url(handle.read(), "JPEG")


def _poll_until_terminal(provider, result):
    deadline = time.time() + config.vton_timeout_seconds()
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        polled = provider.get_status(result.generation_id)
        if polled.is_terminal:
            return polled
        result = polled
    result.status = STATUS_FAILED
    result.error = "Your outfit is taking longer than expected. Please try again."
    result.error_code = "PollingTimeout"
    return result


def _store_result(generation_id, url):
    """Copy the provider's output into our own media storage."""
    if url.startswith("data:"):
        raw = imaging.decode_data_url(url, max_bytes=RESULT_MAX_BYTES)
    elif url.startswith("/media/"):
        return url
    else:
        raw = _download(url)
    image = imaging.open_image(raw)
    relative = "generations/%s.jpg" % generation_id
    storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))
    return storage.media_url(relative)


def _download(url):
    if not url.startswith("https://") and not url.startswith("http://"):
        raise ProviderError(detail="Refusing to download non-http result URL %r" % url[:80])
    request = urllib.request.Request(url, headers={"User-Agent": "BB-FabricStudio/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(RESULT_MAX_BYTES + 1)
    except urllib.error.URLError as exc:
        raise ProviderError(
            "We generated your outfit but couldn't save it. Please try again.",
            detail="Result download failed: %s" % exc,
        )
    if len(raw) > RESULT_MAX_BYTES:
        raise ProviderError(detail="Result image exceeded %d bytes" % RESULT_MAX_BYTES)
    return raw


def _fail(generation_id, message, timings, started, code=None):
    timings["totalMs"] = int((time.time() - started) * 1000)
    GENERATION_STORE.update(generation_id, {
        "status": "failed",
        "stage": STAGE_FAILED,
        "stage_label": STAGE_LABELS[STAGE_FAILED],
        "error": message,
        "error_code": code,
        "timings": timings,
        "updated_at": now(),
    })


def _trim_history():
    try:
        removed = GENERATION_STORE.trim_to(config.history_limit(), "created_at")
        if removed:
            log.info("Trimmed %d old Fabric Studio generations", removed)
    except Exception as exc:  # pragma: no cover
        log.warning("Could not trim generation history: %s", exc)
