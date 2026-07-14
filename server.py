#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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


def json_bytes(payload):
    return json.dumps(payload).encode("utf-8")


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path == "/api/fashn/run":
            self.handle_fashn_run()
            return
        self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path.startswith("/api/fashn/status/"):
            self.handle_fashn_status()
            return
        super().do_GET()

    def handle_fashn_run(self):
        body = self.read_json_body()
        if body is None:
            return
        self.proxy_to_fashn("/run", method="POST", payload=body)

    def handle_fashn_status(self):
        prefix = "/api/fashn/status/"
        prediction_id = self.path[len(prefix):].strip()
        if not prediction_id:
            self.send_json(400, {"message": "Missing prediction id."})
            return
        self.proxy_to_fashn(f"/status/{prediction_id}", method="GET")

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"message": "Invalid content length."})
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(400, {"message": "Invalid JSON body."})
            return None

    def proxy_to_fashn(self, endpoint, method="GET", payload=None):
        api_key = os.environ.get("FASHN_API_KEY", "").strip()
        if not api_key:
            self.send_json(500, {
                "message": "Server is missing FASHN_API_KEY. Add it to .env or your environment and restart server."
            })
            return

        data = None
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "BB-Virtual-TryOn-Proxy/1.0",
        }
        if payload is not None:
            data = json_bytes(payload)
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{FASHN_API_BASE}{endpoint}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "application/json; charset=UTF-8")
                extra_headers = {}
                credits_used = response.headers.get("x-fashn-credits-used")
                if credits_used:
                    extra_headers["x-fashn-credits-used"] = credits_used
                self.send_bytes(response.status, body, content_type, extra_headers)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json; charset=UTF-8")
            self.send_bytes(exc.code, body, content_type)
        except Exception as exc:
            self.send_json(502, {"message": f"Proxy request failed: {exc}"})

    def send_json(self, status, payload):
        self.send_bytes(status, json_bytes(payload), "application/json; charset=UTF-8")

    def send_bytes(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def main():
    load_local_env()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    handler = partial(AppHandler, directory=str(ROOT))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving BB Virtual Try-On at http://{host}:{port}")
    print("FASHN proxy enabled at /api/fashn/*")
    server.serve_forever()


if __name__ == "__main__":
    main()
