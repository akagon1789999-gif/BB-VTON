"""Image helpers shared by fabric processing, garment composition and uploads.

Pillow is required for Fabric Studio; if it is missing the feature reports
itself as unavailable instead of crashing the rest of the site (the existing
Virtual Try-On does not depend on it). numpy is optional and only sharpens the
pattern analysis in fabric_processor.
"""
import base64
import binascii
import hashlib
import io
import re

from . import config
from .errors import ImageError, DependencyError

try:  # pragma: no cover - import guard
    from PIL import Image, ImageFilter, ImageStat, ImageOps
    PILLOW_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    Image = ImageFilter = ImageStat = ImageOps = None
    PILLOW_AVAILABLE = False

DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)

SUPPORTED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
SUPPORTED_MIMETYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def require_pillow():
    if not PILLOW_AVAILABLE:
        raise DependencyError(
            detail="Pillow is not installed; run `pip install -r requirements.txt`."
        )


def numpy_module():
    """Return numpy if installed, else None (callers degrade gracefully)."""
    try:
        import numpy
        return numpy
    except Exception:
        return None


# ------------------------------------------------------------------ input ---
def decode_data_url(value, max_bytes=None):
    """Decode a `data:image/...;base64,...` string into raw bytes."""
    if not isinstance(value, str):
        raise ImageError(detail="Image input is not a string.")
    match = DATA_URL_RE.match(value.strip())
    if not match:
        raise ImageError(detail="Image input is not a base64 data URL.")
    mimetype = match.group(1).lower()
    if mimetype not in SUPPORTED_MIMETYPES:
        raise ImageError(
            "That image format isn't supported. Please use a JPG, PNG, or WEBP image.",
            detail="Unsupported mimetype %s" % mimetype,
        )
    try:
        raw = base64.b64decode(match.group(2), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ImageError(detail="Base64 decode failed: %s" % exc)
    limit = max_bytes or config.max_upload_bytes()
    if len(raw) > limit:
        raise ImageError(
            "That image is too large. Please use an image under %d MB." % (limit // (1024 * 1024)),
            detail="Image is %d bytes (limit %d)" % (len(raw), limit),
        )
    if not raw:
        raise ImageError(detail="Empty image payload.")
    return raw


def open_image(raw_bytes):
    """Open bytes as an RGB(A) Pillow image with EXIF orientation applied."""
    require_pillow()
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()
    except Exception as exc:
        raise ImageError(detail="Pillow could not decode the image: %s" % exc)
    if (image.format or "").upper() not in SUPPORTED_FORMATS:
        raise ImageError(
            "That image format isn't supported. Please use a JPG, PNG, or WEBP image.",
            detail="Decoded format %s" % image.format,
        )
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass
    return image


def load_image(value, max_bytes=None):
    """Accept a data URL or raw bytes and return (image, raw_bytes)."""
    raw = value if isinstance(value, (bytes, bytearray)) else decode_data_url(value, max_bytes)
    raw = bytes(raw)
    return open_image(raw), raw


def to_rgb(image):
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "P"):
        converted = image.convert("RGBA")
        background = Image.new("RGB", converted.size, (255, 255, 255))
        background.paste(converted, mask=converted.split()[-1])
        return background
    return image.convert("RGB")


# ----------------------------------------------------------------- output ---
def encode_image(image, fmt="JPEG", quality=92):
    require_pillow()
    buffer = io.BytesIO()
    if fmt.upper() == "JPEG":
        to_rgb(image).save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
    elif fmt.upper() == "PNG":
        image.save(buffer, "PNG", optimize=True)
    else:
        image.save(buffer, fmt.upper())
    return buffer.getvalue()


def to_data_url(image_or_bytes, fmt="JPEG", quality=92):
    if isinstance(image_or_bytes, (bytes, bytearray)):
        raw = bytes(image_or_bytes)
    else:
        raw = encode_image(image_or_bytes, fmt=fmt, quality=quality)
    mimetype = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return "data:%s;base64,%s" % (mimetype, base64.b64encode(raw).decode("ascii"))


def content_hash(raw_bytes):
    return hashlib.sha256(raw_bytes).hexdigest()[:20]


# --------------------------------------------------------------- geometry ---
def fit_within(image, max_edge):
    """Downscale so the long edge is at most `max_edge`. Never upscales."""
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image
    scale = float(max_edge) / float(longest)
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.resize(size, Image.LANCZOS)


def make_thumbnail(image, size):
    thumb = image.copy()
    thumb.thumbnail((size, size), Image.LANCZOS)
    return thumb


def crop_uniform_border(image, tolerance=12):
    """Trim flat studio borders (white paper, scan edges) around a swatch.

    Deliberately conservative: it only crops when the border is close to a
    single colour and at most 25% of each edge, so real fabric is never cut.
    """
    rgb = to_rgb(image)
    width, height = rgb.size
    small = rgb.resize((min(width, 200), min(height, 200)), Image.BILINEAR)
    pixels = small.load()
    corner = pixels[0, 0]

    def close(pixel):
        return all(abs(pixel[i] - corner[i]) <= tolerance for i in range(3))

    sw, sh = small.size
    top = 0
    while top < sh // 4 and all(close(pixels[x, top]) for x in range(0, sw, max(1, sw // 40))):
        top += 1
    bottom = sh - 1
    while bottom > sh - sh // 4 and all(close(pixels[x, bottom]) for x in range(0, sw, max(1, sw // 40))):
        bottom -= 1
    left = 0
    while left < sw // 4 and all(close(pixels[left, y]) for y in range(0, sh, max(1, sh // 40))):
        left += 1
    right = sw - 1
    while right > sw - sw // 4 and all(close(pixels[right, y]) for y in range(0, sh, max(1, sh // 40))):
        right -= 1

    if top == 0 and left == 0 and bottom == sh - 1 and right == sw - 1:
        return image
    box = (
        int(left * width / sw),
        int(top * height / sh),
        int((right + 1) * width / sw),
        int((bottom + 1) * height / sh),
    )
    if box[2] - box[0] < width * 0.4 or box[3] - box[1] < height * 0.4:
        return image
    return image.crop(box)


# --------------------------------------------------------------- analysis ---
def sharpness_score(image):
    """0..1 rough focus score from edge energy. Used to warn about blur."""
    gray = to_rgb(image).convert("L")
    gray = fit_within(gray, 512)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    # FIND_EDGES lights up the image border itself; crop it off or every flat
    # image scores as sharp.
    width, height = edges.size
    if width > 8 and height > 8:
        edges = edges.crop((3, 3, width - 3, height - 3))
    stddev = ImageStat.Stat(edges).stddev[0]
    return max(0.0, min(1.0, stddev / 60.0))


def brightness_score(image):
    gray = to_rgb(image).convert("L")
    return ImageStat.Stat(gray).mean[0] / 255.0
