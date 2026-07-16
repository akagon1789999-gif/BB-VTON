#!/usr/bin/env python3
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import wraps
from html import escape
from pathlib import Path

from flask import Flask, Response, request, send_from_directory


ROOT = Path(__file__).resolve().parent
FASHN_API_BASE = "https://api.fashn.ai/v1"

# Point DATA_DIR at a mounted persistent volume in production (e.g. Railway
# volume mounted at /data, with DATA_DIR=/data) so uploads and catalog.json
# survive redeploys. Defaults to the repo root for local/dev use.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
CATALOG_FILE = DATA_DIR / "catalog.json"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

DEFAULT_CATALOG = [
    {"id": "s1", "slotId": "suit-1", "name": "Chocolate Brown Pantsuit", "brand": "Sean Alexander", "price": "₦359", "fitType": "Slim Fit", "tags": ["Slim Fit", "Solid", "2PC"], "category": "Suits", "img": "assets/suit-1.jpg"},
    {"id": "s2", "slotId": "suit-2", "name": "Mauve Peplum Suit", "brand": "Bryan Michaels", "price": "₦339", "fitType": "Slim Fit", "tags": ["Slim Fit", "Peplum", "2PC"], "category": "Suits", "img": "assets/suit-2.png"},
    {"id": "s3", "slotId": "suit-3", "name": "Sage Double-Breasted Blazer", "brand": "Bryan Michaels", "price": "₦429", "fitType": "Classic Fit", "tags": ["Classic Fit", "Solid", "2PC"], "category": "Blazers", "img": "assets/suit-3.jpg"},
    {"id": "s7", "slotId": "suit-7", "name": "Charcoal Double-Breasted Suit", "brand": "Bryan Michaels", "price": "₦329", "fitType": "Classic Fit", "tags": ["Classic Fit", "Solid", "2PC"], "category": "Suits", "img": "assets/suit-7.jpg"},
    {"id": "s8", "slotId": "suit-8", "name": "Safia Print Occasion Dress", "brand": "Stacy Adams", "price": "₦379", "fitType": "Hybrid Fit", "tags": ["Hybrid Fit", "Printed", "1PC"], "category": "Dresses", "img": "assets/suit-8.jpg"},
    {"id": "s9", "slotId": "suit-9", "name": "Emerald Leaf Print Dress", "brand": "Sean Alexander", "price": "₦299", "fitType": "Slim Fit", "tags": ["Slim Fit", "Floral", "1PC"], "category": "Dresses", "img": "assets/suit-9.jpg"},
    {"id": "s10", "slotId": "suit-10", "name": "Sky Blue Double-Breasted Blazer", "brand": "Bryan Michaels", "price": "₦249", "fitType": "Slim Fit", "tags": ["Slim Fit", "Solid", "1PC"], "category": "Blazers", "img": "assets/suit-10.jpg"},
    {"id": "s11", "slotId": "suit-11", "name": "Slate Gray Power Suit", "brand": "Stacy Adams", "price": "₦389", "fitType": "Hybrid Fit", "tags": ["Hybrid Fit", "Solid", "2PC"], "category": "Suits", "img": "assets/suit-11.jpg"},
    {"id": "s12", "slotId": "suit-12", "name": "Camel Overcoat Ensemble", "brand": "Bryan Michaels", "price": "₦319", "fitType": "Slim Fit", "tags": ["Slim Fit", "Solid", "3PC"], "category": "Coats", "img": "assets/suit-12.jpg"},
    {"id": "s13", "slotId": "suit-13", "name": "Maroon Brocade Agbada Vest", "brand": "Tazzio", "price": "₦449", "fitType": "Slim Fit", "tags": ["Slim Fit", "Brocade", "2PC"], "category": "Traditional Wear", "img": "assets/suit-13.jpg"},
    {"id": "s14", "slotId": "suit-14", "name": "Heritage Plaid Three-Piece", "brand": "Stacy Adams", "price": "₦279", "fitType": "Hybrid Fit", "tags": ["Hybrid Fit", "Plaid", "3PC"], "category": "Suits", "img": "assets/suit-14.jpg"},
    {"id": "s15", "slotId": "suit-15", "name": "Crimson Gold Brocade Coat Dress", "brand": "Tazzio", "price": "₦459", "fitType": "Hybrid Fit", "tags": ["Hybrid Fit", "Brocade", "1PC"], "category": "Coats", "img": "assets/suit-15.jpg"},
    {"id": "s16", "slotId": "suit-16", "name": "Ivory Windowpane Puff-Sleeve Dress", "brand": "Sean Alexander", "price": "₦319", "fitType": "Slim Fit", "tags": ["Slim Fit", "Plaid", "1PC"], "category": "Dresses", "img": "assets/suit-16.jpg"},
    {"id": "s17", "slotId": "suit-17", "name": "Emerald Bloom Bow Dress", "brand": "Bryan Michaels", "price": "₦339", "fitType": "Slim Fit", "tags": ["Slim Fit", "Floral", "1PC"], "category": "Dresses", "img": "assets/suit-17.jpg"},
    {"id": "s18", "slotId": "suit-18", "name": "Sunset Colorblock Godet Skirt Dress", "brand": "Stacy Adams", "price": "₦369", "fitType": "Hybrid Fit", "tags": ["Hybrid Fit", "Colorblock", "1PC"], "category": "Dresses", "img": "assets/suit-18.jpg"},
    {"id": "s19", "slotId": "suit-19", "name": "Noir Swirl Stripe Gown", "brand": "Tazzio", "price": "₦399", "fitType": "Classic Fit", "tags": ["Classic Fit", "Striped", "1PC"], "category": "Dresses", "img": "assets/suit-19.jpg"},
]


