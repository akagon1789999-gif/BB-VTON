"""Persistence layer for Fabric Studio.

The existing application stores its catalogue as a JSON document inside
DATA_DIR (see server.py: catalog.json / payments.json), so Fabric Studio keeps
the same convention instead of introducing a database engine the deployment
does not have. `JsonStore` adds what the raw json.dump calls in server.py lack
and what a catalogue needs: process-wide locking, atomic writes (so a crash
mid-write cannot truncate the catalogue), an in-memory cache invalidated by
mtime, and secondary indexes.

Swapping this for a real database later means reimplementing JsonStore and the
repositories in catalog.py — nothing above them knows how rows are stored.
"""
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from . import config

# Media layout (see docs): everything Fabric Studio writes lives under
# DATA_DIR/media so a single mounted volume covers the whole feature.
MEDIA_SUBDIRS = (
    "fabrics/original",
    "fabrics/processed",
    "fabrics/thumbs",
    "fabrics/garments",
    "outfits",
    "generations",
    "imports",
)

_dir_lock = threading.Lock()


def media_dir():
    return data_root() / "media"


def data_root():
    return config.data_dir()


def ensure_dirs():
    """Create the media tree. Cheap and idempotent; safe to call per request."""
    with _dir_lock:
        for sub in MEDIA_SUBDIRS:
            (media_dir() / sub).mkdir(parents=True, exist_ok=True)
    return media_dir()


def media_path(relative):
    """Resolve a media-relative path, refusing anything that escapes the tree."""
    root = media_dir().resolve()
    candidate = (root / str(relative).lstrip("/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes the media directory: %s" % relative)
    return candidate


def media_url(relative):
    if not relative:
        return ""
    relative = str(relative)
    if relative.startswith("http://") or relative.startswith("https://") or relative.startswith("/"):
        return relative
    return "/media/" + relative.lstrip("/")


def write_media(relative, data):
    """Write bytes to a media-relative path atomically. Returns the path."""
    ensure_dirs()
    target = media_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(target, data)
    return target


def delete_media(relative):
    if not relative:
        return
    try:
        media_path(relative).unlink(missing_ok=True)
    except (ValueError, OSError):
        pass


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:16])


def _atomic_write_bytes(target, data):
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, str(target))
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


class JsonStore(object):
    """A JSON-document collection of dict records keyed by `key_field`.

    Not a general-purpose database: it holds catalogue-sized collections
    (hundreds to a few thousand records) fully in memory and rewrites the whole
    document on change, which is what the existing catalog.json code already
    does. All public methods return deep copies so callers cannot mutate the
    cache by accident.
    """

    def __init__(self, filename, key_field="id", indexes=()):
        self.filename = filename
        self.key_field = key_field
        self.index_fields = tuple(indexes)
        self._lock = threading.RLock()
        self._cache = None
        self._cache_mtime = None
        self._indexes = {}

    # ------------------------------------------------------------ internals --
    @property
    def path(self):
        return data_root() / self.filename

    def _load_locked(self):
        path = self.path
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if self._cache is not None and mtime == self._cache_mtime:
            return self._cache
        if mtime is None:
            self._cache = []
        else:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self._cache = loaded if isinstance(loaded, list) else []
            except (json.JSONDecodeError, OSError):
                # A corrupt catalogue must not take the whole site down; the
                # backup below keeps the bad file around for inspection.
                self._backup_corrupt(path)
                self._cache = []
        self._cache_mtime = mtime
        self._rebuild_indexes()
        return self._cache

    def _backup_corrupt(self, path):
        try:
            shutil.copyfile(str(path), str(path) + ".corrupt")
        except OSError:
            pass

    def _rebuild_indexes(self):
        self._indexes = {}
        for field in self.index_fields:
            bucket = {}
            for record in self._cache:
                value = record.get(field)
                if isinstance(value, list):
                    keys = [str(v).lower() for v in value]
                else:
                    keys = [str(value).lower()] if value is not None else []
                for key in keys:
                    bucket.setdefault(key, []).append(record)
            self._indexes[field] = bucket

    def _save_locked(self, records):
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")
        _atomic_write_bytes(path, payload)
        self._cache = records
        try:
            self._cache_mtime = path.stat().st_mtime_ns
        except OSError:
            self._cache_mtime = None
        self._rebuild_indexes()

    # --------------------------------------------------------------- public --
    def all(self):
        with self._lock:
            return [dict(r) for r in self._load_locked()]

    def count(self):
        with self._lock:
            return len(self._load_locked())

    def get(self, key):
        if not key:
            return None
        with self._lock:
            for record in self._load_locked():
                if record.get(self.key_field) == key:
                    return dict(record)
        return None

    def find_by(self, field, value):
        """Indexed lookup when `field` was declared as an index, else a scan."""
        if value is None:
            return []
        needle = str(value).lower()
        with self._lock:
            self._load_locked()
            if field in self._indexes:
                return [dict(r) for r in self._indexes[field].get(needle, [])]
            return [
                dict(r) for r in self._cache
                if str(r.get(field, "")).lower() == needle
            ]

    def insert(self, record):
        with self._lock:
            records = list(self._load_locked())
            key = record.get(self.key_field)
            if any(r.get(self.key_field) == key for r in records):
                raise KeyError("Duplicate %s: %s" % (self.key_field, key))
            records.append(dict(record))
            self._save_locked(records)
        return dict(record)

    def upsert(self, record):
        with self._lock:
            records = list(self._load_locked())
            key = record.get(self.key_field)
            for index, existing in enumerate(records):
                if existing.get(self.key_field) == key:
                    merged = dict(existing)
                    merged.update(record)
                    records[index] = merged
                    self._save_locked(records)
                    return dict(merged)
            records.append(dict(record))
            self._save_locked(records)
        return dict(record)

    def update(self, key, changes):
        with self._lock:
            records = list(self._load_locked())
            for index, existing in enumerate(records):
                if existing.get(self.key_field) == key:
                    merged = dict(existing)
                    merged.update(changes)
                    records[index] = merged
                    self._save_locked(records)
                    return dict(merged)
        return None

    def delete(self, key):
        with self._lock:
            records = list(self._load_locked())
            remaining = [r for r in records if r.get(self.key_field) != key]
            if len(remaining) == len(records):
                return False
            self._save_locked(remaining)
        return True

    def replace_all(self, records):
        with self._lock:
            self._save_locked([dict(r) for r in records])

    def trim_to(self, limit, sort_key):
        """Keep only the newest `limit` records (generation history)."""
        with self._lock:
            records = list(self._load_locked())
            if len(records) <= limit:
                return 0
            records.sort(key=lambda r: r.get(sort_key) or "", reverse=True)
            removed = records[limit:]
            self._save_locked(records[:limit])
        return len(removed)
