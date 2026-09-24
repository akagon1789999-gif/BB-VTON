"""Upload preprocessing.

The same pipeline the Next.js studio ran through sharp, done with Pillow:

1. Auto-rotate from EXIF and strip metadata.
2. Apply the crop rect, if the customer set one.
3. Downscale anything over 2000 px on the long edge, preserving aspect.
4. JPEG q95 4:4:4, or PNG when the caller asked for lossless.
"""
import base64
import io

from PIL import Image, ImageOps

from .errors import INPUT_VALIDATION, StudioError, format_bytes

# Hard input limits, straight from the FASHN docs. Enforced in the browser
# before upload and again here before the API call.
MAX_FILE_BYTES = 30 * 1024 * 1024
MIN_DIMENSION = 15
MAX_ASPECT_RATIO = 16
MAX_LONG_EDGE = 2000  # our own downscale ceiling
ACCEPTED_TYPES = ("image/jpeg", "image/png", "image/webp", "image/avif")

# 2:3 is where try-on models behave best. Used to nudge, never to crop silently.
TARGET_RATIO = 2 / 3

# A swatch has to carry a whole garment. Below this on the long edge there is
# not enough motif detail to reproduce, and the model reconstructs something
# that merely resembles the print. Advice, never a rejection: a small swatch
# still works, it just works worse, and that is the customer's call.
MIN_USEFUL_FABRIC_EDGE = 800


def validate_file(name, size, content_type):
    """File-level checks that need no decode. Runs before Pillow sees bytes."""
    if size > MAX_FILE_BYTES:
        raise StudioError(
            INPUT_VALIDATION,
            "%s is %s. The limit is 30 MB." % (name, format_bytes(size)),
            fix="Export it smaller, or screenshot it at a lower resolution.",
            http_status=422,
        )
    if size == 0:
        raise StudioError(
            INPUT_VALIDATION,
            "%s is empty." % name,
            fix="Pick a different file.",
            http_status=422,
        )
    if content_type and content_type not in ACCEPTED_TYPES:
        raise StudioError(
            INPUT_VALIDATION,
            "%s is %s. JPEG, PNG, WebP and AVIF are supported." % (name, content_type),
            fix="Convert it to JPEG or PNG first.",
            http_status=422,
        )


def validate_dimensions(name, width, height):
    """Dimension and aspect checks against decoded metadata."""
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise StudioError(
            INPUT_VALIDATION,
            "%s is %d x %d px. The minimum is 15 x 15 px." % (name, width, height),
            fix="Use the original photo rather than a thumbnail.",
            http_status=422,
        )
    ratio = width / height
    if ratio > MAX_ASPECT_RATIO or ratio < 1 / MAX_ASPECT_RATIO:
        raise StudioError(
            INPUT_VALIDATION,
            "%s is %d x %d px, past the 16:1 aspect ratio limit." % (name, width, height),
            fix="Crop it closer to square before uploading.",
            http_status=422,
        )


def preprocess(raw, name, lossless=False, crop=None, max_long_edge=MAX_LONG_EDGE):
    """Returns a dict: buffer, contentType, extension, width, height, bytes."""
    try:
        source = Image.open(io.BytesIO(raw))
        # exif_transpose applies the EXIF orientation, then drops the tag.
        source = ImageOps.exif_transpose(source)
    except Exception:
        raise StudioError(
            INPUT_VALIDATION,
            "%s could not be decoded as an image." % name,
            fix="Re-export it as JPEG or PNG and try again.",
            http_status=422,
        )

    src_width, src_height = source.size
    if not src_width or not src_height:
        raise StudioError(
            INPUT_VALIDATION,
            "%s has no readable dimensions." % name,
            fix="Re-export it as JPEG or PNG and try again.",
            http_status=422,
        )
    validate_dimensions(name, src_width, src_height)

    working = source
    if crop:
        left = max(0, int(round(crop["x"] * src_width)))
        top = max(0, int(round(crop["y"] * src_height)))
        width = max(MIN_DIMENSION, int(round(crop["width"] * src_width)))
        height = max(MIN_DIMENSION, int(round(crop["height"] * src_height)))
        width = min(width, src_width - left)
        height = min(height, src_height - top)

        validate_dimensions(name, width, height)
        working = working.crop((left, top, left + width, top + height))

    long_edge = max(working.size)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        target = (
            max(1, int(round(working.size[0] * scale))),
            max(1, int(round(working.size[1] * scale))),
        )
        working = working.resize(target, Image.LANCZOS)

    buffer = io.BytesIO()
    if lossless:
        if working.mode not in ("RGB", "RGBA"):
            working = working.convert("RGBA")
        working.save(buffer, format="PNG", optimize=True, compress_level=9)
        content_type, extension = "image/png", "png"
    else:
        if working.mode in ("RGBA", "LA", "P"):
            # Flatten transparency onto white rather than letting it go black.
            flattened = Image.new("RGB", working.size, (255, 255, 255))
            converted = working.convert("RGBA")
            flattened.paste(converted, mask=converted.split()[-1])
            working = flattened
        elif working.mode != "RGB":
            working = working.convert("RGB")
        working.save(buffer, format="JPEG", quality=95, subsampling=0, optimize=True)
        content_type, extension = "image/jpeg", "jpg"

    data = buffer.getvalue()
    if len(data) > MAX_FILE_BYTES:
        raise StudioError(
            INPUT_VALIDATION,
            "%s is still %s after processing. The limit is 30 MB." % (name, format_bytes(len(data))),
            fix="Turn off privacy mode, or use a smaller source image.",
            http_status=422,
        )

    return {
        "buffer": data,
        "contentType": content_type,
        "extension": extension,
        "width": working.size[0],
        "height": working.size[1],
        "bytes": len(data),
    }


def to_data_uri(buffer, content_type):
    return "data:%s;base64,%s" % (content_type, base64.b64encode(buffer).decode("ascii"))


def fabric_hint(width, height):
    """Warns when a swatch is too small to survive being scaled up."""
    long_edge = max(width, height)
    if long_edge >= MIN_USEFUL_FABRIC_EDGE:
        return None
    return (
        "This swatch is %d x %d. Below about %d px on the long edge there is "
        "little pattern detail to work from, and the print tends to come back "
        "approximated rather than reproduced."
        % (width, height, MIN_USEFUL_FABRIC_EDGE)
    )


def aspect_hint(width, height):
    """Model images generate best near 2:3. Advice, never a silent crop."""
    ratio = width / height
    if abs(ratio - TARGET_RATIO) < 0.12:
        return None
    if ratio > TARGET_RATIO:
        return "This model image is wider than 2:3. Cropping to portrait usually gives a cleaner try-on."
    return "This model image is taller than 2:3. Cropping to portrait usually gives a cleaner try-on."