def load_local_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

app = Flask(__name__, static_folder=None)
# Generous cap (photos + product images as base64 can run several MB); prevents unbounded memory use.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


def json_response(status, payload):
    return Response(json.dumps(payload), status=status, mimetype="application/json")


def load_catalog():
    if not CATALOG_FILE.exists():
        save_catalog(DEFAULT_CATALOG)
        return [dict(item) for item in DEFAULT_CATALOG]
    try:
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [dict(item) for item in DEFAULT_CATALOG]


def save_catalog(items):
    CATALOG_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(text):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "item"


def requires_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
        auth = request.authorization
        if not admin_password or not auth or not auth.password or not secrets.compare_digest(auth.password, admin_password):
            return Response(
                json.dumps({"message": "Unauthorized"}),
                status=401,
                mimetype="application/json",
                headers={"WWW-Authenticate": 'Basic realm="BB Admin"'},
            )
        return f(*args, **kwargs)

    return wrapper


def proxy_to_fashn(endpoint, method="GET", payload=None):
    api_key = os.environ.get("FASHN_API_KEY", "").strip()
    if not api_key:
        return json_response(500, {
            "message": "Server is missing FASHN_API_KEY. Add it to .env or your environment and restart server."
        })

    data = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "BB-Virtual-TryOn-Proxy/1.0",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(f"{FASHN_API_BASE}{endpoint}", data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            body = res.read()
            content_type = res.headers.get("Content-Type", "application/json; charset=UTF-8")
            resp = Response(body, status=res.status)
            resp.headers["Content-Type"] = content_type
            resp.headers["Cache-Control"] = "no-store"
            credits_used = res.headers.get("x-fashn-credits-used")
            if credits_used:
                resp.headers["x-fashn-credits-used"] = credits_used
            return resp
    except urllib.error.HTTPError as exc:
        body = exc.read()
        content_type = exc.headers.get("Content-Type", "application/json; charset=UTF-8")
        resp = Response(body, status=exc.code)
        resp.headers["Content-Type"] = content_type
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as exc:
        return json_response(502, {"message": f"FASHN proxy request failed: {exc}"})


@app.post("/api/fashn/run")
def fashn_run():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response(400, {"message": "Invalid JSON body."})
    return proxy_to_fashn("/run", method="POST", payload=payload)


@app.get("/api/fashn/status/<prediction_id>")
def fashn_status(prediction_id):
    prediction_id = (prediction_id or "").strip()
    if not prediction_id:
        return json_response(400, {"message": "Missing prediction id."})
    return proxy_to_fashn(f"/status/{prediction_id}", method="GET")


@app.get("/api/catalog")
def get_catalog():
    resp = json_response(200, load_catalog())
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/admin/ping")
@requires_admin
def admin_ping():
    return json_response(200, {"ok": True})


def _read_item_fields(form):
    name = (form.get("name") or "").strip()
    brand = (form.get("brand") or "").strip()
    price = (form.get("price") or "").strip()
    fit_type = (form.get("fitType") or "").strip()
    category = (form.get("category") or "").strip()
    tags_raw = (form.get("tags") or "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    if price and not price.startswith("₦"):
        price = f"₦{price}"
    return name, brand, price, fit_type, category, tags


@app.post("/api/admin/catalog")
@requires_admin
def create_catalog_item():
    name, brand, price, fit_type, category, tags = _read_item_fields(request.form)
    if not name or not price:
        return json_response(400, {"message": "Name and price are required."})

    image = request.files.get("image")
    if not image or not image.filename:
        return json_response(400, {"message": "An image is required."})
    ext = ALLOWED_IMAGE_TYPES.get(image.mimetype)
    if not ext:
        return json_response(400, {"message": "Unsupported image type. Use JPG, PNG, or WEBP."})

    catalog = load_catalog()
    new_id = f"s{int(time.time() * 1000)}"
    filename = f"{slugify(name)}-{new_id}{ext}"
    image.save(UPLOADS_DIR / filename)

    item = {
        "id": new_id,
        "slotId": new_id,
        "name": name,
        "brand": brand or "BB Apparel",
        "price": price,
        "fitType": fit_type or "Slim Fit",
        "tags": tags or [fit_type or "Slim Fit"],
        "category": category or "Suits",
        "img": f"/uploads/{filename}",
    }
    catalog.append(item)
    save_catalog(catalog)
    return json_response(201, item)


@app.put("/api/admin/catalog/<item_id>")
@requires_admin
def update_catalog_item(item_id):
    catalog = load_catalog()
    item = next((x for x in catalog if x["id"] == item_id), None)
    if not item:
        return json_response(404, {"message": "Item not found."})

    name, brand, price, fit_type, category, tags = _read_item_fields(request.form)
    if name:
        item["name"] = name
    if brand:
        item["brand"] = brand
    if price:
        item["price"] = price
    if fit_type:
        item["fitType"] = fit_type
    if category:
        item["category"] = category
    if "tags" in request.form:
        item["tags"] = tags

    image = request.files.get("image")
    if image and image.filename:
        ext = ALLOWED_IMAGE_TYPES.get(image.mimetype)
        if not ext:
            return json_response(400, {"message": "Unsupported image type. Use JPG, PNG, or WEBP."})
        old_img = item.get("img", "")
        filename = f"{slugify(item['name'])}-{item_id}{ext}"
        image.save(UPLOADS_DIR / filename)
        item["img"] = f"/uploads/{filename}"
        if old_img.startswith("/uploads/") and old_img != item["img"]:
            (UPLOADS_DIR / old_img[len('/uploads/'):]).unlink(missing_ok=True)

    save_catalog(catalog)
    return json_response(200, item)


@app.delete("/api/admin/catalog/<item_id>")
@requires_admin
def delete_catalog_item(item_id):
    catalog = load_catalog()
    item = next((x for x in catalog if x["id"] == item_id), None)
    if not item:
        return json_response(404, {"message": "Item not found."})

    catalog = [x for x in catalog if x["id"] != item_id]
    save_catalog(catalog)

    img = item.get("img", "")
    if img.startswith("/uploads/"):
        (UPLOADS_DIR / img[len('/uploads/'):]).unlink(missing_ok=True)
    return json_response(200, {"message": "Deleted."})


def _abs_url(base_url, path):
    if not path:
        path = "assets/bb-logo.png"
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def render_index_html(shared_id=None):
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    base_url = request.host_url

    title = "BB Apparel — Virtual Try-On"
    description = "Upload your photo and virtually try on suits, blazers, and dresses before you buy — powered by AI."
    image = _abs_url(base_url, "assets/bb-logo.png")
    page_url = base_url

    item = None
    if shared_id:
        item = next((x for x in load_catalog() if x["id"] == shared_id), None)

    if item:
        title = f"{item['name']} — BB Apparel"
        subtitle = " · ".join([p for p in [item.get("brand"), item.get("category")] if p])
        price = item.get("price", "")
        description = " ".join(filter(None, [subtitle, price, "— See it on you with our free AI virtual try-on."]))
        image = _abs_url(base_url, item.get("img", ""))
        page_url = base_url.rstrip("/") + "/?shared=" + urllib.parse.quote(item["id"])

    meta_tags = (
        '\n  <meta property="og:type" content="website">\n'
        '  <meta property="og:site_name" content="BB Apparel">\n'
        f'  <meta property="og:title" content="{escape(title)}">\n'
        f'  <meta property="og:description" content="{escape(description)}">\n'
        f'  <meta property="og:image" content="{escape(image)}">\n'
        f'  <meta property="og:url" content="{escape(page_url)}">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        f'  <meta name="twitter:title" content="{escape(title)}">\n'
        f'  <meta name="twitter:description" content="{escape(description)}">\n'
        f'  <meta name="twitter:image" content="{escape(image)}">\n'
    )
    return html.replace("</head>", meta_tags + "</head>", 1)


@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    response = send_from_directory(UPLOADS_DIR, filename)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def static_files(path):
    if path == "index.html":
        shared_id = (request.args.get("shared") or "").strip()
        html = render_index_html(shared_id or None)
        response = Response(html, mimetype="text/html")
        response.headers["Cache-Control"] = "no-store"
        return response
    response = send_from_directory(ROOT, path)
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving BB Virtual Try-On at http://{host}:{port}")
    print("FASHN proxy enabled at /api/fashn/*")
    app.run(host=host, port=port, threaded=True)
