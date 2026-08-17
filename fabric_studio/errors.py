"""Error types and user-facing message mapping.

Rule of the feature: the browser only ever sees `user_message`. The technical
detail is logged server-side and is only attached to responses when
FABRIC_STUDIO_DEBUG is on (development).
"""
import logging

from . import config

log = logging.getLogger("fabric_studio")


class FabricStudioError(Exception):
    """Base error carrying a safe message for the user and a private detail."""

    status = 400
    code = "fabric_studio_error"
    user_message = "Something went wrong. Please try again."

    def __init__(self, user_message=None, detail=None, status=None, code=None):
        self.user_message = user_message or self.user_message
        self.detail = detail or self.user_message
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code
        super(FabricStudioError, self).__init__(self.detail)

    def to_payload(self):
        payload = {"message": self.user_message, "code": self.code}
        if config.debug_errors():
            payload["detail"] = str(self.detail)
        return payload


class ValidationError(FabricStudioError):
    status = 400
    code = "validation_error"


class NotFoundError(FabricStudioError):
    status = 404
    code = "not_found"
    user_message = "We couldn't find that item."


class ImageError(FabricStudioError):
    status = 400
    code = "image_error"
    user_message = "We couldn't read that image. Please upload a JPG, PNG, or WEBP photo."


class DependencyError(FabricStudioError):
    status = 503
    code = "dependency_unavailable"
    user_message = "Fabric Studio is temporarily unavailable. Please try again shortly."


class ProviderError(FabricStudioError):
    status = 502
    code = "provider_error"
    user_message = "We couldn't generate your outfit this time. Please try again."


class ProviderConfigError(ProviderError):
    code = "provider_not_configured"
    user_message = "Outfit generation isn't available right now. Please try again later."


class RateLimitError(ProviderError):
    status = 429
    code = "rate_limited"
    user_message = "We're generating a lot of outfits right now. Please try again in a moment."


class TimeoutError_(ProviderError):
    status = 504
    code = "timeout"
    user_message = "Your outfit is taking longer than expected. Please try again."


# FASHN runtime error names (documented in the FASHN API reference) mapped to
# messages a customer can act on. Anything unmapped falls back to the generic
# provider message — raw API text is never shown.
RUNTIME_ERROR_MESSAGES = {
    "ImageLoadError": "We couldn't read one of the images. Please upload a different photo and try again.",
    "ContentModerationError": "That photo couldn't be used for a try-on. Please upload a clear, fully-clothed photo.",
    "PoseError": "We couldn't detect a full body in your photo. Try a straight-on, full-length shot in good light.",
    "InputValidationError": "We couldn't prepare that outfit. Please pick a different fabric or outfit and try again.",
    "ThirdPartyError": "Our styling engine refused that combination. Please try a different fabric or outfit.",
    "3rdPartyProviderError": "Our styling engine refused that combination. Please try a different fabric or outfit.",
    "PipelineError": "Our styling engine hit a snag. Please try again — you won't be charged for a failed run.",
    "InternalServerError": "Our styling engine is having a moment. Please try again shortly.",
    "PollingTimeout": "Your outfit is taking longer than expected. Please try again.",
}


def friendly_runtime_message(error_name):
    return RUNTIME_ERROR_MESSAGES.get(
        error_name, "We couldn't generate your outfit this time. Please try again."
    )


def log_exception(context, exc):
    log.exception("fabric_studio:%s failed: %s", context, exc)
