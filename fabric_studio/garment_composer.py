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
def render_preview(template_id, palette=None):
    """Neutral-fabric render used as the outfit catalogue preview image."""
    from . import swatches

    palette = palette or ["#b9a88c", "#cdbfa6"]
    tile = swatches.render("solid", 512, palette[:1], texture="linen")
    fabric = {"id": "preview", "processed": {"tilePath": None}}
    params = garment_templates.get(template_id)
    if params is None:
        raise ValidationError(detail="Unknown template %s" % template_id)

    size = _canvas_size()
    mask, shading, details = garment_templates.build(template_id, size)
    fabric_layer = _tile_fabric(tile, size, params.get("pattern_scale", 0.42))
    shaded = _apply_shading(fabric_layer, shading)
    garment = imaging.Image.alpha_composite(shaded.convert("RGBA"), details)
    garment.putalpha(mask)
    canvas = imaging.Image.new("RGB", size, BACKGROUND)
    return _paste_with_shadow(canvas, garment, mask)
