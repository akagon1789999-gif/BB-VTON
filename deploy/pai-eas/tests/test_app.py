import base64, io, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.dirname(HERE))  # app.py lives one level up
def _fake_weights():
    """A throwaway weights dir so the startup guard passes."""
    import tempfile
    d = tempfile.mkdtemp(prefix="vton-weights-")
    os.makedirs(os.path.join(d, "dwpose"), exist_ok=True)
    for f in ("model.safetensors", "dwpose/yolox_l.onnx", "dwpose/dw-ll_ucoco_384.onnx"):
        open(os.path.join(d, f), "wb").write(b"\0" * 16)
    return d


os.environ.update(
    WEIGHTS_DIR=os.environ.get("TEST_WEIGHTS_DIR") or _fake_weights(),
    DEVICE="cpu", WARMUP="false", MAX_SAMPLES="4", MAX_TIMESTEPS="50",
)

from fastapi.testclient import TestClient
from PIL import Image
import app as A
import fashn_vton

def png(size=(64, 96)):
    b = io.BytesIO(); Image.new("RGB", size, (200, 40, 40)).save(b, "PNG"); return b.getvalue()

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {name}")
    else: fail += 1; print(f"  FAIL  {name}  {detail}")

with TestClient(A.app) as c:
    print("\n-- health --")
    r = c.get("/health")
    check("health 200", r.status_code == 200, r.text)
    check("health reports ok", r.json().get("status") == "ok", r.text)
    check("pipeline loaded from WEIGHTS_DIR",
          A.STATE.pipeline is not None and "vton-weights-" in A.STATE.pipeline.weights_dir)

    print("\n-- multipart --")
    r = c.post("/v1/tryon",
               files={"person_image": ("p.png", png(), "image/png"),
                      "garment_image": ("g.png", png(), "image/png")},
               data={"category": "bottoms", "num_samples": "2", "num_timesteps": "20"})
    check("multipart 200", r.status_code == 200, r.text[:300])
    if r.status_code == 200:
        body = r.json()
        check("returns 2 images", len(body.get("images", [])) == 2, str(len(body.get('images', []))))
        check("images are png data URIs",
              all(i.startswith("data:image/png;base64,") for i in body["images"]))
        last = fashn_vton.CALLS[-1]
        check("category forwarded", last["category"] == "bottoms", last["category"])
        check("timesteps forwarded", last["num_timesteps"] == 20, last["num_timesteps"])
        check("no stray image kwargs",
              set(last) == {"person_image","garment_image","category","garment_photo_type",
                            "num_samples","num_timesteps","guidance_scale","seed",
                            "segmentation_free"}, sorted(last))
        check("person_image is a PIL RGB image",
              isinstance(last["person_image"], Image.Image) and last["person_image"].mode == "RGB")

    print("\n-- json, base64 input --")
    r = c.post("/v1/tryon", json={"person_image": base64.b64encode(png()).decode(),
                                  "garment_image": f"data:image/png;base64,{base64.b64encode(png()).decode()}",
                                  "category": "one-pieces"})
    check("json 200", r.status_code == 200, r.text[:300])
    check("json category forwarded",
          r.status_code == 200 and fashn_vton.CALLS[-1]["category"] == "one-pieces")

    print("\n-- binary response --")
    r = c.post("/v1/tryon", json={"person_image": base64.b64encode(png()).decode(),
                                  "garment_image": base64.b64encode(png()).decode(),
                                  "response_format": "binary"})
    check("binary content-type", r.headers.get("content-type") == "image/png", r.headers)
    check("binary body is a PNG", r.content[:8] == b"\x89PNG\r\n\x1a\n")

    print("\n-- validation and limits --")
    r = c.post("/v1/tryon", json={"person_image": "x", "garment_image": "y", "num_samples": 99})
    check("num_samples ceiling enforced", r.status_code == 422, r.status_code)
    r = c.post("/v1/tryon", json={"person_image": "x", "garment_image": "y", "num_timesteps": 999})
    check("num_timesteps ceiling enforced", r.status_code == 422, r.status_code)
    r = c.post("/v1/tryon", json={"person_image": "x", "garment_image": "y", "category": "hats"})
    check("bad category rejected", r.status_code == 422, r.status_code)
    r = c.post("/v1/tryon", json={"person_image": "x", "garment_image": "y", "nope": 1})
    check("unknown field rejected", r.status_code == 422, r.status_code)
    r = c.post("/v1/tryon", content=b"raw", headers={"Content-Type": "text/plain"})
    check("wrong content-type -> 415", r.status_code == 415, r.status_code)
    r = c.post("/v1/tryon", json={"person_image": "!!!not base64!!!", "garment_image": "x"})
    check("undecodable input -> 400", r.status_code == 400, r.status_code)
    r = c.post("/v1/tryon", files={"person_image": ("p.png", png(), "image/png")})
    check("missing garment file -> 400", r.status_code == 400, r.status_code)
    r = c.post("/v1/tryon", files={"person_image": ("p.txt", b"not an image", "image/png"),
                                   "garment_image": ("g.png", png(), "image/png")})
    check("non-image upload -> 400", r.status_code == 400, r.status_code)

    print("\n-- SSRF guard --")
    for url, label in [("http://169.254.169.254/latest/meta-data/", "cloud metadata"),
                       ("http://127.0.0.1:8000/health", "loopback"),
                       ("http://localhost/x.png", "localhost"),
                       ("http://10.0.0.5/x.png", "private 10/8"),
                       ("http://192.168.1.1/x.png", "private 192.168/16"),
                       ("http://[::1]/x.png", "ipv6 loopback"),
                       ("file:///etc/passwd", "file scheme"),
                       ("gopher://x/", "gopher scheme")]:
        r = c.post("/v1/tryon", json={"person_image": url, "garment_image": base64.b64encode(png()).decode()})
        check(f"blocked {label}", r.status_code == 400, f"{r.status_code} {r.text[:120]}")

    print("\n-- error shape --")
    r = c.post("/v1/tryon", json={"person_image": "http://127.0.0.1/x", "garment_image": "x"})
    check("errors carry error+status", set(r.json()) == {"error", "status"}, r.text[:200])

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
