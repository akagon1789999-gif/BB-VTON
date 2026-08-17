"""Web catalogue importer — admin-only, reviewed, never customer-facing.

    WEB SOURCE -> FETCH -> VALIDATE -> EXTRACT -> LICENCE CHECK -> NORMALISE
              -> THUMBNAIL -> METADATA -> SAVE (pending) -> ADMIN REVIEW -> PUBLISH

Rules enforced here, not left to the operator:

* The customer-facing app never fetches a third-party URL. Only this admin
  path does, and only into a pending record.
* Fetching is limited to hosts on FABRIC_IMPORT_ALLOWED_HOSTS. With the list
  empty the importer is off.
* robots.txt is honoured for our user agent, with size, time and content-type
  limits on the download, and private/loopback addresses are refused (SSRF).
* An import is never published automatically. Records land with
  review_status=pending and is_active=false, and publishing is blocked until a
  licence and source are recorded.
"""
import ipaddress
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from . import catalog, config, imaging, storage
from .errors import ValidationError, log
from .fabric_processor import processor

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_robots_cache = {}
_ROBOTS_TTL_SECONDS = 3600


def importer_enabled():
    return bool(config.import_allowed_hosts())


def allowed_hosts():
    return config.import_allowed_hosts()


# ------------------------------------------------------------- url checks ---
def validate_url(url):
    url = (url or "").strip()
    if not url:
        raise ValidationError("Enter the image URL to import.", detail="Empty import URL")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError(
            "Only https:// image URLs can be imported.",
            detail="Rejected scheme %r" % parsed.scheme,
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValidationError("That doesn't look like a valid URL.", detail="No host in %r" % url)

    hosts = allowed_hosts()
    if not hosts:
        raise ValidationError(
            "The catalogue importer is switched off.",
            detail="FABRIC_IMPORT_ALLOWED_HOSTS is empty; add the source host to enable importing.",
        )
    if not any(host == allowed or host.endswith("." + allowed) for allowed in hosts):
        raise ValidationError(
            "That website isn't on the approved import list.",
            detail="Host %s not in %s" % (host, ", ".join(hosts)),
        )
    _reject_private_address(host)
    return parsed


def _reject_private_address(host):
    """Refuse hosts that resolve to internal addresses (SSRF guard)."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError("We couldn't reach that website.", detail="DNS failure for %s: %s" % (host, exc))
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValidationError(
                "That website isn't allowed.",
                detail="Host %s resolves to non-public address %s" % (host, address),
            )


def robots_allows(url):
    parsed = urllib.parse.urlparse(url)
    root = "%s://%s" % (parsed.scheme, parsed.netloc)
    cached = _robots_cache.get(root)
    if cached and time.time() - cached[1] < _ROBOTS_TTL_SECONDS:
        parser = cached[0]
    else:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(root + "/robots.txt")
        try:
            parser.read()
        except Exception as exc:
            # A missing or unreadable robots.txt is treated as "allowed", which
            # is what the standard says, but it is logged.
            log.info("robots.txt unavailable for %s (%s); continuing", root, exc)
            parser = None
        _robots_cache[root] = (parser, time.time())
    if parser is None:
        return True
    return parser.can_fetch(config.import_user_agent(), url)


# ------------------------------------------------------------------ fetch ---
def fetch_image(url):
    """Download an image with content-type, size and time limits."""
    validate_url(url)
    if not robots_allows(url):
        raise ValidationError(
            "That website asks us not to download this image.",
            detail="robots.txt disallows %s" % url,
        )
    request = urllib.request.Request(url, headers={
        "User-Agent": config.import_user_agent(),
        "Accept": "image/*",
    })
    limit = config.import_max_bytes()
    try:
        with urllib.request.urlopen(request, timeout=config.import_timeout_seconds()) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise ValidationError(
                    "That link isn't a JPG, PNG, or WEBP image.",
                    detail="Content-Type %r" % content_type,
                )
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > limit:
                raise ValidationError(
                    "That image is too large to import.",
                    detail="Content-Length %s exceeds %d" % (declared, limit),
                )
            raw = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise ValidationError(
            "We couldn't download that image.",
            detail="HTTP %s fetching %s" % (exc.code, url),
        )
    except urllib.error.URLError as exc:
        raise ValidationError(
            "We couldn't reach that website.",
            detail="URL error fetching %s: %s" % (url, exc),
        )
    if len(raw) > limit:
        raise ValidationError(
            "That image is too large to import.",
            detail="Downloaded body exceeded %d bytes" % limit,
        )
    return raw, content_type


# ----------------------------------------------------------------- import ---
def import_fabric(url, payload=None, imported_by="admin"):
    """Fetch, analyse and stage a fabric for review. Never publishes."""
    payload = dict(payload or {})
    raw, content_type = fetch_image(url)
    normalized, metadata = processor.analyze_bytes(raw)

    name = (payload.get("name") or "").strip() or _name_from_url(url)
    fabric_id = storage.new_id("fab")
    extension = ALLOWED_CONTENT_TYPES.get(content_type, ".jpg")
    original_relative = "imports/%s%s" % (fabric_id, extension)
    storage.write_media(original_relative, raw)

    thumbnail = imaging.make_thumbnail(normalized, config.fabric_thumbnail_size())
    thumb_relative = "imports/%s-thumb.jpg" % fabric_id
    storage.write_media(thumb_relative, imaging.encode_image(thumbnail, "JPEG", 82))

    license_text = (payload.get("license") or "").strip()
    record = {
        "id": fabric_id,
        "name": name,
        "slug": catalog.slugify(name),
        "category": (payload.get("category") or "Contemporary").strip(),
        "subcategory": (payload.get("subcategory") or "").strip(),
        "description": (payload.get("description") or "").strip(),
        "pattern_type": (payload.get("pattern_type") or metadata.get("patternType") or "").strip(),
        "texture_description": (payload.get("texture_description") or metadata.get("texture") or "").strip(),
        "primary_colors": [c["name"] for c in metadata.get("dominantColors", [])],
        "secondary_colors": [c["name"] for c in metadata.get("secondaryColors", [])],
        "tags": payload.get("tags") or [],
        "region": (payload.get("region") or "").strip(),
        "image_path": original_relative,
        "image_url": storage.media_url(original_relative),
        "thumbnail_url": storage.media_url(thumb_relative),
        "source_url": url,
        "source_name": (payload.get("source_name") or urllib.parse.urlparse(url).hostname or "").strip(),
        "license": license_text,
        "attribution": (payload.get("attribution") or "").strip(),
        # Two independent gates: unreviewed AND inactive.
        "review_status": catalog.REVIEW_PENDING,
        "is_active": False,
        "license_clear": bool(license_text),
        "imported_by": imported_by,
        "imported_at": catalog.now(),
        "created_at": catalog.now(),
        "updated_at": catalog.now(),
        "detected_metadata": metadata,
    }
    catalog.FABRIC_STORE.upsert(record)
    return record


def _name_from_url(url):
    path = urllib.parse.urlparse(url).path
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    cleaned = stem.replace("-", " ").replace("_", " ").strip()
    return (cleaned[:80] or "Imported fabric").title()


def list_pending():
    records = [r for r in catalog.FABRIC_STORE.all()
               if r.get("review_status") == catalog.REVIEW_PENDING]
    records.sort(key=lambda r: r.get("imported_at") or r.get("created_at") or "", reverse=True)
    return records


def publish(fabric_id, reviewer="admin"):
    """Approve a pending import. Blocked until licensing is recorded."""
    record = catalog.FABRIC_STORE.get(fabric_id)
    if record is None:
        raise ValidationError("That import no longer exists.", detail="Fabric %s not found" % fabric_id)
    if not (record.get("license") or "").strip():
        raise ValidationError(
            "Add the licence or usage rights for this image before publishing it.",
            detail="Refusing to publish %s without a licence" % fabric_id,
        )
    if not (record.get("source_url") or "").strip():
        raise ValidationError(
            "Add the source URL for this image before publishing it.",
            detail="Refusing to publish %s without a source URL" % fabric_id,
        )
    catalog.FABRIC_STORE.update(fabric_id, {
        "review_status": catalog.REVIEW_APPROVED,
        "is_active": True,
        "license_clear": True,
        "reviewed_by": reviewer,
        "reviewed_at": catalog.now(),
        "updated_at": catalog.now(),
    })
    return catalog.ensure_fabric_processed(fabric_id, force=True)


def reject(fabric_id, reason="", reviewer="admin"):
    record = catalog.FABRIC_STORE.get(fabric_id)
    if record is None:
        raise ValidationError("That import no longer exists.", detail="Fabric %s not found" % fabric_id)
    catalog.FABRIC_STORE.update(fabric_id, {
        "review_status": catalog.REVIEW_REJECTED,
        "is_active": False,
        "review_note": (reason or "")[:300],
        "reviewed_by": reviewer,
        "reviewed_at": catalog.now(),
        "updated_at": catalog.now(),
    })
    return catalog.FABRIC_STORE.get(fabric_id)


def status():
    return {
        "enabled": importer_enabled(),
        "allowedHosts": allowed_hosts(),
        "maxBytes": config.import_max_bytes(),
        "userAgent": config.import_user_agent(),
        "pending": len(list_pending()),
    }
