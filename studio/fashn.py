"""FASHN client.

Every endpoint parameter lives inside ``inputs``. None of them are top-level
fields on the request body -- that is the single most common way to get a
silently-ignored parameter out of this API.

Requests retry on 429 and 5xx with bounded backoff, and every failure comes
back as a StudioError carrying a message and a fix.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import (
    CONTENT_MODERATION,
    INPUT_VALIDATION,
    INSUFFICIENT_CREDITS,
    NETWORK_ERROR,
    PIPELINE_ERROR,
    RATE_LIMITED,
    UNAUTHORIZED,
    UNKNOWN,
    StudioError,
    to_studio_error,
)

DEFAULT_BASE = "https://api.fashn.ai/v1"
MAX_ATTEMPTS = 3

TERMINAL_STATUSES = ("completed", "failed", "canceled")


def api_key():
    key = (os.environ.get("FASHN_API_KEY") or "").strip()
    if not key:
        raise StudioError(
            UNAUTHORIZED,
            "FASHN_API_KEY is not set.",
            fix="Add your key from fashn.ai/settings to .env, then restart the server.",
            http_status=500,
        )
    return key


def base_url():
    return (os.environ.get("FASHN_API_BASE") or DEFAULT_BASE).rstrip("/")


def _parse(raw):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return raw.decode("utf-8", "replace")


def map_api_error(status, body, retry_after=None):
    """Normalise FASHN's several error shapes into one StudioError."""
    raw = body
    if isinstance(body, dict):
        raw = body.get("error", body.get("detail"))

    name = ""
    detail = ""
    if isinstance(raw, dict):
        name = str(raw.get("name") or "")
        detail = str(raw.get("message") or "")
    elif isinstance(raw, str):
        detail = raw

    if status in (401, 403):
        return StudioError(
            UNAUTHORIZED,
            "FASHN rejected the API key.",
            fix="Check FASHN_API_KEY in .env, then restart the server.",
            http_status=401,
        )

    if status == 429:
        return StudioError(
            RATE_LIMITED,
            "FASHN is rate limiting this key.",
            fix="Retrying automatically.",
            http_status=429,
            retryable=True,
            retry_after=retry_after if retry_after is not None else 5,
        )

    if name == "InputValidationError" or re.search(r"validation", detail, re.I):
        return StudioError(
            INPUT_VALIDATION,
            detail or "FASHN rejected one of the images.",
            fix="Images must be under 30 MB, at least 15 x 15 px, and between 1:16 and 16:1.",
            http_status=422,
        )

    if re.search(r"credit", name, re.I) or re.search(r"credit", detail, re.I):
        return StudioError(
            INSUFFICIENT_CREDITS,
            detail or "Not enough credits for this generation.",
            fix="Top up at fashn.ai/billing, or drop the quality preset to lower the cost.",
            http_status=402,
        )

    if re.search(r"moderation|nsfw|content", name, re.I):
        return StudioError(
            CONTENT_MODERATION,
            detail or "FASHN flagged one of the images.",
            fix="Try a different photo. Full-body, clothed, well-lit images work best.",
            http_status=422,
        )

    if status >= 500:
        return StudioError(
            PIPELINE_ERROR,
            detail or "FASHN had a server error.",
            fix="Retrying automatically.",
            http_status=status,
            retryable=True,
        )

    return StudioError(UNKNOWN, detail or "FASHN returned %s." % status, http_status=status)


