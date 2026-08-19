"""Re-fabric a garment photograph: same garment, same folds, new cloth.

A vector silhouette filled with a repeating tile is flat — it has no folds, no
seam shadows and no drape, so the try-on model has to invent all of that. A
photograph of the real garment already contains it. This module keeps the
photograph's *lighting* and replaces only its *colour and pattern*:

    garment photo -> mask the garment
                  -> take its luminance (folds, shadows, sheen)
                  -> tile the customer's fabric across it
                  -> multiply the two back together
                  -> composite through the mask

That is the classic textile-substitution trick, and it is why the result reads
as cloth rather than as a sticker. No GPU and no API credits: it is arithmetic
on two images.

Its weak point is the mask, and the weakness is fatal often enough that this
path is never chosen blindly. `usability(photo)` has to pass first:

* a model in the frame is disqualifying — masking a garment off a body is human
  parsing, which this app does not do (see segmentation.py);
* a garment close in tone to its background is disqualifying — a white shirt on
  a cream backdrop masks as *background*, and the fabric lands on the room;
* a patterned reference is disqualifying — luminance cannot separate someone
  else's print from the folds, so the old motif ghosts through the new cloth.

When it fails, garment_composer falls back to the vector template, and the AI
route (`edit` with the fabric as image_context) handles the photographs this
cannot.
"""
from . import imaging
from .errors import ValidationError

# Corner flood-fill tolerance when separating a plain studio background.
BACKGROUND_TOLERANCE = 34
# Luminance below this is treated as shadow to keep rather than fabric to paint.
SHADOW_FLOOR = 0.10


def usability(photo):
    """Report whether this reference photo can be re-fabricked locally.

    Returns {"ok": bool, "reasons": [...]} — reasons are for the admin, who is
    the only one who sees them.
    """
    from .fabric_analysis import analyze

    reasons = []
    if looks_like_a_person(photo):
        reasons.append("There is a model in this photo. Use a photo of the garment on its own.")

    try:
        mask = build_garment_mask(photo)
    except ValidationError as exc:
        return {"ok": False, "reasons": reasons + [str(exc)]}

    numpy = imaging.numpy_module()
    coverage = float((numpy.asarray(mask) > 127).mean()) if numpy is not None else 0.0
    if coverage < 0.12:
        reasons.append("We couldn't find the garment — it may be too close in colour to the background.")
    elif coverage > 0.8:
        reasons.append("The garment couldn't be separated from the background. Try a plainer, more contrasting backdrop.")

    metadata = analyze(_garment_crop(photo, mask))
    if metadata.get("patternDensity") in ("medium", "high") and metadata.get("patternType") not in ("solid", "textured"):
        reasons.append("This garment is already patterned. Use a plain garment so the new fabric reads cleanly.")

    return {"ok": not reasons, "reasons": reasons, "coverage": round(coverage, 3)}


def _garment_crop(photo, mask):
    """Crop to the garment's bounding box so the backdrop does not skew the
    pattern reading."""
    box = mask.point(lambda v: 255 if v > 127 else 0).getbbox()
    if not box:
        return photo
    return photo.crop(box)


