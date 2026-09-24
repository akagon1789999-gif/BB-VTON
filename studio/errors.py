"""One error shape for the whole studio.

Every failure that reaches the UI carries a plain-language ``message`` and,
where one exists, a concrete ``fix``. Ported from the Next.js studio's
lib/errors.ts so the browser contract is identical.
"""
import logging

log = logging.getLogger("studio")

# Recognised codes. The browser branches on these, so they are part of the
# contract rather than free text.
INPUT_VALIDATION = "InputValidationError"
INSUFFICIENT_CREDITS = "InsufficientCredits"
RATE_LIMITED = "RateLimited"
TIMEOUT = "Timeout"
NETWORK_ERROR = "NetworkError"
UNAUTHORIZED = "Unauthorized"
CONTENT_MODERATION = "ContentModerationError"
PIPELINE_ERROR = "PipelineError"
STORAGE_ERROR = "StorageError"
UNKNOWN = "Unknown"


class StudioError(Exception):
    """A failure with something a person can actually do about it."""

    def __init__(self, code, message, fix=None, http_status=400,
                 retryable=False, retry_after=None, prediction_id=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after = retry_after
        self.prediction_id = prediction_id

    def to_payload(self):
        payload = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.fix:
            payload["fix"] = self.fix
        if self.retry_after is not None:
            payload["retryAfter"] = self.retry_after
        if self.prediction_id:
            payload["predictionId"] = self.prediction_id
        return payload


NETWORK_SIGNATURES = (
    "timed out", "connection reset", "connection refused", "name resolution",
    "nodename nor servname", "network is unreachable", "broken pipe",
    "eof occurred", "temporary failure",
)


def to_studio_error(exc):
    """Turn anything thrown into something a person can act on."""
    if isinstance(exc, StudioError):
        return exc

    text = str(exc) or ""
    lowered = text.lower()
    if any(signature in lowered for signature in NETWORK_SIGNATURES):
        return StudioError(
            NETWORK_ERROR,
            "The connection to FASHN dropped.",
            fix="Check your network and try again. Your images and settings are kept.",
            http_status=502,
            retryable=True,
        )

    return StudioError(
        UNKNOWN,
        text or "Something went wrong.",
        http_status=500,
        retryable=True,
    )


BYTES_PER_MIB = 1024 * 1024


def format_bytes(count):
    if count < 1024:
        return "%d B" % count
    if count < BYTES_PER_MIB:
        return "%d KB" % round(count / 1024)
    return "%.1f MB" % (count / BYTES_PER_MIB)
