"""Builds the garment image that the try-on provider receives.

    PROCESSED FABRIC TILE + OUTFIT TEMPLATE -> FLAT-LAY GARMENT PRODUCT IMAGE

This is the step that keeps MODE A cheap and faithful. Rather than asking a
generative model to imagine a garment in "roughly this fabric" (which drifts
the colours and melts the print), the actual fabric pixels are poured into the
outfit silhouette, shaded, and handed to the try-on model as an ordinary
flat-lay product photo — the input those models are trained on.

Results are cached per (fabric, outfit, template version): composing is a
fraction of a second, but caching also makes the cache key stable so repeat
generations of the same pairing reuse one asset.
"""
import time

from . import config, garment_templates, imaging, storage
from .errors import ValidationError

COMPOSER_VERSION = 3

BACKGROUND = (247, 246, 243)


def cache_key(fabric, outfit):
    processed = (fabric or {}).get("processed") or {}
    return "%s-%s-v%d.%d-%s" % (
        (fabric or {}).get("id", "fabric"),
        (outfit or {}).get("id", "outfit"),
        COMPOSER_VERSION,
        garment_templates.TEMPLATE_VERSION,
        (processed.get("sourceHash") or "nohash")[:10],
    )


def cached_path(fabric, outfit):
    return "fabrics/garments/%s.jpg" % cache_key(fabric, outfit)


def compose(fabric, outfit, force=False):
    """Return {path, url, width, height, cached, ms} for the garment image."""
    imaging.require_pillow()
    started = time.time()
    relative = cached_path(fabric, outfit)
    target = storage.media_path(relative)
    if target.exists() and not force:
        with imaging.Image.open(str(target)) as existing:
            size = existing.size
        return {
            "path": relative,
            "url": storage.media_url(relative),
            "width": size[0],
            "height": size[1],
            "cached": True,
            "ms": int((time.time() - started) * 1000),
        }

    image = render(fabric, outfit)
    storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))
    return {
        "path": relative,
        "url": storage.media_url(relative),
        "width": image.size[0],
        "height": image.size[1],
        "cached": False,
        "ms": int((time.time() - started) * 1000),
    }


def render(fabric, outfit):
    """Compose the garment image (no caching, no disk writes)."""
    template_id = (outfit or {}).get("template_id") or (outfit or {}).get("garment_template")
    params = garment_templates.get(template_id)
    if params is None:
        raise ValidationError(
            "That outfit isn't available right now. Please pick another one.",
            detail="Outfit %s references unknown template %s" % ((outfit or {}).get("id"), template_id),
        )

    tile = _load_tile(fabric)
    size = _canvas_size()
    mask, shading, details = garment_templates.build(template_id, size)

    scale = float(outfit.get("pattern_scale") or params.get("pattern_scale") or 0.42)
    fabric_layer = _tile_fabric(tile, size, scale)
    shaded = _apply_shading(fabric_layer, shading)
    garment = imaging.Image.alpha_composite(shaded.convert("RGBA"), details)
    garment.putalpha(mask)

    canvas = imaging.Image.new("RGB", size, BACKGROUND)
    canvas = _paste_with_shadow(canvas, garment, mask)
    return canvas


# ------------------------------------------------------------------ stages --
def _canvas_size():
    long_edge = config.garment_render_size()
    width, height = garment_templates.CANVAS
    scale = long_edge / float(max(width, height))
    return (max(64, int(width * scale)), max(64, int(height * scale)))


def _load_tile(fabric):
    processed = (fabric or {}).get("processed") or {}
    relative = processed.get("tilePath") or processed.get("normalizedPath")
    if not relative:
        raise ValidationError(
            "That fabric is still being prepared. Please try again in a moment.",
            detail="Fabric %s has no processed tile" % (fabric or {}).get("id"),
        )
    path = storage.media_path(relative)
    if not path.exists():
        raise ValidationError(
            "That fabric is still being prepared. Please try again in a moment.",
            detail="Missing processed tile %s" % relative,
        )
    with imaging.Image.open(str(path)) as opened:
        return imaging.to_rgb(opened.copy())


