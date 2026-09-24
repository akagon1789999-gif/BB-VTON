# Studio

A length of cloth, a photo of someone already wearing the piece, and one call
to FASHN `tryon-max`. The cut, drape, embroidery placement, identity and pose
survive; only the cloth changes.

This is the flow behind the **Fabric Studio** nav item, and only that one.
**Virtual Try-On** is a separate two-step flow — your photo, then your look,
with the garment picked from the shop catalogue — which posts straight to
`/api/fashn/run`. Two entry points, two different jobs: try-on starts from the
catalogue, the studio starts from a length of cloth.

`fabric_studio/` also still owns the fabric and outfit catalogues, the admin
tools and the importer — the studio borrows its fabric catalogue through a
picker rather than duplicating it, and both flows feed **My Designs**.

```
  fabric (upload, or the shop's catalogue) ─┐
                                            ├─→ /api/studio/generate ─→ tryon-max ─→ result
  photo of someone wearing the piece ───────┘         │
                                                      └── prompt composed from
                                                          garment type × template × coverage
```

---

## Why the prompt is load-bearing

`tryon-max` expects a *garment* as `product_image`. We hand it a rectangle of
cloth instead, so the instruction is what stops the model treating that
rectangle as a finished garment. It is composed server-side in
[`studio/prompts.py`](studio/prompts.py) from three axes:

| Axis | Options | What it changes |
|---|---|---|
| **Garment type** | agbada · kaftan · senator · suit · dress · shirt · two-piece · custom | For the three composed templates, the vocabulary: an agbada prompt names the outer robe, inner buba, sokoto and fila cap; a dress prompt names the headwrap, sash and overlay and never mentions a trouser cut. For **Universal** it selects the brief — a type listed in `GARMENT_BRIEFS` gets its own text, everything else gets the general one. |
| **Template** | Universal *(default)* · Structural · Designer · Concise | Universal is the shop's own brief: it asks the model to identify every visible garment component itself, so it reads the same for an agbada and a mermaid gown, and it leans hard on not substituting the fabric and not changing the person or the backdrop. Structural is a directive that pins silhouette, construction, identity, pose and camera. Designer is a shorter brief aimed at colour harmony. Concise is a one-sentence floor for A/B work. |
| **Coverage** | Full set *(default)* · Outer only | Full set remakes cap, outer garment, inner top and trousers in the cloth and recolours the embroidery to match. Outer only changes the main garment and leaves everything else in its reference colour. |

### Garment-specific briefs

`GARMENT_BRIEFS` in [`studio/prompts.py`](studio/prompts.py) maps a garment
type to a brief written for how *that* garment fails. One entry so far:

* **dress** — a dress fails in two opposite directions, and the brief is aimed
  at both. Left alone, the model reads bodice and skirt as separate garments
  and re-textures only one. Told to cover everything, it overcorrects and
  flattens a solid-plus-lace-plus-print dress into a single uniform print.
  Sections 2, 3 and 5 carry a *material-zone hierarchy* — identify the zones,
  keep lace as lace and sheer as sheer, recolour solid sections from the
  fabric's palette rather than printing over them — and section 1 locks the
  construction. It closes with a fourteen-point self-check.

Adding another garment is one dictionary entry, not a branch. Types without an
entry fall through to the general universal text, and the rail says which is
in play.

Not every template reads every axis. The Designer brief is inherently full-set,
and the Universal brief is both full-set and garment-agnostic — each template
declares its own `scopeApplies` / `garmentApplies` in `/api/studio/config`, and
the rail hides or greys the control it does not feed, with a line saying why.
That way the two rules live in one place rather than being re-derived in the
browser.

The composed text is shown in **Advanced → Instruction**, and editing it hands
ownership to the customer — the template and garment type stop rewriting it
until they press *Reset to template*.

---

## The API

Every call to FASHN goes out from the server. The key is never sent to the
browser.

| Endpoint | Purpose |
|---|---|
| `GET /api/studio/config` | Control vocabulary, credit matrix, latency table, input limits. The rail renders from this. |
| `GET /api/studio/prompt` | The composed instruction for a `garment` × `template` × `scope`. One source of truth, so the browser never re-implements the templates. |
| `POST /api/studio/upload` | multipart: `file`, `slot=product\|model`, `privacy`, `lossless`, `crop`. Returns something FASHN can read. |
| `POST /api/studio/generate` | Submits the job. Returns a prediction id, the credit cost and which strategy ran. |
| `GET /api/studio/status/<id>` | One poll, normalised. |
| `GET /api/studio/credits` | Live balance for the header chip. |
| `GET /api/studio/files/<key>` | Serves stored bytes back. |

### Uploads

`studio/images.py` runs every upload through the same pipeline: EXIF
auto-rotate and strip, apply the crop rect, downscale anything over 2000 px on
the long edge, then JPEG q95 4:4:4 — or PNG when the caller asked for lossless.
The FASHN limits (30 MB, 15 × 15 px minimum, 1:16 to 16:1) are enforced in the
browser first so a 41 MB file never reaches the wire, and again here.

