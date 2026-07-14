#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, Response, request, send_from_directory


ROOT = Path(__file__).resolve().parent
FASHN_API_BASE = "https://api.fashn.ai/v1"


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


@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def static_files(path):
    response = send_from_directory(ROOT, path)
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving BB Virtual Try-On at http://{host}:{port}")
    print("FASHN proxy enabled at /api/fashn/*")
    app.run(host=host, port=port, threaded=True)