def looks_like_a_person(photo):
    """True when the reference photo has a model in it.

    Local re-fabric needs a garment-only photograph: masking a garment off a
    body reliably is human parsing, which this app does not do (see
    segmentation.py). Detect the case so the caller can take the AI route or
    fall back to the template instead of painting fabric over someone's face.
    """
    numpy = imaging.numpy_module()
    if numpy is None:
        return False
    array = numpy.asarray(imaging.to_rgb(imaging.fit_within(photo, 320)), dtype=numpy.float32)
    skin = _skin_mask(numpy, array)
    top_quarter = skin[: max(1, skin.shape[0] // 4)]
    # A garment flat-lay has almost no skin; a model has a head up top and
    # hands at the sides. Thresholds are deliberately twitchy: a false positive
    # costs a fallback to the template, a false negative paints fabric over a
    # face.
    return float(skin.mean()) > 0.015 or float(top_quarter.mean()) > 0.02


def build_garment_mask(photo, skip_skin=True):
    """Mask of the garment in a reference photograph (255 = garment).

    Removes the background by colour-similarity to the image corners, then
    optionally removes skin tones so a short-sleeved garment does not paint the
    model's arms.
    """
    numpy = imaging.numpy_module()
    if numpy is None:
        raise ValidationError(detail="numpy is required to re-fabric a garment photo")

    rgb = imaging.to_rgb(photo)
    array = numpy.asarray(rgb, dtype=numpy.float32)
    height, width = array.shape[:2]

    # --- background: sample the four corners, keep pixels unlike all of them
    patch = max(4, min(height, width) // 40)
    corners = [
        array[:patch, :patch], array[:patch, -patch:],
        array[-patch:, :patch], array[-patch:, -patch:],
    ]
    background = numpy.zeros((height, width), dtype=bool)
    for corner in corners:
        reference = corner.reshape(-1, 3).mean(axis=0)
        distance = numpy.sqrt(((array - reference) ** 2).sum(axis=2))
        background |= distance < BACKGROUND_TOLERANCE
    mask = ~background

    if skip_skin:
        mask &= ~_skin_mask(numpy, array)

    # --- tidy: drop specks, close pinholes, keep the largest region
    mask_image = imaging.Image.fromarray((mask * 255).astype(numpy.uint8))
    radius = max(1, min(height, width) // 200)
    mask_image = mask_image.filter(imaging.ImageFilter.MedianFilter(_odd(radius * 2 + 1)))
    mask_image = mask_image.filter(imaging.ImageFilter.MaxFilter(_odd(radius * 2 + 1)))
    mask_image = mask_image.filter(imaging.ImageFilter.MinFilter(_odd(radius * 2 + 1)))
    mask_image = _largest_region(numpy, mask_image)
    return mask_image.filter(imaging.ImageFilter.GaussianBlur(max(1.0, radius * 0.8)))


def _skin_mask(numpy, array):
    """Rough skin-tone test in normalised RGB — enough to spare hands and face."""
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    total = array.sum(axis=2) + 1e-6
    r_norm, g_norm = red / total, green / total
    return (
        (red > 60) & (red > green) & (green > blue)
        & (r_norm > 0.34) & (r_norm < 0.50)
        & (g_norm > 0.26) & (g_norm < 0.38)
        & ((red - green) > 12)
    )


def _largest_region(numpy, mask_image):
    """Keep the biggest blob, so stray background patches drop out."""
    mask = numpy.asarray(mask_image) > 127
    height, width = mask.shape
    # Cheap connected components via iterative label propagation on a
    # downscaled copy — exact labels are not needed, only the dominant blob.
    scale = max(1, max(height, width) // 220)
    small = mask[::scale, ::scale]
    labels = numpy.zeros(small.shape, dtype=numpy.int32)
    current = 0
    for y in range(small.shape[0]):
        for x in range(small.shape[1]):
            if not small[y, x] or labels[y, x]:
                continue
            current += 1
            stack = [(y, x)]
            labels[y, x] = current
            while stack:
                cy, cx = stack.pop()
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < small.shape[0] and 0 <= nx < small.shape[1]:
                        if small[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = current
                            stack.append((ny, nx))
    if current == 0:
        return mask_image
    counts = numpy.bincount(labels.ravel())
    counts[0] = 0
    keep = int(counts.argmax())
    small_keep = (labels == keep)
    grown = numpy.kron(small_keep, numpy.ones((scale, scale), dtype=bool))[:height, :width]
    if grown.shape != mask.shape:  # pragma: no cover - edge padding
        padded = numpy.zeros_like(mask)
        padded[:grown.shape[0], :grown.shape[1]] = grown
        grown = padded
    return imaging.Image.fromarray(((mask & grown) * 255).astype(numpy.uint8))


def refabric(photo, fabric_tile, mask=None, scale=0.42, keep_shading=0.9):
    """Return the photo with the garment re-made in `fabric_tile`."""
    numpy = imaging.numpy_module()
    if numpy is None:
        raise ValidationError(detail="numpy is required to re-fabric a garment photo")

    rgb = imaging.to_rgb(photo)
    width, height = rgb.size
    mask = mask if mask is not None else build_garment_mask(rgb)

    # Luminance of the garment carries every fold and shadow — but also the
    # original print. Low-pass it so drape survives and the old pattern does
    # not ghost through the new one.
    gray = rgb.convert("L")
    smoothing = max(1.5, min(rgb.size) / 45.0)
    gray = gray.filter(imaging.ImageFilter.GaussianBlur(smoothing))
    luminance = numpy.asarray(gray, dtype=numpy.float32) / 255.0
    mask_array = numpy.asarray(mask.resize(rgb.size), dtype=numpy.float32) / 255.0
    garment = mask_array > 0.5
    if not garment.any():
        raise ValidationError(
            "We couldn't read that garment photo. Please use one on a plain background.",
            detail="Garment mask came out empty",
        )
    # Normalise against the garment's own mid-tone so a dark original does not
    # darken the new fabric and a pale one does not blow it out.
    mid = float(numpy.clip(numpy.median(luminance[garment]), 0.12, 0.9))
    shading = numpy.clip(luminance / mid, 0.25, 1.75)
    shading = 1.0 + (shading - 1.0) * keep_shading

    fabric = _tile(fabric_tile, (width, height), scale)
    fabric_array = numpy.asarray(fabric, dtype=numpy.float32)
    painted = numpy.clip(fabric_array * shading[:, :, None], 0, 255)

    # Deep shadows and specular highlights come through from the original so
    # the cloth keeps the photograph's contact shadows.
    original = numpy.asarray(rgb, dtype=numpy.float32)
    raw_luminance = numpy.asarray(rgb.convert("L"), dtype=numpy.float32) / 255.0
    deep = (raw_luminance < SHADOW_FLOOR)[:, :, None]
    painted = numpy.where(deep, original * 0.65 + painted * 0.35, painted)

    alpha = mask_array[:, :, None]
    blended = original * (1 - alpha) + painted * alpha
    return imaging.Image.fromarray(blended.astype(numpy.uint8))


def _tile(tile, size, scale):
    width, height = size
    tile_width = max(48, int(width * max(0.08, min(1.6, scale))))
    ratio = tile.size[1] / float(tile.size[0])
    tile = tile.resize((tile_width, max(48, int(tile_width * ratio))), imaging.Image.LANCZOS)
    layer = imaging.Image.new("RGB", size)
    for y in range(0, height + tile.size[1], tile.size[1]):
        for x in range(0, width + tile.size[0], tile.size[0]):
            layer.paste(tile, (x, y))
    return layer


def _odd(value):
    return value if value % 2 else value + 1
