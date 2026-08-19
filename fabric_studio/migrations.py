"""Schema/state migrations for the Fabric Studio catalogues.

The existing app persists JSON documents on a mounted volume rather than using
a database engine, so "migration" here means: create the media tree, seed the
catalogues, and repair assets — always additively. Migrations never delete or
overwrite a record an administrator created or edited; a seed record that
already exists is left exactly as it is.

Applied migrations are recorded in DATA_DIR/fabric_studio_meta.json, so each
one runs once per deployment volume and startup stays fast afterwards.
"""
import json
import threading
import time

from . import config, imaging, storage
from .catalog import FABRIC_STORE, OUTFIT_STORE, ensure_fabric_processed, now, slugify
from .errors import log
from .seed_data import SEED_FABRICS, SEED_LICENSE, SEED_OUTFITS

SCHEMA_VERSION = 1
META_FILE = "fabric_studio_meta.json"

_lock = threading.Lock()


def _meta_path():
    return storage.data_root() / META_FILE


def read_meta():
    path = _meta_path()
    if not path.exists():
        return {"schemaVersion": 0, "applied": [], "updatedAt": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schemaVersion": 0, "applied": [], "updatedAt": None}


def write_meta(meta):
    meta["updatedAt"] = now()
    path = _meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ------------------------------------------------------------- migrations ---
def migration_001_media_tree():
    storage.ensure_dirs()
    return {"created": list(storage.MEDIA_SUBDIRS)}


def migration_002_seed_outfits():
    """Insert the predefined outfits and render their preview images."""
    from . import garment_composer

    existing = {record["id"] for record in OUTFIT_STORE.all()}
    inserted = 0
    for seed in SEED_OUTFITS:
        if seed["id"] in existing:
            continue
        record = dict(seed)
        record["slug"] = slugify(record["name"])
        record["is_active"] = True
        record["created_at"] = now()
        record["updated_at"] = now()
        preview_relative = "outfits/%s.png" % record["id"]
        try:
            preview = garment_composer.render_preview(record["template_id"])
            storage.write_media(preview_relative, imaging.encode_image(preview, "PNG"))
            record["preview_image_path"] = preview_relative
            record["preview_image_url"] = storage.media_url(preview_relative)
        except Exception as exc:  # pragma: no cover - preview is cosmetic
            log.warning("Could not render preview for %s: %s", record["id"], exc)
        OUTFIT_STORE.upsert(record)
        inserted += 1
    return {"insertedOutfits": inserted, "total": OUTFIT_STORE.count()}


def migration_003_seed_fabrics():
    """Render and insert the seed swatches (owned assets, clean licence)."""
    from . import swatches

    existing = {record["id"] for record in FABRIC_STORE.all()}
    inserted = 0
    for seed in SEED_FABRICS:
        if seed["id"] in existing:
            continue
        record = _seed_fabric_record(seed)
        spec = seed["swatch"]
        image = swatches.render(spec["kind"], 1024, spec["palette"], **spec.get("options", {}))
        relative = "fabrics/original/%s.jpg" % seed["id"]
        storage.write_media(relative, imaging.encode_image(image, "JPEG", 94))
        record["image_path"] = relative
        record["image_url"] = storage.media_url(relative)
        FABRIC_STORE.upsert(record)
        inserted += 1
    return {"insertedFabrics": inserted, "total": FABRIC_STORE.count()}


def migration_004_process_fabrics():
    """Warm the processed-asset cache so the first customer isn't the one waiting."""
    processed = 0
    failed = 0
    for record in FABRIC_STORE.all():
        try:
            ensure_fabric_processed(record["id"])
            processed += 1
        except Exception as exc:
            failed += 1
            log.warning("Could not process fabric %s: %s", record.get("id"), exc)
    return {"processed": processed, "failed": failed}


def migration_005_refresh_outfit_previews():
    """Re-render outfit previews after a change to the sketch style.

    Skips any outfit whose preview an admin uploaded — a real photograph always
    outranks a generated sketch.
    """
    from . import garment_composer

    refreshed = 0
    skipped = 0
    for record in OUTFIT_STORE.all():
        if record.get("preview_custom"):
            skipped += 1
            continue
        template_id = record.get("template_id")
        if not template_id:
            continue
        relative = "outfits/%s.png" % record["id"]
        try:
            preview = garment_composer.render_preview(template_id)
            storage.write_media(relative, imaging.encode_image(preview, "PNG"))
        except Exception as exc:  # pragma: no cover - preview is cosmetic
            log.warning("Could not refresh preview for %s: %s", record["id"], exc)
            continue
        previous = record.get("preview_image_path")
        if previous and previous != relative:
            storage.delete_media(previous)
        OUTFIT_STORE.update(record["id"], {
            "preview_image_path": relative,
            "preview_image_url": storage.media_url(relative),
            "preview_version": garment_composer.PREVIEW_VERSION,
            "updated_at": now(),
        })
        refreshed += 1
    return {"refreshed": refreshed, "skippedCustom": skipped}


MIGRATIONS = (
    ("001_media_tree", migration_001_media_tree),
    ("002_seed_outfits", migration_002_seed_outfits),
    ("003_seed_fabrics", migration_003_seed_fabrics),
    ("004_process_fabrics", migration_004_process_fabrics),
    ("005_refresh_outfit_previews_v4", migration_005_refresh_outfit_previews),
)


def _seed_fabric_record(seed):
    record = {
        "id": seed["id"],
        "name": seed["name"],
        "slug": slugify(seed["name"]),
        "category": seed["category"],
        "subcategory": seed.get("subcategory", ""),
        "description": seed.get("description", ""),
        "pattern_type": seed.get("pattern_type", ""),
        "texture_description": seed.get("texture_description", ""),
        "primary_colors": [],
        "secondary_colors": [],
        "tags": seed.get("tags", []),
        "region": seed.get("region", ""),
        "swatch": seed.get("swatch"),
        "is_active": True,
        "review_status": "approved",
        "is_seed": True,
        "created_at": now(),
        "updated_at": now(),
    }
    record.update(SEED_LICENSE)
    return record


# ------------------------------------------------------------------ runner --
def run_migrations(force=False):
    """Apply pending migrations. Safe to call on every process start."""
    with _lock:
        meta = read_meta()
        applied = set(meta.get("applied") or [])
        results = {}
        for name, function in MIGRATIONS:
            if name in applied and not force:
                continue
            started = time.time()
            try:
                results[name] = function()
                applied.add(name)
            except Exception as exc:
                log.exception("Fabric Studio migration %s failed: %s", name, exc)
                results[name] = {"error": str(exc)}
                break
            finally:
                results.setdefault(name, {})
                if isinstance(results.get(name), dict):
                    results[name]["ms"] = int((time.time() - started) * 1000)
        meta["applied"] = sorted(applied)
        meta["schemaVersion"] = SCHEMA_VERSION
        write_meta(meta)
        return {"schemaVersion": SCHEMA_VERSION, "applied": sorted(applied), "results": results}


def repair_assets():
    """Re-render seed swatches whose files vanished (e.g. a wiped volume).

    Only touches records that carry a `swatch` spec — an uploaded or imported
    image can never be regenerated, so those are reported instead.
    """
    from . import swatches

    storage.ensure_dirs()
    repaired = []
    missing = []
    for record in FABRIC_STORE.all():
        relative = record.get("image_path")
        exists = False
        if relative:
            try:
                exists = storage.media_path(relative).exists()
            except ValueError:
                exists = False
        if exists:
            continue
        spec = record.get("swatch")
        if not spec:
            missing.append(record["id"])
            continue
        image = swatches.render(spec["kind"], 1024, spec["palette"], **spec.get("options", {}))
        relative = "fabrics/original/%s.jpg" % record["id"]
        storage.write_media(relative, imaging.encode_image(image, "JPEG", 94))
        FABRIC_STORE.update(record["id"], {
            "image_path": relative,
            "image_url": storage.media_url(relative),
            "updated_at": now(),
        })
        ensure_fabric_processed(record["id"], force=True)
        repaired.append(record["id"])
    return {"repaired": repaired, "missingSourceImage": missing}


def status():
    meta = read_meta()
    return {
        "schemaVersion": meta.get("schemaVersion", 0),
        "applied": meta.get("applied", []),
        "pending": [name for name, _fn in MIGRATIONS if name not in (meta.get("applied") or [])],
        "fabrics": FABRIC_STORE.count(),
        "outfits": OUTFIT_STORE.count(),
        "dataDir": str(config.data_dir()),
        "pillow": imaging.PILLOW_AVAILABLE,
    }
