"""Environment-driven configuration for Fabric Studio.

Everything the feature needs to be switched (provider, model names, limits) is
read from the environment here so no other module hard-codes a provider or a
FASHN-specific assumption. server.py already loads .env before importing this
package, so plain os.environ reads are enough.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def _env_int(name, default):
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _env_bool(name, default=False):
    value = _env(name).lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def data_dir():
    """Same convention as server.py: DATA_DIR or the repo root."""
    return Path(_env("DATA_DIR") or str(ROOT)).resolve()


# ---------------------------------------------------------------- provider ---
# fashn_api (default) | mock | fashn_vton_15
def vton_provider_name():
    return _env("VTON_PROVIDER", "fashn_api").lower()


def fashn_api_key():
    return _env("FASHN_API_KEY")


def fashn_api_base():
    return _env("FASHN_API_BASE", "https://api.fashn.ai/v1")


# Model used for MODE A (fast fabric try-on). tryon-v1.6 is the low-cost model
# and is the only try-on model that accepts an explicit garment category and a
# flat-lay photo hint, which is exactly what the composed garment template is.
def vton_fast_model():
    return _env("VTON_FAST_MODEL", "tryon-v1.6")


# Model used for MODE B / quality runs. tryon-max is the flagship model and
# accepts a refinement prompt alongside the product image.
def vton_quality_model():
    return _env("VTON_QUALITY_MODEL", "tryon-max")


def vton_timeout_seconds():
    return _env_int("VTON_TIMEOUT_SECONDS", 240)


# ------------------------------------------------- self-hosted VTON 1.5 ------
def vton15_url():
    return _env("FASHN_VTON15_URL")


def vton15_token():
    return _env("FASHN_VTON15_TOKEN")


# ------------------------------------------------------------ segmentation ---
# noop (default) | remote
def segmentation_provider_name():
    return _env("SEGMENTATION_PROVIDER", "noop").lower()


def segmentation_url():
    return _env("SEGMENTATION_URL")


def segmentation_token():
    return _env("SEGMENTATION_TOKEN")


# ------------------------------------------------------------ processing ----
def fabric_normalized_size():
    """Long edge of the normalized fabric asset, in pixels."""
    return _env_int("FABRIC_NORMALIZED_SIZE", 1024)


def fabric_thumbnail_size():
    return _env_int("FABRIC_THUMBNAIL_SIZE", 400)


def garment_render_size():
    """Long edge of the composed garment image sent to the VTON provider.

    Try-on providers downscale their inputs anyway; sending more pixels costs
    upload time without improving the result.
    """
    return _env_int("GARMENT_RENDER_SIZE", 1024)


def person_image_max_edge():
    return _env_int("PERSON_IMAGE_MAX_EDGE", 1536)


def person_image_min_edge():
    return _env_int("PERSON_IMAGE_MIN_EDGE", 400)


def max_upload_bytes():
    return _env_int("FABRIC_MAX_UPLOAD_BYTES", 12 * 1024 * 1024)


# -------------------------------------------------------------- importer ----
def import_allowed_hosts():
    """Allow-list for the catalogue importer. Empty = importer disabled."""
    raw = _env("FABRIC_IMPORT_ALLOWED_HOSTS")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def import_max_bytes():
    return _env_int("FABRIC_IMPORT_MAX_BYTES", 8 * 1024 * 1024)


def import_timeout_seconds():
    return _env_int("FABRIC_IMPORT_TIMEOUT_SECONDS", 20)


def import_user_agent():
    return _env("FABRIC_IMPORT_USER_AGENT", "BB-Fabric-Catalogue-Importer/1.0 (+contact: admin)")


# ------------------------------------------------------------------ misc -----
def history_limit():
    return _env_int("FABRIC_HISTORY_LIMIT", 200)


def debug_errors():
    """When on, API error payloads include the technical detail as well."""
    return _env_bool("FABRIC_STUDIO_DEBUG", False)


# ------------------------------------------------------------- strategies ---
# How the garment reaches the try-on model:
#   fabric   - send the fabric itself as the product image and describe the
#              garment in the prompt (FASHN's own recommendation; default)
#   template - send a flat-lay composed from the fabric and an outfit template
#              (deterministic and cheap, but the garment shape is ours, not the
#              model's)
#   edit     - send the person as the image and the fabric as image_context
def vton_garment_strategy():
    value = _env("VTON_GARMENT_STRATEGY", "fabric").lower()
    return value if value in ("fabric", "template", "edit") else "fabric"


# Model used when the fabric goes straight to the try-on model.
def vton_fabric_model():
    return _env("VTON_FABRIC_MODEL", "tryon-max")


def vton_edit_model():
    return _env("VTON_EDIT_MODEL", "edit")


def vton_resolution():
    return _env("VTON_RESOLUTION", "1k")
