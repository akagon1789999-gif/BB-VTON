"""Where uploaded bytes live between the browser and FASHN.

One driver, writing under ``DATA_DIR/studio-uploads`` and serving the bytes
back through ``/api/studio/files/*``. Point DATA_DIR at a mounted volume in
production, exactly as server.py already does for the catalogue.

The directory is deliberately not called ``studio``: DATA_DIR defaults to the
repo root, and that would put customer uploads inside this package.

``is_publicly_reachable`` decides whether FASHN gets a hosted URL or a data
URI. Hosted URLs are preferred -- base64 inflates the payload and slows the
round trip -- but on localhost FASHN cannot reach us, so callers inline
instead.
"""
import os
import re
import threading
import uuid
from pathlib import Path

from .errors import STORAGE_ERROR, StudioError

_lock = threading.Lock()

UNSAFE = re.compile(r"[^a-zA-Z0-9._/-]")
LOCAL_HOST = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\.local(:|$)", re.I)


def data_root():
    """Same convention as server.py: DATA_DIR or the repo root."""
    root = os.environ.get("DATA_DIR") or str(Path(__file__).resolve().parent.parent)
    return Path(root).resolve()


def root_dir():
    return data_root() / "studio-uploads"


def origin():
    return (os.environ.get("APP_URL") or "").strip().rstrip("/")


def is_publicly_reachable():
    """True only when APP_URL is a public https origin.

    That means a tunnel or a real deployment. On plain localhost FASHN cannot
    fetch from us, so callers fall back to data URIs.
    """
    value = origin()
    return bool(value) and value.startswith("https://") and not LOCAL_HOST.search(value)


def new_key(slot, extension):
    return "%s/%s.%s" % (slot, uuid.uuid4().hex, extension)


def path_for(key):
    """Resolve a key to a path, refusing anything that escapes the tree."""
    safe = UNSAFE.sub("_", str(key)).replace("..", "_").lstrip("/")
    root = root_dir().resolve()
    candidate = (root / safe).resolve()
    if candidate != root and root not in candidate.parents:
        raise StudioError(
            STORAGE_ERROR,
            "That file path is not allowed.",
            http_status=400,
        )
    return candidate


def put(key, body, content_type):
    target = path_for(key)
    with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling then rename, so a reader never sees a half file.
        temp = target.with_suffix(target.suffix + ".part")
        temp.write_bytes(body)
        temp.replace(target)
        target.with_name(target.name + ".type").write_text(content_type, encoding="utf-8")
    return {"key": key, "url": url_for(key), "bytes": len(body), "contentType": content_type}


def get(key):
    try:
        target = path_for(key)
    except StudioError:
        return None
    if not target.is_file():
        return None
    content_type = "application/octet-stream"
    sidecar = target.with_name(target.name + ".type")
    if sidecar.is_file():
        content_type = sidecar.read_text(encoding="utf-8").strip() or content_type
    return {"body": target.read_bytes(), "contentType": content_type}


def delete(key):
    try:
        target = path_for(key)
    except StudioError:
        return
    target.unlink(missing_ok=True)
    target.with_name(target.name + ".type").unlink(missing_ok=True)


def url_for(key):
    """An absolute URL when we know our public origin, a relative one otherwise."""
    path = "/api/studio/files/%s" % key
    base = origin()
    return (base + path) if base else path
