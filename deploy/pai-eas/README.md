# FASHN VTON v1.5 on PAI-EAS (serverless, scale-to-zero)

Self-hosted [FASHN VTON v1.5](https://github.com/fashn-AI/fashn-vton-1.5)
(Apache-2.0) as an EAS custom-container service that costs nothing while idle.

```
app.py                      FastAPI service: /health + /v1/tryon
Dockerfile                  CUDA 12.1 + cuDNN 8, two-stage, non-root
eas_config.template.json    EAS service definition (rendered by deploy.sh)
deploy.sh                   weights -> OSS, image -> ACR, service -> live
.env.deploy.example         credentials and overrides
tests/                      GPU-free checks for the serving layer
```

## Quick start

```bash
cp .env.deploy.example .env.deploy   # fill it in
set -a; . ./.env.deploy; set +a
./deploy.sh --dry-run                # inspect the plan and rendered config
./deploy.sh
```

## Where the weights live, and why it is split

The model needs three sets of weights. They are **not** all handled the same way:

| Weights | Size | Where | Why |
|---|---|---|---|
| `model.safetensors` (VTON) | ~1.7 GB | OSS, mounted read-only at `/mnt/models` | Too large to want inside every image pull |
| `dwpose/*.onnx` (pose) | ~350 MB | OSS, same mount | Same |
| human parser | ~244 MB | **baked into the image** | It downloads itself from the HF Hub on first use |

That last row is the one that matters for scale-to-zero. `FashnHumanParser`
fetches its weights from Hugging Face the first time it runs and caches them
under `HF_HOME`. On a service that drops to zero replicas, "the first time it
runs" happens on **every cold start** — so an un-baked parser would add a Hub
round-trip to each one and make a huggingface.co outage an outage of your own
service. The Dockerfile pre-fetches it at build time and sets `HF_HUB_OFFLINE=1`,
so a cold replica does no network I/O beyond the image pull and the OSS read.

## Cold starts are the whole design problem

`autoscaler.min = 0` is what makes this free at idle, and it is also the thing
that will bite you. A cold request pays for: image pull, ~2 GB read off OSS,
pipeline construction, then CUDA warmup. **Budget 2–4 minutes.**

What the config does about it:

- `behavior.onZero.interceptTraffic: true` — EAS holds the request while a
  replica starts instead of failing it. Your client still needs a timeout
  longer than the cold start, or it gives up before the reply arrives.
- `scaleDownGracePeriodSeconds: 900` — 15 minutes of idle before dropping to
  zero, so bursty traffic is not paying cold starts back to back.
- `WARMUP=true` — a synthetic 4-step pass during startup, so the first real
  caller does not absorb kernel autotuning.
- Weights load in the FastAPI lifespan handler, which Uvicorn completes
  **before** binding the port. A still-loading replica is unreachable rather
  than reachable-and-broken, which is what makes the EAS port probe trustworthy.

If a 3-minute worst case is unacceptable, set `min: 1`. That is the honest
trade: scale-to-zero and instant first response are mutually exclusive here.

## The API

`/health` → `200` with queue depth, VRAM and uptime once loaded.

`/v1/tryon` accepts **either** content type:

```bash
# JSON: URLs, data URIs, or bare base64
curl -X POST "https://$EAS_HOST/api/predict/$SERVICE_NAME/v1/tryon" \
  -H "Authorization: $EAS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"person_image":"https://cdn.example.com/model.jpg",
       "garment_image":"https://cdn.example.com/shirt.jpg",
       "category":"tops","num_timesteps":30}'

# multipart upload, PNG straight back
curl -X POST "https://$EAS_HOST/api/predict/$SERVICE_NAME/v1/tryon" \
  -H "Authorization: $EAS_TOKEN" \
  -F person_image=@model.jpg -F garment_image=@shirt.jpg \
  -F category=tops -F response_format=binary -o result.png
```

| Field | Default | Notes |
|---|---|---|
| `category` | `tops` | `tops` · `bottoms` · `one-pieces` |
| `garment_photo_type` | `model` | `model` · `flat-lay` |
| `num_samples` | 1 | capped by `MAX_SAMPLES` |
| `num_timesteps` | 30 | 20 fast · 30 balanced · 50 quality, capped by `MAX_TIMESTEPS` |
| `guidance_scale` | 1.5 | |
| `seed` | 42 | |
| `segmentation_free` | `true` | maskless mode |
| `response_format` | `base64` | `binary` returns the first image as PNG |

## Security posture

- **SSRF.** URL inputs are an SSRF primitive: an EAS replica sits in a VPC next
  to the metadata service. Every URL is scheme-checked, its host resolved, and
  every resolved address must be globally routable — re-validated on each
  redirect hop. Set `URL_ALLOWLIST` in production to narrow it further.
- **Decompression bombs.** Dimensions are probed before full decode; 24 MP and
  20 MB ceilings, both configurable.
- **Load shedding.** One inference at a time on one GPU. Past `MAX_QUEUE` the
  service returns 503 rather than accumulating a backlog no one is waiting for.
- **Container.** Non-root (uid 10001), read-only code and weights, no build
  tools in the runtime stage.
- **Credentials.** Read from env, never arguments, never echoed, never in the
  image. `ossutil` gets a 600-perm config file removed on exit — argv is world
  readable via `ps`.

## Things to check against your account

Three values are environment-specific and worth confirming before the first run:

1. **`INSTANCE_TYPE`** — `ecs.gn7i-c8g1.2xlarge` (A10, 24 GB) suits the ≥8 GB
   Ampere+ recommendation, but GPU availability varies by region and quota.
   `eascmd instances` lists what your account can actually launch.
2. **`storage[].oss.readOnly`** — if your eascmd build rejects the field, drop
   it; nothing here writes to the mount.
3. **Dedicated gateway** — EAS does **not** allow `min: 0` behind one. Default
   gateway only, or scale-to-zero silently is not what you deployed.

## Cost shape

You pay for GPU-seconds while replicas exist, plus OSS storage (~2 GB) and ACR.
At zero traffic with `min: 0` the compute bill is zero. The lever that matters
is `scaleDownGracePeriodSeconds`: shorter is cheaper and colder.