def _tile_fabric(tile, size, scale):
    """Repeat the fabric tile across the canvas at the requested motif scale."""
    width, height = size
    tile_width = max(48, int(width * max(0.12, min(1.6, scale)) * 2))
    ratio = tile.size[1] / float(tile.size[0])
    tile = tile.resize((tile_width, max(48, int(tile_width * ratio))), imaging.Image.LANCZOS)

    layer = imaging.Image.new("RGB", size)
    for y in range(0, height + tile.size[1], tile.size[1]):
        for x in range(0, width + tile.size[0], tile.size[0]):
            layer.paste(tile, (x, y))
    return layer


def _apply_shading(fabric_layer, shading):
    """Multiply-style shading: 128 leaves the fabric untouched."""
    numpy = imaging.numpy_module()
    if numpy is None:
        from PIL import ImageChops
        return ImageChops.multiply(fabric_layer, shading.convert("RGB"))

    fabric_array = numpy.asarray(fabric_layer, dtype=numpy.float32)
    shade = numpy.asarray(shading, dtype=numpy.float32)[:, :, None] / 128.0
    out = numpy.clip(fabric_array * shade, 0, 255).astype(numpy.uint8)
    return imaging.Image.fromarray(out)


def _paste_with_shadow(canvas, garment, mask):
    """Drop the garment onto the backdrop with a soft contact shadow."""
    width, height = canvas.size
    blur = max(6, int(width * 0.02))
    shadow_mask = mask.filter(imaging.ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * 0.42))
    shadow = imaging.Image.new("RGB", canvas.size, (120, 116, 110))
    canvas = imaging.Image.composite(shadow, canvas, shadow_mask.transform(
        canvas.size,
        imaging.Image.AFFINE,
        (1, 0, -int(width * 0.008), 0, 1, -int(height * 0.006)),
    ))
    canvas.paste(garment, (0, 0), garment)
    return canvas


# ------------------------------------------------------- outfit previews -----
PREVIEW_VERSION = 4

# A technical flat sketch — the drawing convention the trade already uses for
# "which cut is this?" — rather than a render of the garment in an invented
# fabric. The stroke is a mid-tone so one file reads on both the cream and the
# dark card, and the fill is barely there so the card colour shows through.
# Tuned by eye against both card colours: any darker and the line vanishes on
# the dark card, any more fill and it turns into a grey blob there.
SKETCH_STROKE = (154, 148, 136)
SKETCH_FILL_ALPHA = 14


def render_preview(template_id, size=None):
    """Neutral garment sketch used on the outfit cards.

    Deliberately *not* the fabric-filled composite: the outfit catalogue asks
    "which cut?", and dressing the answer in a fabric the customer did not pick
    only muddles the question. An admin-uploaded photograph always wins over
    this.
    """
    imaging.require_pillow()
    if garment_templates.get(template_id) is None:
        raise ValidationError(detail="Unknown template %s" % template_id)

    width, height = size or _preview_size()
    mask, _shading, details = garment_templates.build(template_id, (width, height))

    stroke_width = max(1, int(round(width / 320.0)))
    edge = mask.filter(imaging.ImageFilter.FIND_EDGES)
    edge = edge.filter(imaging.ImageFilter.MaxFilter(3 if stroke_width < 2 else 5))
    edge = edge.filter(imaging.ImageFilter.GaussianBlur(0.6))
    outline = imaging.Image.new("RGBA", (width, height), SKETCH_STROKE + (255,))
    outline.putalpha(edge.point(lambda v: min(255, int(v * 2.2))))

    body = imaging.Image.new("RGBA", (width, height), SKETCH_STROKE + (SKETCH_FILL_ALPHA,))
    body.putalpha(mask.point(lambda v: int(v * SKETCH_FILL_ALPHA / 255.0)))

    seams = _strengthen(details)
    return imaging.Image.alpha_composite(imaging.Image.alpha_composite(body, seams), outline)


def _strengthen(details, factor=1.7):
    """Bring the construction lines up so they survive at card size."""
    numpy = imaging.numpy_module()
    if numpy is None:
        return details
    array = numpy.asarray(details, dtype=numpy.float32).copy()
    array[:, :, 3] = numpy.clip(array[:, :, 3] * factor, 0, 255)
    return imaging.Image.fromarray(array.astype(numpy.uint8))


def _preview_size():
    long_edge = max(320, min(config.garment_render_size(), 720))
    width, height = garment_templates.CANVAS
    scale = long_edge / float(max(width, height))
    return (max(48, int(width * scale)), max(48, int(height * scale)))
