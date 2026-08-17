"""FabricProcessor — turns a stored fabric image into reusable AI-ready assets.

    FABRIC ORIGINAL -> [validate -> crop borders -> normalise -> analyse]
                    -> NORMALIZED FABRIC + TILE + THUMBNAIL + METADATA

The original file is never modified or overwritten: processed assets are
written next to it under fabrics/processed and fabrics/thumbs. The result is
cached on the fabric record and keyed by (processor version, source hash), so a
fabric is analysed once and then reused by every generation that selects it.
"""
import time

from . import config, imaging, storage
from .errors import ImageError, ValidationError
from .fabric_analysis import analyze

PROCESSOR_VERSION = 2

MIN_SOURCE_EDGE = 240


class FabricProcessor(object):
    """Stateless service; safe to instantiate per request or reuse."""

    version = PROCESSOR_VERSION

    def is_current(self, fabric):
        """True when the cached processed asset can be reused as-is."""
        processed = (fabric or {}).get("processed") or {}
        if processed.get("processorVersion") != PROCESSOR_VERSION:
            return False
        if not processed.get("sourceHash"):
            return False
        for key in ("normalizedPath", "tilePath", "thumbnailPath"):
            relative = processed.get(key)
            if not relative:
                return False
            try:
                if not storage.media_path(relative).exists():
                    return False
            except ValueError:
                return False
        try:
            return processed.get("sourceHash") == self.source_hash(fabric)
        except ImageError:
            return False

    def source_hash(self, fabric):
        return imaging.content_hash(self.read_source(fabric))

    def read_source(self, fabric):
        relative = (fabric or {}).get("image_path")
        if not relative:
            raise ValidationError(
                "That fabric isn't ready yet. Please choose another one.",
                detail="Fabric %s has no stored image_path" % (fabric or {}).get("id"),
            )
        try:
            path = storage.media_path(relative)
        except ValueError as exc:
            raise ValidationError(detail=str(exc))
        if not path.exists():
            raise ValidationError(
                "That fabric isn't available right now. Please choose another one.",
                detail="Missing fabric image file %s" % relative,
            )
        return path.read_bytes()

    # ---------------------------------------------------------------- run ---
    def process(self, fabric, force=False):
        """Return the processed-asset block for `fabric`, building it if needed."""
        imaging.require_pillow()
        if not force and self.is_current(fabric):
            return dict(fabric["processed"])

        started = time.time()
        raw = self.read_source(fabric)
        source_hash = imaging.content_hash(raw)
        image = imaging.open_image(raw)
        self.validate_source(image, fabric)

        normalized = self.normalize(image)
        metadata = analyze(normalized)
        tile = self.build_tile(normalized)
        thumbnail = imaging.make_thumbnail(normalized, config.fabric_thumbnail_size())

        fabric_id = fabric.get("id") or "fabric"
        stem = "%s-%s" % (fabric_id, source_hash[:10])
        normalized_rel = "fabrics/processed/%s.jpg" % stem
        tile_rel = "fabrics/processed/%s-tile.jpg" % stem
        thumb_rel = "fabrics/thumbs/%s.jpg" % stem

        storage.write_media(normalized_rel, imaging.encode_image(normalized, "JPEG", 92))
        storage.write_media(tile_rel, imaging.encode_image(tile, "JPEG", 94))
        storage.write_media(thumb_rel, imaging.encode_image(thumbnail, "JPEG", 82))

        processed = {
            "processorVersion": PROCESSOR_VERSION,
            "sourceHash": source_hash,
            "normalizedPath": normalized_rel,
            "tilePath": tile_rel,
            "thumbnailPath": thumb_rel,
            "normalizedUrl": storage.media_url(normalized_rel),
            "thumbnailUrl": storage.media_url(thumb_rel),
            "width": normalized.size[0],
            "height": normalized.size[1],
            "sourceWidth": image.size[0],
            "sourceHeight": image.size[1],
            "metadata": metadata,
            "processedAt": _now(),
            "processingMs": int((time.time() - started) * 1000),
        }
        # Clean up assets from a previous version of this fabric so processed
        # files do not pile up on the volume across re-imports.
        self._prune_previous(fabric, processed)
        return processed

    def _prune_previous(self, fabric, processed):
        previous = (fabric or {}).get("processed") or {}
        for key in ("normalizedPath", "tilePath", "thumbnailPath"):
            old = previous.get(key)
            if old and old != processed.get(key):
                storage.delete_media(old)

    # ------------------------------------------------------------- stages ---
    def validate_source(self, image, fabric=None):
        width, height = image.size
        if min(width, height) < MIN_SOURCE_EDGE:
            raise ValidationError(
                "That fabric photo is too small to use. Please upload one at least %dpx on the short edge." % MIN_SOURCE_EDGE,
                detail="Fabric %s is %dx%d" % ((fabric or {}).get("id"), width, height),
            )
        if imaging.brightness_score(image) < 0.04:
            raise ValidationError(
                "That fabric photo is too dark to read. Please upload a brighter photo.",
                detail="Fabric image is almost black",
            )
        return True

    def normalize(self, image):
        """Crop flat borders, drop alpha, and cap the long edge (never upscale)."""
        cropped = imaging.crop_uniform_border(image)
        rgb = imaging.to_rgb(cropped)
        return imaging.fit_within(rgb, config.fabric_normalized_size())

    def build_tile(self, normalized):
        """A square, mirror-tileable crop used to fill garment silhouettes.

        Mirroring the crop into a 2x2 block removes the hard seam you get from
        naive tiling, which is what makes the composed garment read as one
        continuous piece of cloth rather than a grid of stamps.
        """
        width, height = normalized.size
        edge = min(width, height)
        left = (width - edge) // 2
        top = (height - edge) // 2
        square = normalized.crop((left, top, left + edge, top + edge))
        size = min(512, edge)
        square = square.resize((size, size), imaging.Image.LANCZOS)

        tile = imaging.Image.new("RGB", (size * 2, size * 2))
        flipped_h = square.transpose(imaging.Image.FLIP_LEFT_RIGHT)
        flipped_v = square.transpose(imaging.Image.FLIP_TOP_BOTTOM)
        flipped_hv = flipped_h.transpose(imaging.Image.FLIP_TOP_BOTTOM)
        tile.paste(square, (0, 0))
        tile.paste(flipped_h, (size, 0))
        tile.paste(flipped_v, (0, size))
        tile.paste(flipped_hv, (size, size))
        return tile

    # -------------------------------------------------------- ad-hoc input --
    def analyze_bytes(self, raw):
        """Analyse raw bytes without a catalogue record (used by the importer)."""
        imaging.require_pillow()
        image = imaging.open_image(raw)
        self.validate_source(image)
        normalized = self.normalize(image)
        return normalized, analyze(normalized)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


processor = FabricProcessor()
