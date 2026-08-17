"""Minimal JSON-over-HTTP helper.

urllib keeps Fabric Studio dependency-free on the network side, matching the
FASHN proxy already in server.py. Responses come back as
(status_code, parsed_json, headers) so providers can read credit headers.
"""
import json
import urllib.error
import urllib.request

from ..errors import ProviderError, RateLimitError, TimeoutError_


def request_json(url, method="GET", payload=None, headers=None, timeout=60):
    body = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "BB-FabricStudio/1.0",
    }
    request_headers.update(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, _parse(raw), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        parsed = _parse(raw)
        if exc.code == 429:
            raise RateLimitError(detail=_detail(parsed, exc.code))
        return exc.code, parsed, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if "timed out" in str(reason).lower():
            raise TimeoutError_(detail="Request to %s timed out" % url)
        raise ProviderError(detail="Network error calling %s: %s" % (url, reason))
    except Exception as exc:  # pragma: no cover - defensive
        raise ProviderError(detail="Unexpected error calling %s: %s" % (url, exc))


def _parse(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"raw": raw[:400].decode("utf-8", "replace")}


def _detail(parsed, status):
    if isinstance(parsed, dict):
        return parsed.get("message") or parsed.get("error") or "HTTP %s" % status
    return "HTTP %s" % status
