"""HTTP surface for the studio (Flask blueprint).

Mirrors the Next.js route handlers one-for-one so the browser contract is the
same one the standalone app used:

    POST /api/studio/upload            multipart -> a URL FASHN can read
    POST /api/studio/generate          submit a job, get a prediction id
    GET  /api/studio/status/<id>       one poll, normalised
    GET  /api/studio/credits           live balance
    GET  /api/studio/files/<key>       serve stored bytes back
    GET  /api/studio/config            control vocabulary + cost tables
    GET  /api/studio/prompt            the composed prompt for a combination

The FASHN key never reaches the browser: every call to the API goes out from
here.
"""
import functools
import json
import os

from flask import Blueprint, Response, request

from . import credits as credits_lib
from . import fashn, images, prompts, storage
from .errors import (
    INPUT_VALIDATION,
    INSUFFICIENT_CREDITS,
    STORAGE_ERROR,
    UNKNOWN,
    StudioError,
    log,
    to_studio_error,
)

MAX_SEED = 4294967295


def json_response(status, payload):
    response = Response(json.dumps(payload, ensure_ascii=False), status=status,
                        mimetype="application/json")
    response.headers["Cache-Control"] = "no-store"
    return response


def api_route(function):
    """Turn any failure into the one error shape the browser knows."""
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except StudioError as exc:
            return json_response(exc.http_status, exc.to_payload())
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("studio.%s failed: %s", function.__name__, exc)
            studio = to_studio_error(exc)
            return json_response(studio.http_status, studio.to_payload())
    return wrapper


ENGINES = ("tryon-max", "edit")


def default_engine():
    """FABRIC_STRATEGY sets the default; each request may override it."""
    return "edit" if (os.environ.get("FABRIC_STRATEGY") or "").strip() == "edit" else "tryon-max"


def fabric_strategy():
    return default_engine()


# ----------------------------------------------------------------- params ---

def _clamp(value, low, high, default):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def read_params(raw):
    """Normalise whatever the browser sent into a complete parameter set."""
    raw = raw if isinstance(raw, dict) else {}

    garment = raw.get("garmentType")
    if garment not in prompts.VOCAB:
        garment = "agbada"

    template = raw.get("fabricTemplate")
    if template not in prompts.TEMPLATE_VALUES:
        template = "universal"

    scope = raw.get("fabricScope")
    if scope not in ("full-set", "outer-only"):
        scope = "full-set"

    output_format = raw.get("outputFormat")
    if output_format not in ("png", "jpeg"):
        output_format = "png"

    return {
        "garmentType": garment,
        "fabricTemplate": template,
        "fabricScope": scope,
        "prompt": raw.get("prompt") or "",
        "promptOverridden": bool(raw.get("promptOverridden")),
        "resolution": credits_lib.normalize_resolution(raw.get("resolution")),
        "generationMode": credits_lib.normalize_mode(raw.get("generationMode")),
        "seed": _clamp(raw.get("seed"), 0, MAX_SEED, 42),
        "numImages": _clamp(raw.get("numImages"), 1, 4, 1),
        "outputFormat": output_format,
        "privacy": bool(raw.get("privacy")),
        # tryon-max replaces one garment region; edit rewrites the whole
        # picture. A two-piece outfit whose lower half must change needs edit.
        "engine": raw.get("engine") if raw.get("engine") in ENGINES else default_engine(),
    }


def prompt_for(params, strategy):
    """Fabric mode composes its prompt unless the customer took the wheel."""
    if params["promptOverridden"] and params["prompt"].strip():
        return params["prompt"].strip()
    if strategy == "edit":
        return prompts.fabric_edit_prompt(
            params["garmentType"], params["fabricTemplate"], params["fabricScope"])
    return prompts.fabric_prompt(
        params["garmentType"], params["fabricTemplate"], params["fabricScope"])


