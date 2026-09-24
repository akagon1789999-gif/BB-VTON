# Selvedge

A self-hosted fabric and garment try-on studio built on FASHN `tryon-max`.

Upload a bolt of cloth and a photo of someone already wearing the piece you
want remade, and get back a photoreal image of that person in the same outfit
cut from your fabric. The cut, drape, embroidery placement, identity and pose
survive; only the cloth changes.

A garment-type selector (agbada, kaftan, senator, suit, dress, shirt,
two-piece, custom) drives a prompt template that names the actual layers of
that piece, so the instruction is never generic — and never talks about a
trouser cut on a dress.

Everything that touches the FASHN key runs in Next.js route handlers. The key
is never sent to the browser.

---

## Setup

```bash
pnpm install
cp .env.example .env.local   # then paste your FASHN key
pnpm dev
```

Open <http://localhost:3000>. The history drawer ships with three worked
examples, so the app is demoable before the first API call.

### Environment

| Variable | Required | Notes |
| --- | --- | --- |
| `FASHN_API_KEY` | yes | From fashn.ai → settings. Server-side only. |
| `FASHN_API_BASE` | no | Defaults to `https://api.fashn.ai/v1`. |
| `STORAGE_DRIVER` | no | `local` (default) or `s3`. |
| `APP_URL` | no | Public origin. See "Hosted URLs vs data URIs" below. |
| `FABRIC_STRATEGY` | no | `tryon-max` (default) or `edit`. |
| `S3_*` | when `STORAGE_DRIVER=s3` | Bucket, region, credentials, public base URL. |

### Storage

`StorageAdapter` has two implementations:

- **`local`** writes to `./.data/uploads` and serves the bytes back through
  `/api/files/*`. This works identically under `next dev` and `next start`,
  unlike dropping files into `/public` after a build.
- **`s3`** targets any S3-compatible bucket — AWS, Cloudflare R2, Backblaze B2
  or MinIO. Set `S3_ENDPOINT` for non-AWS providers and
  `S3_FORCE_PATH_STYLE=true` for MinIO.

### Hosted URLs vs data URIs

Hosted `https` URLs are preferred in the FASHN payload: base64 inflates the
request and slows the round trip. The app inlines a data URI only when:

1. **Privacy mode is on**, or
2. **The storage driver is not reachable from the public internet.**

The second case is the normal one in local development — FASHN cannot fetch
`http://localhost:3000/api/files/...`, so the app detects it and inlines
automatically. Point `APP_URL` at a tunnel (`cloudflared`, `ngrok`) or use the
S3 driver to exercise the hosted-URL path.