The crop is **non-destructive**: the original `File` stays in memory for the
session and every rect change re-uploads from it, so a crop that was tightened
can be widened again.

### Hosted URLs vs data URIs

Hosted `https` URLs are preferred — base64 inflates the request and slows the
round trip. The payload inlines a data URI only when:

1. **Privacy mode is on**, or
2. **`APP_URL` is not a public https origin**, which is the case on localhost.

Set `APP_URL` in production to get hosted URLs.

### Cost

| mode \ resolution | 1k | 2k | 4k |
|---|---|---|---|
| balanced | 2 | 3 | 4 |
| quality | 3 | 4 | 5 |

Multiplied by the image count (1–4). The three presets are Draft (balanced/1k),
Standard (balanced/2k) and Final (quality/4k); Advanced can land between them,
and the rail then reads *custom*. Post-processing always runs a single image
and is charged that way.

**There is no `fast` mode on `tryon-max`** — the endpoint takes `balanced` and
`quality` only. Sending `fast` does not make a job cheaper; it leaves the mode
undefined, the API auto-selects, and the run bills as `balanced` while a naive
UI quotes the lower number. `fast` is therefore not offered, and
`normalize_mode` folds it into `balanced` if it ever arrives.

`generation_mode` is always sent explicitly — **omitting it also bills as
`balanced`**, so leaving it out is the other way to pay more than was quoted.

The table above is only ever an *estimate* shown before the run. The real
figure comes back from FASHN in the `x-fashn-credits-used` header and rides
along on the status payload as `creditsUsed`.

---

## How much of the outfit changes

`tryon-max` is a *try-on* model: it resolves one garment region and replaces
it. Given a flat swatch it has no silhouette to classify, so on a two-piece
reference it reliably picks the top and leaves the skirt in the colour it had
in the photo. No amount of prompt tightening fixes that, and `tryon-max` has
no `category` parameter to override the choice — only the legacy `tryon-v1.6`
does.

So the engine is a per-run choice, in the rail under **Fabric application**:

| Choice | Model | What it does |
|---|---|---|
| **One garment** *(default)* | `tryon-max` | Replaces a single garment region. Best realism, and the right pick for an agbada, a kaftan or a one-piece gown. |
| **Whole outfit** | `edit` | Rewrites the whole picture from the instruction, so every layer can take the fabric. The answer for a two-piece whose skirt or trousers must change too. Slightly less faithful to the original photograph. |

`FABRIC_STRATEGY` still sets the default; the control overrides it per run.

On the `edit` path the fabric goes in as **`image_context`** with the person
as `image`. FASHN has no `reference_image` parameter — sending one is silently
ignored, which runs the edit with no fabric at all.

---

## Polling

2 seconds flat, then exponential once the job passes 30 seconds, capped at 10.
A dropped connection mid-poll pauses and resumes rather than failing a job that
is probably still running. At 120 seconds polling stops and the prediction id
is handed back to the UI for *Check again*, so a slow job never costs a second
generation.

An in-flight prediction id is persisted, so a refresh resumes the job instead
of orphaning it.

---

## History

Every generation lands in the drawer with both inputs, the exact parameters and
the result. Clicking one restores all of it — instruction, seed, quality, mode,
coverage, both uploads and the output. Completed entries also populate the
**My Designs** gallery.

It is held in `localStorage` (40 entries). Data URIs over 128 KB are dropped
before writing, so privacy-mode results leave a record without blowing the
quota.

---

## Post-processing

Once there is a result, the action bar runs further FASHN models on it:

| Action | Model |
|---|---|
| Upscale | `reframe` |
| Animate | `image-to-video` |
| Swap face | `model-swap` |
| Change background | `background-change` |
| Remove background | `background-remove` |

---

## Configuration

| Variable | Required | Notes |
|---|---|---|
| `FASHN_API_KEY` | yes | From fashn.ai → settings. Server-side only. |
| `FASHN_API_BASE` | no | Defaults to `https://api.fashn.ai/v1`. |
| `APP_URL` | no | Public origin. Decides hosted URLs vs data URIs. |
| `FABRIC_STRATEGY` | no | `tryon-max` (default) or `edit`. |
| `DATA_DIR` | no | Uploads land in `DATA_DIR/studio-uploads`. Point it at a mounted volume in production. |

## Tests

```bash
python3 -m unittest discover -t . -s tests
```

`tests/test_studio.py` covers prompt composition, the credit matrix, the image
pipeline, storage, parameter clamping, FASHN error mapping and the full HTTP
contract. Nothing in it reaches FASHN: `run`, `status` and `credits` are
stubbed, so the tests assert the payload that *would* be sent — the part that
costs money to get wrong.

To exercise the failure UI without spending credits, run the `studio-offline`
launch target: it points `FASHN_API_BASE` at a dead port, so a generation fails
into the error panel.
