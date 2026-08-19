"""Step one of the two-step pipeline: the garment, remade in the chosen fabric.

    fabric image + garment reference  ->  AI generated garment  ->  (step two)

The engine keeps the garment's design, cut, embroidery placement and silhouette
and replaces only the material, which is the one thing local compositing cannot
do when the reference is a photograph of someone wearing the outfit.

Every remake is cached by (fabric content, garment content, prompt, model), so a
fabric and garment pairing is generated once and every later customer who picks
that pairing skips straight to the try-on. That matters: step one costs credits,
and without the cache it would cost them on every visit.
"""
import json
import time

from . import config, imaging, prompts, storage
from .errors import ProviderError, log
from .virtual_tryon import STATUS_COMPLETED, GarmentRemakeRequest, get_provider

CACHE_DIR = "fabrics/garments"
INDEX_FILE = "garment_remakes.json"
REMAKE_VERSION = 1

_index = storage.JsonStore(INDEX_FILE, key_field="key")


def cache_key(fabric_hash, garment_hash, prompt, model):
    digest = imaging.content_hash(
        ("%s|%s|%s|%s|%d" % (fabric_hash, garment_hash, prompt, model, REMAKE_VERSION)).encode("utf-8")
    )
    return digest


def lookup(key):
    """Return the cached remake for this pairing, if it is still on disk."""
    record = _index.get(key)
    if not record:
        return None
    relative = record.get("path")
    try:
        if relative and storage.media_path(relative).exists():
            return record
    except ValueError:
        pass
    _index.delete(key)
    return None


def remake(fabric_image, garment_image, fabric_hash, garment_hash,
           fabric=None, outfit=None, user_prompt=None, mode="fast", poll=True):
    """Remake the garment in the fabric, or return the cached result.

    Returns {path, url, cached, key, prompt, ms, creditsUsed}.
    """
    provider = get_provider()
    if not provider.supports_garment_remake:
        raise ProviderError(
            detail="Provider %s cannot remake garments" % provider.name
        )

    prompt = prompts.build_remake_prompt(outfit or {}, fabric or {}, user_prompt)
    model = getattr(config, "vton_edit_model")()
    key = cache_key(fabric_hash, garment_hash, prompt, model)

    cached = lookup(key)
    if cached:
        return {
            "path": cached["path"],
            "url": storage.media_url(cached["path"]),
            "cached": True,
            "key": key,
            "prompt": prompt,
            "ms": 0,
            "creditsUsed": 0,
        }

    started = time.time()
    request = GarmentRemakeRequest(
        garment_image=garment_image,
        fabric_image=fabric_image,
        prompt=prompt,
        options={"mode": mode},
        request_id=key,
    )
    result = provider.remake_garment(request)
    if poll and not result.is_terminal:
        result = _poll(provider, result)

    if result.status != STATUS_COMPLETED or not result.result_image:
        raise ProviderError(
            result.error or "We couldn't prepare that garment. Please try again.",
            detail="Garment remake returned %s (%s)" % (result.status, result.error_code),
        )

    relative = "%s/remade-%s.jpg" % (CACHE_DIR, key)
    _store(relative, result.result_image)
    _index.upsert({
        "key": key,
        "path": relative,
        "fabricHash": fabric_hash,
        "garmentHash": garment_hash,
        "model": model,
        "provider": provider.name,
        "prompt": prompt,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return {
        "path": relative,
        "url": storage.media_url(relative),
        "cached": False,
        "key": key,
        "prompt": prompt,
        "ms": int((time.time() - started) * 1000),
        "creditsUsed": (result.metadata or {}).get("creditsUsed"),
    }


def _poll(provider, result):
    deadline = time.time() + config.vton_timeout_seconds()
    while time.time() < deadline:
        time.sleep(2.0)
        polled = provider.get_status(result.generation_id)
        if polled.is_terminal:
            return polled
        result = polled
    raise ProviderError(
        "Preparing that garment took too long. Please try again.",
        detail="Garment remake timed out",
    )


def _store(relative, source_url):
    """Keep our own copy: the provider's CDN link is not ours to depend on."""
    if source_url.startswith("data:"):
        raw = imaging.decode_data_url(source_url, max_bytes=16 * 1024 * 1024)
    elif source_url.startswith("/media/"):
        raw = storage.media_path(source_url[len("/media/"):]).read_bytes()
    else:
        import urllib.request
        request = urllib.request.Request(source_url, headers={"User-Agent": "BB-FabricStudio/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
    image = imaging.open_image(raw)
    storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))


def stats():
    records = _index.all()
    return {"cachedRemakes": len(records)}