def resolve_image(ref, label, privacy):
    """Turn a client image reference into something FASHN can actually read.

    Hosted https URLs are preferred. Data URIs are used only when privacy mode
    is on, or when this server is not reachable from the public internet --
    the usual case on localhost.
    """
    if not isinstance(ref, dict):
        raise StudioError(
            INPUT_VALIDATION,
            "The %s is missing." % label,
            fix="Upload a %s before generating." % label,
            http_status=400,
        )

    data_uri = ref.get("dataUri")
    if data_uri:
        return data_uri, True

    url = ref.get("url") or ""
    key = ref.get("key")
    needs_inline = privacy or not storage.is_publicly_reachable()

    if not needs_inline and url.startswith("https://"):
        return url, False

    if key:
        stored = storage.get(key)
        if not stored:
            raise StudioError(
                STORAGE_ERROR,
                "The %s is no longer in storage." % label,
                fix="Upload it again.",
                http_status=410,
            )
        return images.to_data_uri(stored["body"], stored["contentType"]), True

    if url.startswith("https://"):
        return url, False

    raise StudioError(
        INPUT_VALIDATION,
        "The %s has no readable source." % label,
        fix="Upload it again.",
        http_status=400,
    )


def assert_affordable(cost):
    """Non-fatal balance check, so "not enough credits" arrives with real numbers."""
    try:
        balance = fashn.credits()
    except StudioError:
        # A flaky balance lookup must never block a generation the customer can
        # probably afford. A hard verdict below still propagates.
        return
    if balance["total"] < cost:
        raise StudioError(
            INSUFFICIENT_CREDITS,
            "This costs %d credits and you have %d. You are %d short."
            % (cost, balance["total"], cost - balance["total"]),
            fix="Drop to a lower quality preset, reduce the image count, or top up at fashn.ai/billing.",
            http_status=402,
        )


# ---------------------------------------------------------------- blueprint --

