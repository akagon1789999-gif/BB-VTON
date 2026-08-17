"""Fabric and outfit catalogue repositories.

Everything above this module works with catalogue *records*; only this module
knows they live in JSON documents. Search, filtering and facets are computed
here so the frontend never receives a hard-coded catalogue.
"""
import re
import time

from . import storage
from .errors import NotFoundError, ValidationError
from .fabric_processor import processor
from .seed_data import FABRIC_CATEGORIES, OUTFIT_CATEGORIES, PATTERN_TYPES

FABRIC_STORE = storage.JsonStore(
    "fabric_catalog.json",
    key_field="id",
    indexes=("category", "pattern_type", "slug"),
)
OUTFIT_STORE = storage.JsonStore(
    "outfit_catalog.json",
    key_field="id",
    indexes=("category", "slug", "garment_type"),
)

REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(text):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "item"


# ------------------------------------------------------------- fabric CRUD --
def all_fabrics(include_inactive=False):
    records = FABRIC_STORE.all()
    if include_inactive:
        return records
    return [r for r in records if r.get("is_active") and r.get("review_status", REVIEW_APPROVED) == REVIEW_APPROVED]


def get_fabric(identifier, include_inactive=True):
    if not identifier:
        return None
    record = FABRIC_STORE.get(identifier)
    if record is None:
        matches = FABRIC_STORE.find_by("slug", identifier)
        record = matches[0] if matches else None
    if record is None:
        return None
    if not include_inactive and not record.get("is_active"):
        return None
    return record


def require_fabric(identifier, include_inactive=False):
    record = get_fabric(identifier, include_inactive=include_inactive)
    if record is None:
        raise NotFoundError(
            "We couldn't find that fabric. Please pick another one.",
            detail="Fabric %r not found" % identifier,
        )
    return record


def save_fabric(record):
    record.setdefault("created_at", now())
    record["updated_at"] = now()
    record.setdefault("slug", slugify(record.get("name")))
    record.setdefault("is_active", True)
    record.setdefault("review_status", REVIEW_APPROVED)
    return FABRIC_STORE.upsert(record)


def delete_fabric(fabric_id, remove_files=True):
    record = FABRIC_STORE.get(fabric_id)
    if record is None:
        raise NotFoundError(detail="Fabric %s not found" % fabric_id)
    if remove_files:
        storage.delete_media(record.get("image_path"))
        for key in ("normalizedPath", "tilePath", "thumbnailPath"):
            storage.delete_media((record.get("processed") or {}).get(key))
    FABRIC_STORE.delete(fabric_id)
    return True


def set_fabric_active(fabric_id, active):
    record = FABRIC_STORE.update(fabric_id, {"is_active": bool(active), "updated_at": now()})
    if record is None:
        raise NotFoundError(detail="Fabric %s not found" % fabric_id)
    return record


def ensure_fabric_processed(fabric_id, force=False):
    """Process a fabric if its cached assets are missing or stale, then persist."""
    record = require_fabric(fabric_id, include_inactive=True)
    if not force and processor.is_current(record):
        return record
    processed = processor.process(record, force=force)
    updates = {"processed": processed, "updated_at": now()}
    metadata = processed.get("metadata") or {}
    # Detected values only fill gaps — curated metadata is never overwritten.
    if not record.get("pattern_type"):
        updates["pattern_type"] = metadata.get("patternType")
    if not record.get("primary_colors"):
        updates["primary_colors"] = [c["name"] for c in metadata.get("dominantColors", [])]
    if not record.get("secondary_colors"):
        updates["secondary_colors"] = [c["name"] for c in metadata.get("secondaryColors", [])]
    if not record.get("texture_description"):
        updates["texture_description"] = metadata.get("texture")
    updates["thumbnail_url"] = storage.media_url(processed.get("thumbnailPath"))
    return FABRIC_STORE.update(fabric_id, updates)


# ------------------------------------------------------------- outfit CRUD --
def all_outfits(include_inactive=False):
    records = OUTFIT_STORE.all()
    if not include_inactive:
        records = [r for r in records if r.get("is_active")]
    records.sort(key=lambda r: (r.get("sort_order") or 999, r.get("name") or ""))
    return records


def get_outfit(identifier, include_inactive=True):
    if not identifier:
        return None
    record = OUTFIT_STORE.get(identifier)
    if record is None:
        matches = OUTFIT_STORE.find_by("slug", identifier)
        record = matches[0] if matches else None
    if record is None:
        return None
    if not include_inactive and not record.get("is_active"):
        return None
    return record


def require_outfit(identifier, include_inactive=False):
    record = get_outfit(identifier, include_inactive=include_inactive)
    if record is None:
        raise NotFoundError(
            "We couldn't find that outfit. Please pick another one.",
            detail="Outfit %r not found" % identifier,
        )
    return record