One deployment caveat: `POST /api/upload` streams the file through the Node
runtime, and some serverless platforms cap request bodies well below FASHN's
30 MB limit (Vercel's is 4.5 MB). Self-host, raise the platform limit, or move
to presigned direct-to-bucket uploads if you deploy there.

---

## Credit cost

Cost is `matrix[generation_mode][resolution] × num_images`.

| mode \ resolution | 1k | 2k | 4k |
| --- | --- | --- | --- |
| `fast` | 1 | 2 | 3 |
| `balanced` | 2 | 3 | 4 |
| `quality` | 3 | 4 | 5 |

The quality control maps to three rungs, and Advanced can set the two axes
independently (the control then reads "custom"):

| Preset | Mode + resolution | Cost | Typical latency |
| --- | --- | --- | --- |
| Draft | `fast` + `1k` | 1 | ~10s |
| Standard | `balanced` + `2k` | 3 | ~25s |
| Final | `quality` + `4k` | 5 | ~55s |

`generation_mode` is always sent explicitly. Omitting it bills as `balanced`,
which makes cost unpredictable.

The live balance is fetched from `/v1/credits` and shown in the header. Before
submitting, the server compares balance against cost and, if you are short,
returns the balance, the cost and the shortfall rather than a bare failure.

---

## Fabric mode, and tuning its prompt

The swatch goes in as `product_image`, the person as `model_image`, and the
prompt is composed from the garment-type selector. Three templates ship, chosen
under **Advanced → Template**:

**Structural** (default, ~3,900 characters). Treats the model photo as a
template rather than inspiration. It splits its preservation list in two — a
PRESERVE THE SHAPE list (silhouette, seams, embroidery *placement*, cap *fold*,
identity, pose, camera) and a COORDINATED SET list naming every layer whose
material changes — then adds fabric fidelity, pattern preservation,
construction, photorealism, an explicit conflict-priority order, and a DO NOT
list that closes with the failure condition stated plainly: *a single layer
left in the old colour is a failed result.*

**Designer** (~2,100 characters). A shorter brief written as a designer
instruction rather than a constraint list, aimed squarely at colour harmony.
Worth trying when the structural directive starts diluting — which shows up as
pattern drift or a flattened silhouette.

**Concise** (one sentence). An A/B floor.

Every template interpolates from a per-garment vocabulary, so it reads
correctly whatever is selected:

| Garment | Layers named | Headwear | Construction detail |
| --- | --- | --- | --- |
| Agbada | outer agbada, inner buba, sokoto trousers, fila cap | the fila cap | side openings, trouser cut, cap shape |
| Suit | jacket, trousers, waistcoat | any hat | lapel width, button stance, vents |
| Dress | dress, headwrap, sash, belt, overlay | any headwrap | waist seam, skirt fullness, hem |
| Custom | every layer, inner, lower, head covering | any head covering | necklines, hems, fastenings, seams |

Edit the prompt and the app stops rewriting it; "Reset to template" hands
control back. The template and coverage are stored on every history entry and
shown on its card, so two runs of the same inputs stay distinguishable.

### Coverage: how many layers change

A separate axis, under **Advanced → Coverage**, shown only for the Structural
and Concise templates — the Coordinated brief already remakes every layer, so
there is nothing to choose. It exists
because "preserve the garment" and "preserve its colour" are different
instructions, and collapsing them is what leaves a purple cap sitting on top of
a newly patterned agbada.

**Full set** (default). Cap, outer garment, inner top and trousers are all cut
from the uploaded cloth; the cap takes the same print at a scale suited to its
size, and the inner layers take either the same print or a solid tone from the
fabric's dominant palette. Embroidery keeps its exact position and stitch
structure but is recoloured to a tone from that same palette. Footwear,
eyewear, watches and jewellery are explicitly left alone. The prompt closes by
naming the failure: a single layer left in the old colour is a failed result.

**Outer only.** The previous behaviour. The outer garment changes; the cap,
inner top, trousers and embroidery colour stay exactly as they are in the model
photo.

Under the hood the strict template splits its preservation list in two — a
PRESERVE THE SHAPE list (silhouette, seams, embroidery *placement*, cap *fold*,
identity, pose, camera) and a COORDINATED SET list that names each layer whose
material changes. Layer names are garment-specific: agbada expands to "the
outer agbada, the inner buba, the sokoto trousers and the fila cap".

`{garment}` expands per type in both — `agbada` becomes "agbada and trousers",
`senator` becomes "senator top and trousers", and so on. Edit the prompt and
the app stops rewriting it; "Reset to template" hands control back. The chosen
template is stored on every history entry and shown on its card, so a strict
run and a concise run of the same inputs stay distinguishable.

**Which to use.** Strict is the default because it holds construction and
identity far better on complex pieces — agbada, senator, anything with
embroidery or layering. Concise is worth trying when a long prompt starts
diluting the result, which shows up as pattern drift or a flattened
silhouette. Same seed, same inputs, flip the template: that is the cleanest
A/B this tool offers.

**Tuning notes, in rough order of impact:**

1. **Name the pattern behaviour, not just the fabric.** "Run the stripe
   vertically down the body and align it across the seams" beats "use this
   fabric" for aso-oke and other directional weaves.
2. **Say what must not change.** The strict template does this wholesale; when
   writing your own, adding "keep the embroidery placement and the neckline"
   measurably reduces drift.
3. **Shoot the swatch flat and square-on**, filling the frame. A swatch
   photographed at an angle bakes perspective into the print scale.
4. **Pin the seed** once a look is close, then change one clause at a time.
   Same seed plus same inputs is reproducible.
5. **Push resolution before pushing mode.** Print detail responds more to `2k`
   and `4k` than to `quality` at `1k`.

### If retexture fidelity is poor

Fabric mode is the harder case. The strategy is configurable rather than
hardcoded:

```bash
FABRIC_STRATEGY=edit
```

- `tryon-max` (default) — swatch as `product_image`, retexture prompt attached.
- `edit` — the reference photo becomes the base `image`, the swatch becomes
  `reference_image`, and the prompt carries an explicit retexture instruction
  that pins the person, pose, lighting, background and silhouette.

The response echoes which strategy ran, so history entries stay honest.

---

## API surface

| Route | Purpose |
| --- | --- |
| `POST /api/upload` | Multipart in, preprocessed image and a public URL out. |
| `POST /api/generate` | Validates, resolves images, calls `/v1/run`. Returns `{ predictionId, creditCost }`. |
| `GET /api/status/:id` | Proxies `/v1/status/:id`, normalises the error shape. |
| `GET /api/credits` | Live balance. |
| `GET /api/files/*` | Serves objects from the configured storage driver. |

### Image preprocessing

Every upload passes through Sharp before it leaves the server:

1. Auto-rotate from EXIF, then strip metadata.
2. Apply the crop rect, if one was set.
3. Downscale anything over 2000 px on the long edge, preserving aspect.
4. Encode JPEG q95 — or PNG when privacy mode or PNG output is requested.
5. Reject anything over 30 MB, under 15 × 15 px, or past 16:1.

Model images generate best near 2:3. The app says so and offers a crop rather
than cropping silently, and the crop is non-destructive: the original file
stays in the session, so you can widen a crop you already tightened.

### Polling

2s interval, exponential backoff after 30s (capped at 10s), hard timeout at
120s. Polling cancels on unmount. In-flight prediction ids are persisted, so a
refresh resumes the job instead of orphaning it, and a timeout keeps the id and
offers **Check again** rather than forcing a paid re-run.

---

## Design

The palette is an indigo dye house: vat-indigo ground, warp-and-weft greys, raw
calico type, and one loud thread — the vermilion **selvedge line** woven into
the edge of a shuttle-loom bolt. That red marks the active mode, the focused
control and the primary action, and appears nowhere else. Type is Archivo for
display, Inter for body, IBM Plex Mono for every parameter and credit readout.

Reduced motion is respected, focus is always visible, and every control is
reachable by keyboard — including the crop rect, which nudges with the arrow
keys and resizes with shift+arrows.

---

## Scripts

```bash
pnpm dev        # development server
pnpm build      # production build
pnpm start      # serve the build
pnpm lint       # eslint
pnpm typecheck  # tsc --noEmit
```
