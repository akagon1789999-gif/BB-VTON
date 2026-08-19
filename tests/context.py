"""Shared test environment.

Imported first by every test module: it points DATA_DIR at a temporary
directory and forces the mock provider *before* fabric_studio reads any
configuration.
"""
import atexit
import os
import shutil
import tempfile

DATA_DIR = tempfile.mkdtemp(prefix="fabric-studio-tests-")
os.environ["DATA_DIR"] = DATA_DIR
os.environ["VTON_PROVIDER"] = "mock"
os.environ.setdefault("FABRIC_STUDIO_DEBUG", "true")
os.environ.pop("FABRIC_IMPORT_ALLOWED_HOSTS", None)

atexit.register(lambda: shutil.rmtree(DATA_DIR, ignore_errors=True))

from fabric_studio import catalog, imaging, storage, swatches  # noqa: E402
from fabric_studio.catalog import FABRIC_STORE, OUTFIT_STORE  # noqa: E402
from fabric_studio.fabric_processor import processor  # noqa: E402
from fabric_studio.garment_remake import _index as REMAKE_INDEX  # noqa: E402
from fabric_studio.generations import GENERATION_STORE  # noqa: E402

storage.ensure_dirs()


def person_image(width=700, height=1100, color=(198, 190, 178)):
    """A synthetic 'photo' that passes the person-photo validator."""
    from PIL import ImageDraw

    image = imaging.Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    draw.ellipse([width * 0.42, height * 0.06, width * 0.58, height * 0.17], fill=(150, 120, 95))
    draw.rectangle([width * 0.38, height * 0.17, width * 0.62, height * 0.62], fill=(80, 90, 120))
    draw.rectangle([width * 0.41, height * 0.62, width * 0.59, height * 0.93], fill=(45, 50, 65))
    return image


def person_data_url(**kwargs):
    return imaging.to_data_url(person_image(**kwargs))


def make_fabric(fabric_id="fab_test", kind="geometric", palette=None, process=True, **fields):
    """Create (and by default process) a fabric without running migrations."""
    palette = palette or ["#123a75", "#c62f2f", "#d8a63c"]
    image = swatches.render(kind, 640, palette)
    relative = "fabrics/original/%s.jpg" % fabric_id
    storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))
    record = {
        "id": fabric_id,
        "name": fields.pop("name", "Test %s" % kind.title()),
        "category": fields.pop("category", "Ankara"),
        "image_path": relative,
        "image_url": storage.media_url(relative),
        "is_active": True,
        "review_status": catalog.REVIEW_APPROVED,
    }
    record.update(fields)
    catalog.save_fabric(record)
    if process:
        return catalog.ensure_fabric_processed(fabric_id)
    return catalog.get_fabric(fabric_id)


def make_outfit(outfit_id="out_test", template_id="modern-senator", **fields):
    record = {
        "id": outfit_id,
        "name": fields.pop("name", "Test Outfit"),
        "category": fields.pop("category", "Men"),
        "template_id": template_id,
        "garment_type": fields.pop("garment_type", "one-pieces"),
        "mask_type": "full_body",
        "is_active": True,
    }
    record.update(fields)
    return catalog.save_outfit(record)


def reset_stores():
    FABRIC_STORE.replace_all([])
    OUTFIT_STORE.replace_all([])
    GENERATION_STORE.replace_all([])
    # The remake cache is keyed by content, so it would otherwise carry across
    # tests and make the first generation of a test look like a cache hit.
    REMAKE_INDEX.replace_all([])