def save_outfit(record):
    record.setdefault("created_at", now())
    record["updated_at"] = now()
    record.setdefault("slug", slugify(record.get("name")))
    record.setdefault("is_active", True)
    return OUTFIT_STORE.upsert(record)


def delete_outfit(outfit_id, remove_files=True):
    record = OUTFIT_STORE.get(outfit_id)
    if record is None:
        raise NotFoundError(detail="Outfit %s not found" % outfit_id)
    if remove_files:
        storage.delete_media(record.get("preview_image_path"))
    OUTFIT_STORE.delete(outfit_id)
    return True


def set_outfit_active(outfit_id, active):
    record = OUTFIT_STORE.update(outfit_id, {"is_active": bool(active), "updated_at": now()})
    if record is None:
        raise NotFoundError(detail="Outfit %s not found" % outfit_id)
    return record


# ------------------------------------------------------------ search/views --
def search_fabrics(query=None, category=None, pattern=None, color=None, tag=None,
                   limit=60, offset=0, include_inactive=False):
    records = all_fabrics(include_inactive=include_inactive)
    needle = (query or "").strip().lower()

    def matches(record):
        if category and category != "All" and record.get("category") != category:
            return False
        if pattern and pattern != "All" and (record.get("pattern_type") or "") != pattern:
            return False
        if color and color != "All":
            colors = [c.lower() for c in (record.get("primary_colors") or []) + (record.get("secondary_colors") or [])]
            if color.lower() not in colors:
                return False
        if tag and tag != "All" and tag not in (record.get("tags") or []):
            return False
        if needle:
            haystack = " ".join(str(v) for v in [
                record.get("name"), record.get("category"), record.get("subcategory"),
                record.get("description"), record.get("pattern_type"),
                " ".join(record.get("primary_colors") or []),
                " ".join(record.get("secondary_colors") or []),
                " ".join(record.get("tags") or []),
                record.get("region"),
            ] if v).lower()
            if needle not in haystack:
                return False
        return True

    filtered = [r for r in records if matches(r)]
    filtered.sort(key=lambda r: (r.get("category") or "", r.get("name") or ""))
    total = len(filtered)
    window = filtered[offset:offset + max(1, limit)]
    return {
        "items": [fabric_view(r) for r in window],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def fabric_view(record):
    """Public shape of a fabric. Curated fields win; detected fields inform."""
    processed = record.get("processed") or {}
    metadata = processed.get("metadata") or {}
    return {
        "id": record.get("id"),
        "fabricId": record.get("id"),
        "name": record.get("name"),
        "slug": record.get("slug"),
        "category": record.get("category"),
        "subcategory": record.get("subcategory"),
        "description": record.get("description"),
        "imageUrl": record.get("image_url") or storage.media_url(record.get("image_path")),
        "thumbnailUrl": (
            record.get("thumbnail_url")
            or storage.media_url(processed.get("thumbnailPath"))
            or record.get("image_url")
            or storage.media_url(record.get("image_path"))
        ),
        "patternType": record.get("pattern_type") or metadata.get("patternType") or "",
        "patternDensity": metadata.get("patternDensity") or "",
        "primaryColors": record.get("primary_colors") or [c["name"] for c in metadata.get("dominantColors", [])],
        "secondaryColors": record.get("secondary_colors") or [c["name"] for c in metadata.get("secondaryColors", [])],
        "colorSwatches": [c.get("hex") for c in metadata.get("dominantColors", [])][:3],
        "textureDescription": record.get("texture_description") or metadata.get("texture") or "",
        "region": record.get("region") or "",
        "tags": record.get("tags") or [],
        "sourceName": record.get("source_name") or "",
        "sourceUrl": record.get("source_url") or "",
        "license": record.get("license") or "",
        "attribution": record.get("attribution") or "",
        "isActive": bool(record.get("is_active")),
        "reviewStatus": record.get("review_status", REVIEW_APPROVED),
        "isProcessed": bool(processed.get("normalizedPath")),
        "detected": {
            "patternType": metadata.get("patternType"),
            "patternDensity": metadata.get("patternDensity"),
            "orientation": metadata.get("orientation"),
            "description": metadata.get("description"),
        } if metadata else {},
        "createdAt": record.get("created_at"),
        "updatedAt": record.get("updated_at"),
    }


def outfit_view(record):
    return {
        "id": record.get("id"),
        "outfitId": record.get("id"),
        "name": record.get("name"),
        "slug": record.get("slug"),
        "category": record.get("category"),
        "description": record.get("description"),
        "previewImageUrl": record.get("preview_image_url") or storage.media_url(record.get("preview_image_path")),
        "garmentType": record.get("garment_type"),
        "maskType": record.get("mask_type"),
        "templateId": record.get("template_id"),
        "supportedRegions": record.get("supported_regions") or [],
        "defaultPrompt": record.get("default_prompt") or "",
        "patternScale": record.get("pattern_scale"),
        "isActive": bool(record.get("is_active")),
        "sortOrder": record.get("sort_order"),
        "createdAt": record.get("created_at"),
        "updatedAt": record.get("updated_at"),
    }


def facets():
    """Filter options built from the live catalogue, not a hard-coded list."""
    records = all_fabrics()
    categories = {}
    patterns = {}
    colors = {}
    tags = {}
    for record in records:
        categories[record.get("category") or "Other"] = categories.get(record.get("category") or "Other", 0) + 1
        pattern = record.get("pattern_type") or "unknown"
        patterns[pattern] = patterns.get(pattern, 0) + 1
        for color in (record.get("primary_colors") or [])[:2]:
            colors[color] = colors.get(color, 0) + 1
        for tag in record.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1

    def as_list(mapping, order=None):
        items = [{"value": k, "count": v} for k, v in mapping.items()]
        if order:
            rank = {value: index for index, value in enumerate(order)}
            items.sort(key=lambda item: (rank.get(item["value"], 999), item["value"]))
        else:
            items.sort(key=lambda item: (-item["count"], item["value"]))
        return items

    return {
        "categories": as_list(categories, FABRIC_CATEGORIES),
        "patterns": as_list(patterns, PATTERN_TYPES),
        "colors": as_list(colors)[:14],
        "tags": as_list(tags)[:14],
        "outfitCategories": OUTFIT_CATEGORIES,
    }


def validate_fabric_payload(payload, partial=False):
    """Shared validation for admin create/update."""
    cleaned = {}
    name = (payload.get("name") or "").strip()
    if not partial and not name:
        raise ValidationError("A fabric name is required.", detail="Missing name")
    if name:
        cleaned["name"] = name[:120]
        cleaned["slug"] = slugify(name)
    for field, limit in (("category", 60), ("subcategory", 60), ("description", 600),
                         ("texture_description", 300), ("pattern_type", 40),
                         ("source_name", 120), ("license", 200), ("attribution", 300),
                         ("region", 80)):
        if field in payload:
            cleaned[field] = (payload.get(field) or "").strip()[:limit]
    if "source_url" in payload:
        url = (payload.get("source_url") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValidationError("The source URL must start with http:// or https://.",
                                  detail="Bad source_url %r" % url)
        cleaned["source_url"] = url[:500]
    for field in ("primary_colors", "secondary_colors", "tags"):
        if field in payload:
            value = payload.get(field)
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            cleaned[field] = [str(v)[:40] for v in (value or [])][:12]
    if "is_active" in payload:
        cleaned["is_active"] = _as_bool(payload.get("is_active"))
    return cleaned


def validate_outfit_payload(payload, partial=False):
    from . import garment_templates

    cleaned = {}
    name = (payload.get("name") or "").strip()
    if not partial and not name:
        raise ValidationError("An outfit name is required.", detail="Missing name")
    if name:
        cleaned["name"] = name[:120]
        cleaned["slug"] = slugify(name)
    template_id = (payload.get("template_id") or "").strip()
    if template_id:
        if garment_templates.get(template_id) is None:
            raise ValidationError(
                "That garment template doesn't exist.",
                detail="Unknown template %s (available: %s)" % (template_id, ", ".join(garment_templates.ids())),
            )
        cleaned["template_id"] = template_id
    elif not partial:
        raise ValidationError("Pick a garment template for this outfit.", detail="Missing template_id")

    garment_type = (payload.get("garment_type") or "").strip()
    if garment_type:
        if garment_type not in ("tops", "bottoms", "one-pieces"):
            raise ValidationError(
                "Garment type must be tops, bottoms, or one-pieces.",
                detail="Bad garment_type %r" % garment_type,
            )
        cleaned["garment_type"] = garment_type
    for field, limit in (("category", 40), ("description", 600), ("mask_type", 40), ("default_prompt", 600)):
        if field in payload:
            cleaned[field] = (payload.get(field) or "").strip()[:limit]
    if "supported_regions" in payload:
        value = payload.get("supported_regions")
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        cleaned["supported_regions"] = [str(v)[:60] for v in (value or [])][:10]
    if "pattern_scale" in payload and str(payload.get("pattern_scale") or "").strip():
        try:
            scale = float(payload["pattern_scale"])
        except (TypeError, ValueError):
            raise ValidationError("Pattern scale must be a number between 0.1 and 1.6.",
                                  detail="Bad pattern_scale %r" % payload.get("pattern_scale"))
        cleaned["pattern_scale"] = max(0.1, min(1.6, scale))
    if "sort_order" in payload and str(payload.get("sort_order") or "").strip():
        try:
            cleaned["sort_order"] = int(payload["sort_order"])
        except (TypeError, ValueError):
            raise ValidationError("Sort order must be a whole number.", detail="Bad sort_order")
    if "is_active" in payload:
        cleaned["is_active"] = _as_bool(payload.get("is_active"))
    return cleaned


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