def _request(method, path, payload=None, timeout=60):
    """One request with bounded retries on 429 and 5xx.

    Returns (parsed_body, headers). The headers carry `x-fashn-credits-used`,
    which is the only authoritative figure for what a job actually cost — our
    own table is an estimate shown before the run.
    """
    url = base_url() + path
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        body = None
        headers = {
            "Authorization": "Bearer %s" % api_key(),
            "Accept": "application/json",
            "User-Agent": "BB-Studio/1.0",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return _parse(response.read()), dict(response.headers)
        except urllib.error.HTTPError as exc:
            parsed = _parse(exc.read())
            retry_after = None
            header = (exc.headers or {}).get("Retry-After")
            if header:
                try:
                    retry_after = int(float(header))
                except (TypeError, ValueError):
                    retry_after = None
            error = map_api_error(exc.code, parsed, retry_after)
            if error.retryable and attempt < MAX_ATTEMPTS:
                last_error = error
                time.sleep(error.retry_after or 2 ** attempt)
                continue
            raise error
        except urllib.error.URLError as exc:
            error = StudioError(
                NETWORK_ERROR,
                "The connection to FASHN dropped.",
                fix="Check the server's network and try again. Nothing you uploaded was lost.",
                http_status=502,
                retryable=True,
            )
            if attempt < MAX_ATTEMPTS:
                last_error = error
                time.sleep(2 ** attempt)
                continue
            raise error
        except Exception as exc:  # pragma: no cover - defensive
            error = to_studio_error(exc)
            if error.retryable and attempt < MAX_ATTEMPTS:
                last_error = error
                time.sleep(2 ** attempt)
                continue
            raise error

    raise last_error or StudioError(UNKNOWN, "Request failed.", http_status=500)


def _compact(inputs):
    """Strip None so we never send a key FASHN would read as an explicit null."""
    return {key: value for key, value in inputs.items() if value is not None}


def _as_renderable_image(value):
    """Bare base64 out of privacy mode becomes a data URI the browser can render."""
    if not isinstance(value, str):
        return value
    if re.match(r"^(https?:|data:)", value, re.I):
        return value
    mime = "image/png" if value.startswith("iVBOR") else "image/jpeg"
    return "data:%s;base64,%s" % (mime, value)


def run(model_name, inputs):
    """POST /v1/run -- submit a job, get a prediction id back."""
    result, _headers = _request(
        "POST", "/run", {"model_name": model_name, "inputs": _compact(inputs)})
    result = result if isinstance(result, dict) else {}

    if result.get("error"):
        raise map_api_error(422, {"error": result["error"]})

    prediction_id = result.get("id")
    if not prediction_id:
        raise StudioError(
            UNKNOWN,
            "FASHN accepted the job but returned no prediction id.",
            http_status=502,
            retryable=True,
        )
    return prediction_id


def status(prediction_id):
    """GET /v1/status/{id} -- one poll."""
    result, headers = _request(
        "GET",
        "/status/%s" % urllib.parse.quote(str(prediction_id), safe=""),
        timeout=20,
    )
    result = result if isinstance(result, dict) else {}

    raw_error = result.get("error")
    if raw_error is None:
        error = None
    elif isinstance(raw_error, str):
        error = raw_error
    elif isinstance(raw_error, dict):
        error = raw_error.get("message") or raw_error.get("name") or "Generation failed."
    else:
        error = "Generation failed."

    # `output` is always an array on success -- render all of it.
    raw_output = result.get("output")
    if isinstance(raw_output, list):
        output = [_as_renderable_image(item) for item in raw_output]
    elif raw_output:
        output = [_as_renderable_image(raw_output)]
    else:
        output = None

    # Case-insensitive: urllib normalises, but a proxy may not.
    used = None
    for name, value in (headers or {}).items():
        if name.lower() == "x-fashn-credits-used":
            try:
                used = float(value)
            except (TypeError, ValueError):
                used = None
            break

    return {
        "id": result.get("id") or prediction_id,
        "status": result.get("status") or "processing",
        # What the job actually cost, straight from FASHN. None until it lands.
        "creditsUsed": used,
        # With return_base64 the entries are bare base64, not data URIs. Make
        # them renderable so privacy mode behaves like every other result.
        "output": output,
        "error": error,
    }


def credits():
    """GET /v1/credits -- live balance for the header."""
    result, _headers = _request("GET", "/credits", timeout=15)
    result = result if isinstance(result, dict) else {}

    node = result.get("credits", result)

    if isinstance(node, (int, float)):
        return {"total": float(node), "subscription": float(node), "onDemand": 0}

    if not isinstance(node, dict):
        node = {}

    def _number(value, fallback=0.0):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback
        return number if number == number else fallback  # filters NaN

    subscription = _number(node.get("subscription"))
    on_demand = _number(node.get("on_demand", node.get("onDemand")))
    total = _number(node.get("total"), subscription + on_demand)

    return {"total": total, "subscription": subscription, "onDemand": on_demand}