def create_blueprint():
    bp = Blueprint("studio", __name__)

    @bp.get("/api/studio/config")
    @api_route
    def config():
        return json_response(200, {
            "engines": [
                {"value": "tryon-max", "label": "One garment",
                 "note": "best realism"},
                {"value": "edit", "label": "Whole outfit",
                 "note": "tops + skirts"},
            ],
            "defaultEngine": default_engine(),
            "generationModes": list(credits_lib.GENERATION_MODES),
            # `hasBrief` marks a garment type that carries its own brief rather
            # than the general universal text, so the rail can say which is in play.
            "garmentTypes": [
                dict(garment, hasBrief=prompts.has_garment_brief(garment["value"]))
                for garment in prompts.GARMENT_TYPES
            ],
            "fabricTemplates": prompts.FABRIC_TEMPLATES,
            "fabricScopes": prompts.FABRIC_SCOPES,
            "qualityPresets": credits_lib.QUALITY_PRESETS,
            "creditMatrix": credits_lib.MATRIX,
            "latency": credits_lib.LATENCY,
            "strategy": fabric_strategy(),
            "hostedUploads": storage.is_publicly_reachable(),
            "limits": {
                "maxFileBytes": images.MAX_FILE_BYTES,
                "minDimension": images.MIN_DIMENSION,
                "maxAspectRatio": images.MAX_ASPECT_RATIO,
                "acceptedTypes": list(images.ACCEPTED_TYPES),
            },
        })

    @bp.get("/api/studio/prompt")
    @api_route
    def prompt():
        garment = request.args.get("garment", "agbada")
        template = request.args.get("template", "universal")
        scope = request.args.get("scope", "full-set")
        if garment not in prompts.VOCAB:
            garment = "agbada"
        if template not in prompts.TEMPLATE_VALUES:
            template = "universal"
        if scope not in ("full-set", "outer-only"):
            scope = "full-set"
        return json_response(200, {
            "prompt": prompts.fabric_prompt(garment, template, scope),
            "scopeApplies": prompts.scope_applies(template),
            "garmentApplies": prompts.garment_applies(template),
            "dedicatedBrief": template == "universal" and prompts.has_garment_brief(garment),
        })

    @bp.get("/api/studio/credits")
    @api_route
    def credits():
        return json_response(200, fashn.credits())

    @bp.get("/api/studio/files/<path:key>")
    @api_route
    def files(key):
        stored = storage.get(key)
        if not stored:
            return json_response(404, {"code": "Unknown", "message": "Not found",
                                       "retryable": False})
        response = Response(stored["body"], mimetype=stored["contentType"])
        response.headers["Content-Length"] = str(len(stored["body"]))
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        return response

    @bp.post("/api/studio/upload")
    @api_route
    def upload():
        """multipart: file, slot=product|model, privacy, lossless, crop."""
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            raise StudioError(
                INPUT_VALIDATION,
                "No file arrived with the upload.",
                fix="Pick an image and try again.",
                http_status=400,
            )

        raw = uploaded.read()
        images.validate_file(uploaded.filename, len(raw), uploaded.mimetype or "")

        slot = "model" if request.form.get("slot") == "model" else "product"
        privacy = request.form.get("privacy") == "true"
        lossless = privacy or request.form.get("lossless") == "true"

        crop = None
        raw_crop = (request.form.get("crop") or "").strip()
        if raw_crop:
            try:
                parsed = json.loads(raw_crop)
                if all(isinstance(parsed.get(k), (int, float))
                       for k in ("x", "y", "width", "height")):
                    crop = parsed
            except (ValueError, AttributeError):
                pass  # a malformed crop is ignored rather than failing the upload

        processed = images.preprocess(raw, uploaded.filename, lossless=lossless, crop=crop)

        # The two slots fail in different ways: a photo that is not portrait
        # crops badly, a swatch that is tiny cannot carry a garment. Cropping
        # fixes the first and would only worsen the second, so the kind travels
        # with the hint and the UI offers the crop link only where it helps.
        if slot == "model":
            hint = images.aspect_hint(processed["width"], processed["height"])
            hint_kind = "aspect"
        else:
            hint = images.fabric_hint(processed["width"], processed["height"])
            hint_kind = "resolution"

        payload = {
            "fileName": uploaded.filename,
            "bytes": processed["bytes"],
            "width": processed["width"],
            "height": processed["height"],
            "contentType": processed["contentType"],
            "hint": hint,
            "hintKind": hint_kind if hint else None,
        }

        # Privacy mode keeps the bytes off our disk as well as out of FASHN's history.
        if privacy:
            data_uri = images.to_data_uri(processed["buffer"], processed["contentType"])
            payload.update({"url": "", "dataUri": data_uri, "previewUrl": data_uri})
            return json_response(200, payload)

        key = storage.new_key(slot, processed["extension"])
        stored = storage.put(key, processed["buffer"], processed["contentType"])
        payload.update({
            "key": stored["key"],
            "url": stored["url"],
            "previewUrl": "/api/studio/files/%s" % stored["key"],
        })
        return json_response(200, payload)

    @bp.post("/api/studio/generate")
    @api_route
    def generate():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise StudioError(INPUT_VALIDATION, "The request carried no parameters.",
                              http_status=400)

        operation = body.get("operation") or "tryon"
        if body.get("params") is None:
            raise StudioError(INPUT_VALIDATION, "The request carried no parameters.",
                              http_status=400)

        params = read_params(body.get("params"))
        options = body.get("options") if isinstance(body.get("options"), dict) else {}
        privacy = params["privacy"]
        seed = params["seed"]
        num_images = params["numImages"]

        # ---- post-processing operations run on an existing result -----------
        if operation != "tryon":
            source = body.get("source")
            if not source:
                raise StudioError(
                    INPUT_VALIDATION,
                    "There is no image to work on.",
                    fix="Generate a result first, then run this from the action bar.",
                    http_status=400,
                )

            cost = credits_lib.credit_cost(params["generationMode"], params["resolution"], 1)
            assert_affordable(cost)

            if operation == "upscale":
                model_name = "reframe"
                prediction_id = fashn.run("reframe", {
                    "image": source,
                    "target_aspect_ratio": options.get("target_aspect_ratio") or None,
                    "resolution": params["resolution"],
                    "seed": seed,
                    "output_format": params["outputFormat"],
                    "return_base64": privacy,
                })
            elif operation == "image-to-video":
                model_name = "image-to-video"
                duration = 10 if _clamp(options.get("duration"), 5, 10, 5) == 10 else 5
                prediction_id = fashn.run("image-to-video", {
                    "image": source,
                    "prompt": options.get("prompt") or None,
                    "duration": duration,
                    "resolution": options.get("resolution") or "720p",
                    "seed": seed,
                    "return_base64": privacy,
                })
            elif operation == "swap-face":
                model_name = "model-swap"
                prediction_id = fashn.run("model-swap", {
                    "image": source,
                    "prompt": options.get("prompt") or None,
                    "seed": seed,
                    "output_format": params["outputFormat"],
                    "return_base64": privacy,
                })
            elif operation == "background-change":
                model_name = "background-change"
                prediction_id = fashn.run("background-change", {
                    "image": source,
                    "prompt": options.get("prompt") or "a clean studio backdrop",
                    "seed": seed,
                    "output_format": params["outputFormat"],
                    "return_base64": privacy,
                })
            elif operation == "background-remove":
                model_name = "background-remove"
                prediction_id = fashn.run("background-remove", {
                    "image": source,
                    "output_format": "png",
                    "return_base64": privacy,
                })
            else:
                raise StudioError(INPUT_VALIDATION, 'Unknown operation "%s".' % operation,
                                  http_status=400)

            return json_response(200, {
                "predictionId": prediction_id,
                "creditCost": cost,
                "modelName": model_name,
                "strategy": "n/a",
                "inlined": privacy,
            })

        # ---- the main try-on path -------------------------------------------
        strategy = params["engine"]
        use_edit = strategy == "edit"

        product_value, product_inlined = resolve_image(body.get("product"), "fabric swatch", privacy)
        model_value, model_inlined = resolve_image(body.get("model"), "model image", privacy)

        cost = credits_lib.credit_cost(params["generationMode"], params["resolution"], num_images)
        assert_affordable(cost)

        prompt_text = prompt_for(params, strategy)

        if use_edit:
            # Edit strategy: the person is the canvas, the swatch is the reference.
            prediction_id = fashn.run("edit", {
                "image": model_value,
                "image_context": product_value,
                "prompt": prompt_text,
                "resolution": params["resolution"],
                "generation_mode": params["generationMode"],
                "seed": seed,
                "num_images": num_images,
                "output_format": params["outputFormat"],
                "return_base64": privacy,
            })
        else:
            prediction_id = fashn.run("tryon-max", {
                "product_image": product_value,
                "model_image": model_value,
                "prompt": prompt_text or None,
                "resolution": params["resolution"],
                # Always explicit -- omitting this silently bills as `balanced`.
                "generation_mode": params["generationMode"],
                "seed": seed,
                "num_images": num_images,
                "output_format": params["outputFormat"],
                "return_base64": privacy,
            })

        return json_response(200, {
            "predictionId": prediction_id,
            "creditCost": cost,
            "modelName": "edit" if use_edit else "tryon-max",
            "strategy": strategy,
            "inlined": product_inlined or model_inlined,
        })

    @bp.get("/api/studio/status/<prediction_id>")
    @api_route
    def status(prediction_id):
        try:
            return json_response(200, fashn.status(prediction_id))
        except StudioError as exc:
            payload = exc.to_payload()
            payload["predictionId"] = prediction_id
            return json_response(exc.http_status, payload)

    return bp
