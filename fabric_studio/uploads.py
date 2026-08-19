"""Customer-supplied fabric photos and garment references.

The catalogue is the curated path; this is the open one. A customer can bring
their own length of cloth and their own garment reference — including a photo of
someone wearing the outfit they want — and the pipeline treats them exactly like
catalogue records.

Uploads are never written into the catalogue: they are stored under
media/uploads keyed by content hash, so the same photo uploaded twice is
processed once, and nothing a customer uploads shows up in anyone else's
catalogue. An admin who wants an upload in the catalogue adds it deliberately
through the admin tools.
"""
from . import imaging, storage
from .errors import ValidationError
from .fabric_analysis import analyze
from .fabric_processor import processor

UPLOAD_FABRIC_DIR = "uploads/fabrics"
UPLOAD_GARMENT_DIR = "uploads/garments"


def store_fabric(value):
    """Process an uploaded fabric photo into a catalogue-shaped record."""
    imaging.require_pillow()
    image, raw = imaging.load_image(value)
    digest = imaging.content_hash(raw)
    fabric_id = "upload_%s" % digest[:16]

    original = "%s/%s.jpg" % (UPLOAD_FABRIC_DIR, digest)
    normalized_rel = "%s/%s-normalized.jpg" % (UPLOAD_FABRIC_DIR, digest)
    tile_rel = "%s/%s-tile.jpg" % (UPLOAD_FABRIC_DIR, digest)
    thumb_rel = "%s/%s-thumb.jpg" % (UPLOAD_FABRIC_DIR, digest)

    if storage.media_path(normalized_rel).exists():
        with imaging.Image.open(str(storage.media_path(normalized_rel))) as opened:
            normalized = opened.copy()
        metadata = analyze(normalized)
    else:
        processor.validate_source(image)
        normalized = processor.normalize(image)
        metadata = analyze(normalized)
        tile = processor.build_tile(normalized)
        thumbnail = imaging.make_thumbnail(normalized, 400)
        storage.write_media(original, raw)
        storage.write_media(normalized_rel, imaging.encode_image(normalized, "JPEG", 92))
        storage.write_media(tile_rel, imaging.encode_image(tile, "JPEG", 94))
        storage.write_media(thumb_rel, imaging.encode_image(thumbnail, "JPEG", 82))

    return {
        "id": fabric_id,
        "name": "Your fabric",
        "category": "Uploaded",
        "is_upload": True,
        "image_path": original,
        "image_url": storage.media_url(original),
        "thumbnail_url": storage.media_url(thumb_rel),
        "pattern_type": metadata.get("patternType"),
        "primary_colors": [c["name"] for c in metadata.get("dominantColors", [])],
        "texture_description": metadata.get("texture"),
        "processed": {
            "processorVersion": processor.version,
            "sourceHash": digest,
            "normalizedPath": normalized_rel,
            "tilePath": tile_rel,
            "thumbnailPath": thumb_rel,
            "metadata": metadata,
        },
    }


def store_garment(value, name=None, template_id="modern-senator"):
    """Store an uploaded garment reference as an outfit-shaped record.

    The reference may be a flat-lay or a photo of someone wearing the outfit —
    the remake step handles both, which local compositing cannot.
    """
    imaging.require_pillow()
    image, raw = imaging.load_image(value)
    if min(image.size) < 240:
        raise ValidationError(
            "That garment photo is too small. Please use one at least 240px on the short side.",
            detail="Garment upload is %dx%d" % image.size,
        )
    digest = imaging.content_hash(raw)
    relative = "%s/%s.jpg" % (UPLOAD_GARMENT_DIR, digest)
    if not storage.media_path(relative).exists():
        normalized = imaging.fit_within(imaging.to_rgb(image), 1400)
        storage.write_media(relative, imaging.encode_image(normalized, "JPEG", 92))

    return {
        "id": "upload_%s" % digest[:16],
        "name": name or "Your garment",
        "category": "Uploaded",
        "is_upload": True,
        # Kept so a fallback composite still has a shape to fill if the remake
        # step is unavailable.
        "template_id": template_id,
        "garment_type": "one-pieces",
        "mask_type": "full_body",
        "reference_image_path": relative,
        "preview_image_url": storage.media_url(relative),
        "default_prompt": "",
    }
