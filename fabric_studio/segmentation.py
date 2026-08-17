"""Human parsing / segmentation service — deliberately independent of FASHN.

The try-on engines in use today (FASHN cloud, and the self-hosted VTON 1.5
later) run their own internal human parsing, so Fabric Studio does not need to
segment anything to produce a result. This module exists so that when we *do*
want our own masks — for tighter garment placement, for skipping the engine's
parsing step, or for a cheaper self-hosted pipeline — it plugs in here and
nothing else changes.

    SegmentationProvider
      +-- NoopSegmentationProvider    (default; engine does its own parsing)
      +-- RemoteSegmentationProvider  (POST an image to a parsing service)

What *does* run today is PersonPhotoValidator: real, cheap, local checks that
catch the photos which reliably fail try-on (too small, too dark, too blurry,
wrong crop) before any paid inference is spent on them.

LABELS is the contract a real implementation must fill.
"""
import threading

from . import config, imaging
from .errors import ValidationError

LABELS = (
    "person",
    "clothing",
    "skin",
    "hair",
    "arms",
    "hands",
    "legs",
    "background",
)


class SegmentationResult(object):
    def __init__(self, provider, masks=None, available=False, notes=None):
        self.provider = provider
        # label -> data URL (or storage path) of an 8-bit mask
        self.masks = dict(masks or {})
        self.available = available
        self.notes = notes or ""

    def to_dict(self):
        return {
            "provider": self.provider,
            "available": self.available,
            "labels": sorted(self.masks.keys()),
            "notes": self.notes,
        }


class SegmentationProvider(object):
    name = "abstract"

    def is_configured(self):
        return True

    def segment(self, image_or_url):
        raise NotImplementedError

    def describe(self):
        return {"provider": self.name, "configured": self.is_configured(), "labels": list(LABELS)}


class NoopSegmentationProvider(SegmentationProvider):
    """Returns no masks. The try-on engine parses the person itself."""

    name = "noop"

    def segment(self, image_or_url):
        return SegmentationResult(
            provider=self.name,
            masks={},
            available=False,
            notes="Human parsing is performed inside the try-on engine; no local masks were produced.",
        )


class RemoteSegmentationProvider(SegmentationProvider):
    """Calls an external human-parsing service.

    Expected contract (mirrors the shape of common parsing servers):
        POST {SEGMENTATION_URL}/parse  {"image": "<data url>"}
        -> {"masks": {"person": "<data url>", "clothing": "...", ...}}

    STATUS: not exercised against a live service in this repo.
    """

    name = "remote"

    def __init__(self, url=None, token=None):
        self._url = url
        self._token = token

    @property
    def url(self):
        return (self._url or config.segmentation_url()).rstrip("/")

    def is_configured(self):
        return bool(self.url)

    def segment(self, image_or_url):
        if not self.is_configured():
            return NoopSegmentationProvider().segment(image_or_url)
        from .virtual_tryon.http import request_json

        headers = {}
        token = self._token or config.segmentation_token()
        if token:
            headers["Authorization"] = "Bearer %s" % token
        payload = {"image": _as_data_url(image_or_url)}
        status, body, _headers = request_json(
            "%s/parse" % self.url, method="POST", payload=payload, headers=headers, timeout=60
        )
        if status >= 400 or not isinstance(body, dict):
            return SegmentationResult(
                provider=self.name, masks={}, available=False,
                notes="Segmentation service returned %s; continuing without local masks." % status,
            )
        masks = {k: v for k, v in (body.get("masks") or {}).items() if k in LABELS}
        return SegmentationResult(
            provider=self.name, masks=masks, available=bool(masks),
            notes="Masks produced by the remote parsing service.",
        )


def _as_data_url(image_or_url):
    if isinstance(image_or_url, str):
        return image_or_url
    return imaging.to_data_url(image_or_url, "JPEG", 88)


_lock = threading.Lock()
_instances = {}


def get_segmentation_provider(name=None):
    resolved = (name or config.segmentation_provider_name() or "noop").lower()
    with _lock:
        instance = _instances.get(resolved)
        if instance is None:
            instance = RemoteSegmentationProvider() if resolved == "remote" else NoopSegmentationProvider()
            _instances[resolved] = instance
        return instance


def reset_segmentation_providers():
    with _lock:
        _instances.clear()


# ------------------------------------------------------ person photo gate ---
class PersonPhotoValidator(object):
    """Cheap local checks that run before any paid inference.

    Errors block the generation; warnings are surfaced to the user but let
    them continue, because "unusual" is not the same as "will fail".
    """

    def validate(self, image):
        imaging.require_pillow()
        errors = []
        warnings = []

        width, height = image.size
        min_edge = config.person_image_min_edge()
        if min(width, height) < min_edge:
            errors.append(
                "Your photo is a bit small (%dx%d). Please use one at least %dpx on the short side."
                % (width, height, min_edge)
            )

        ratio = height / float(width or 1)
        if ratio < 0.75:
            warnings.append(
                "This looks like a wide photo. A full-length, portrait-orientation shot gives the best fit."
            )
        elif ratio > 3.2:
            warnings.append("This photo is unusually tall and narrow — the outfit may be cropped.")

        brightness = imaging.brightness_score(image)
        if brightness < 0.12:
            errors.append("Your photo is too dark to work with. Please retake it in brighter light.")
        elif brightness < 0.24:
            warnings.append("Your photo is quite dark — a brighter, evenly-lit shot gives a cleaner result.")
        elif brightness > 0.95:
            warnings.append("Your photo is very bright and may have lost detail.")

        sharpness = imaging.sharpness_score(image)
        if sharpness < 0.035:
            warnings.append("Your photo looks soft or blurry — a sharper photo gives a better result.")

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "metrics": {
                "width": width,
                "height": height,
                "brightness": round(brightness, 3),
                "sharpness": round(sharpness, 3),
                "aspectRatio": round(ratio, 3),
            },
        }

    def prepare(self, value):
        """Validate and normalise an uploaded person photo.

        Returns (data_url, report). Raises ValidationError when unusable.
        Downscaling here is a direct cost lever: try-on engines work from ~1-1.5k
        pixels, so shipping a 12MP phone photo only buys upload time.
        """
        image, _raw = imaging.load_image(value)
        report = self.validate(image)
        if not report["ok"]:
            raise ValidationError(report["errors"][0], detail="; ".join(report["errors"]))
        normalized = imaging.fit_within(imaging.to_rgb(image), config.person_image_max_edge())
        report["metrics"]["normalizedWidth"] = normalized.size[0]
        report["metrics"]["normalizedHeight"] = normalized.size[1]
        return imaging.to_data_url(normalized, "JPEG", 90), report


validator = PersonPhotoValidator()
