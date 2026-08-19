# Fabric Studio

Person **+** fabric **+** predefined outfit → the person wearing that outfit made from
that fabric. It runs alongside the existing Virtual Try-On (person + garment) and reuses
the same server, admin login, storage convention, design system and FASHN account.

```
USER ──┬── person photo ────────────────┐
       ├── fabric  (catalogue) ──┐      │
       └── outfit  (catalogue) ──┤      │
                                 ▼      ▼
                     ┌────────────────────────────┐
                     │ FABRIC PROCESSOR           │  colours · pattern · texture
                     │ (cached per fabric)        │  normalised image + seamless tile
                     └─────────────┬──────────────┘
                                   ▼
                     ┌────────────────────────────┐
                     │ GARMENT COMPOSER           │  outfit silhouette + shading
                     │ (cached per fabric+outfit) │  fabric poured into the shape
                     └─────────────┬──────────────┘
                                   ▼
                     ┌────────────────────────────┐
                     │ VirtualTryOnProvider       │  fashn_api │ fashn_vton_15 │ mock
                     └─────────────┬──────────────┘
                                   ▼
                        result stored + history record
```

**How the garment reaches the model** is a strategy, set by
`VTON_GARMENT_STRATEGY`:

    person + garment template + fabric swatch  ->  tryon-max

| Strategy | What is sent as the product image | Model | Notes |
|---|---|---|---|
| `composite` *(default)* | the outfit template filled with the chosen fabric — one flat-lay carrying both the cut and the cloth | `tryon-max` | The intended workflow. ~2 credits (balanced/1k), ~3 (quality). |
| `fabric` | the bare fabric swatch; the garment exists only in the prompt | `tryon-max` | FASHN's suggestion when you have no garment reference at all. |
| `template` | the composite, on the cheap legacy model | `tryon-v1.6` | Takes a `category` and a flat-lay hint instead of a prompt. Cheapest. |
| `edit` | the person as `image`, the fabric as `image_context` | `edit` | The other approach FASHN suggested. |

**Where the composite comes from.** Preferably a photograph of the real garment,
uploaded per outfit (`reference` on the admin outfit form): the customer's
fabric is painted onto it while its own luminance — folds, seams, contact
shadows — is preserved, so the result reads as cloth rather than as a flat
shape. Failing that, the vector template is filled instead.

A reference photograph is only used when `refabric.usability()` passes, and the
bar is deliberately high, because the failure mode is ugly:

* **no model in frame** — masking a garment off a body is human parsing, which
  this app does not do. A photo with a face in it is refused outright;
* **the garment must contrast with its background** — a white shirt on a cream
  backdrop masks as *background*, and the fabric lands on the room;
* **the garment must be plain** — luminance cannot separate someone else's
  print from the folds, so a patterned reference ghosts its old motif through
  the new cloth.

Anything rejected falls back to the vector template, and the admin is told why.
For on-model or patterned references, the AI route (`edit` with the fabric as
`image_context`) is the answer, and is not wired into composition yet.

The prompt is load-bearing in `fabric` and `edit` mode — it is what stops the model
treating a rectangle of cloth as a finished garment — so it is built from structured
catalogue data in `prompts.py` rather than assembled at the call site.

---

## 1. Files created

**Backend package** (`fabric_studio/`)

| File | Purpose |
|---|---|
| `__init__.py` | `register(app, admin_required)` + non-blocking startup tasks |
| `config.py` | All env-driven configuration (provider, models, limits, importer) |
| `storage.py` | `JsonStore` (atomic writes, locking, indexes) + media tree helpers |
| `imaging.py` | Pillow helpers: decode/encode, data URLs, resize, crop, quality scores |
| `errors.py` | Error types + safe user messages + FASHN runtime-error mapping |
| `color_names.py` | HSV-based colour naming for extracted palettes |
| `fabric_analysis.py` | Colour extraction, pattern/texture/orientation detection |
| `fabric_processor.py` | `FabricProcessor`: validate → crop → normalise → analyse → cache |
| `swatches.py` | Procedural swatch renderer used to seed the catalogue |
| `garment_templates.py` | 11 parametric flat-lay silhouettes (mask + shading + details) |
| `garment_composer.py` | Fabric + template → garment product image (cached) |
| `segmentation.py` | Segmentation provider interface, no-op/remote impls, photo validator |
| `catalog.py` | Fabric/outfit repositories, search, facets, payload validation |
| `seed_data.py` | 22 seed fabrics + 11 seed outfits |
| `migrations.py` | Idempotent seeding/repair, applied-state tracking |
| `generations.py` | Pipeline worker, real stage tracking, history, benchmarking stats |
| `importer.py` | Reviewed web catalogue importer (allow-list, robots.txt, SSRF guards) |
| `routes.py` | Flask blueprint: public + admin endpoints, media serving |
| `virtual_tryon/types.py` | Provider-neutral `TryOnRequest` / `TryOnResult` |
| `virtual_tryon/provider.py` | `VirtualTryOnProvider` interface + factory |
| `virtual_tryon/http.py` | urllib JSON helper with error classification |
| `virtual_tryon/fashn_api_provider.py` | FASHN cloud API provider (current) |
| `virtual_tryon/fashn_vton15_provider.py` | Self-hosted VTON 1.5 provider (migration target) |
| `virtual_tryon/mock_provider.py` | Zero-credit provider for development and tests |

**Tests** (`tests/`): `context.py`, `test_storage.py`, `test_fabric_analysis.py`,
`test_pipeline_units.py`, `test_providers.py`, `test_catalog.py`, `test_api.py`,
`test_importer.py`, `test_migrations.py` — 111 tests.

**Docs**: `FABRIC_STUDIO.md` (this file).

## 2. Files modified

| File | Change |
|---|---|
| `server.py` | Three lines: import `fabric_studio`, `register(app, admin_required=requires_admin)`, `run_startup_tasks()`. No existing route touched. |
| `index.html` | Nav entries (Fabric Studio, My Designs), two new views, Fabric Studio state/handlers/bindings, nav collapse breakpoint raised to 1080px for seven items, **theme token system + cream/dark toggle** (§16). Existing views untouched apart from their colours becoming tokens. |
| `admin.html` | Tab bar + Fabrics / Outfits / Fabric Imports tabs and their JS, plus the same theme tokens and a cream/dark toggle. Existing product admin untouched, now inside the Products tab. |
| `sw.js` | Service worker no longer caches `/api/*` or `/media/generations/*` (cache-first was replaying stale poll responses and could serve one visitor's result to another on a shared device). Cache version bumped to v3. |
| `requirements.txt` | `pillow`, `numpy`. |
| `.env.example` | Fabric Studio variables, documented below. |
| `.gitignore` | Runtime catalogue/media files. |
| `.claude/launch.json` | Added a `fabric-studio` dev configuration (mock provider, port 8011). |

## 3. Database / migrations

The app has no database engine: `server.py` already persists `catalog.json` and
`payments.json` as JSON documents on the `DATA_DIR` volume, so Fabric Studio follows the
same convention through `JsonStore` (process-wide lock, atomic temp-file + rename,
mtime-invalidated cache, secondary indexes). No existing file or table is altered.

New documents under `DATA_DIR`:

| Document | Records | Indexes |
|---|---|---|
| `fabric_catalog.json` | `id, name, slug, category, subcategory, description, image_path, image_url, thumbnail_url, pattern_type, primary_colors, secondary_colors, texture_description, tags, region, source_url, source_name, license, attribution, is_active, review_status, processed{}, created_at, updated_at` | category, pattern_type, slug |
| `outfit_catalog.json` | `id, name, slug, category, description, preview_image_path/url, garment_type, template_id, mask_type, supported_regions, default_prompt, pattern_scale, sort_order, is_active, created_at, updated_at` | category, slug, garment_type |
| `fabric_generations.json` | `id, user_id, fabric_id, outfit_id, mode, prompt, provider, provider_generation_id, result_image_url, status, stage, error, warnings, created_at, updated_at, timings{}, metadata{}` | user_id |
| `fabric_studio_meta.json` | applied migrations + schema version | — |

Migrations run automatically on startup, in a background thread, once per volume:

1. `001_media_tree` — create `media/{fabrics/{original,processed,thumbs,garments},outfits,generations,imports}`
2. `002_seed_outfits` — insert 11 outfits, render their previews
3. `003_seed_fabrics` — render and insert 22 swatches
4. `004_process_fabrics` — warm the processed-asset cache

They are additive and idempotent: a record that already exists is never overwritten or
deleted, so admin edits survive redeploys. `POST /api/admin/fabric-studio/migrate` re-runs
them; `POST /api/admin/fabric-studio/repair` re-renders seed swatches whose files went
missing (e.g. a volume was replaced) and reports uploaded images it cannot regenerate.

## 4. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `FASHN_API_KEY` | — | **Server-side only.** Already used by the existing try-on proxy. |
| `VTON_PROVIDER` | `fashn_api` | `fashn_api` · `mock` · `fashn_vton_15` |
| `VTON_GARMENT_STRATEGY` | `fabric` | `fabric` · `template` · `edit` — how the garment reaches the model |
| `VTON_FABRIC_MODEL` | `tryon-max` | Model for the `fabric` strategy |
| `VTON_FAST_MODEL` | `tryon-v1.6` | Model for the `template` strategy in fast mode |
| `VTON_QUALITY_MODEL` | `tryon-max` | Model for `template` in quality mode |
| `VTON_EDIT_MODEL` | `edit` | Model for the `edit` strategy |
| `VTON_RESOLUTION` | `1k` | `1k` · `2k` · `4k` — higher costs more credits |
| `VTON_TIMEOUT_SECONDS` | `240` | Submit + poll budget per generation |
| `FASHN_VTON15_URL` / `FASHN_VTON15_TOKEN` | — | Self-hosted inference server |
| `SEGMENTATION_PROVIDER` | `noop` | `noop` · `remote` |
| `SEGMENTATION_URL` / `SEGMENTATION_TOKEN` | — | External human-parsing service |
| `DATA_DIR` | repo root | Existing variable; also holds Fabric Studio data |
| `FABRIC_IMPORT_ALLOWED_HOSTS` | empty (importer off) | Comma-separated hosts the importer may fetch |
| `FABRIC_IMPORT_MAX_BYTES` | `8388608` | Import download cap |
| `FABRIC_NORMALIZED_SIZE` / `FABRIC_THUMBNAIL_SIZE` | `1024` / `400` | Processed asset sizes |
| `GARMENT_RENDER_SIZE` | `1024` | Long edge of the composed garment sent for inference |
| `PERSON_IMAGE_MAX_EDGE` / `PERSON_IMAGE_MIN_EDGE` | `1536` / `400` | Upload normalisation and rejection threshold |
| `FABRIC_HISTORY_LIMIT` | `200` | Generations kept before trimming |
| `FABRIC_STUDIO_DEBUG` | `false` | Include technical detail in API errors (dev only) |

The FASHN key is read server-side only (`config.fashn_api_key()`), never returned by any
endpoint, never rendered into HTML, and never sent to the browser.

## 5. FASHN API integration

Implemented against the documented prediction API — one endpoint, poll for the result:

* `POST https://api.fashn.ai/v1/run` with `{ "model_name": …, "inputs": {…} }`
* `GET  https://api.fashn.ai/v1/status/{id}` until `completed` / `failed`
* `Authorization: Bearer $FASHN_API_KEY`; credits read from `x-fashn-credits-used`

| Strategy / mode | Model | Inputs sent |
|---|---|---|
| `fabric`, fast *(default)* | `tryon-max` | `model_image`, `product_image` (the fabric), `prompt`, `generation_mode: balanced`, `resolution`, `output_format` |
| `fabric`, design | `tryon-max` | as above with `generation_mode: quality` and the customer's brief folded into the prompt |
| `template`, fast | `tryon-v1.6` | `model_image`, `garment_image` (composed flat-lay), `category`, `garment_photo_type: "flat-lay"`, `mode`, `output_format` |
| `template`, design | `tryon-max` | `model_image`, `product_image`, `prompt`, `generation_mode`, `resolution` |
| `edit` | `edit` | `image` (person), `image_context` (fabric), `prompt`, `generation_mode`, `resolution` |

Statuses map `starting`/`in_queue` → queued, `processing` → processing, `completed` →
completed, `failed`/`canceled`/`time_out` → failed. Runtime errors (`PoseError`,
`ContentModerationError`, `ImageLoadError`, …) are translated into customer-safe
sentences; the raw payload is logged server-side only.

The existing `/api/fashn/*` proxy used by the original Virtual Try-On is untouched.

## 6. Fabric catalogue

Database-driven, never hard-coded in the frontend. 22 seed fabrics across Ankara, Adire,
Lace, Brocade, Atiku, Senator, Silk, Chiffon, Velvet, Linen, Cotton, Denim, Traditional
(aso-oke), Embroidered and Contemporary. Search covers name, category, description,
colours, tags and region; facets (category / pattern / colour / tag) are computed from
live records, so a newly added fabric appears in the filters with no code change.

**On the seed images:** they are rendered procedurally by `swatches.py`, so every seed
record ships with a licence BB Apparel actually holds — no scraped or unclear-licence
photography. Real fabric photography is added through the admin uploader or the reviewed
importer, which record `source_url`, `source_name`, `license` and `attribution`.

## 7. Outfit catalogue

Outfit cards show a **technical flat sketch** — the line drawing the trade uses
for "which cut is this?" — rendered from the same silhouette the `template`
strategy uses, in a neutral stroke, as a transparent PNG so one file reads on
both the cream and the dark card. They are deliberately *not* the fabric-filled
composite: the catalogue is asking which cut, and answering in a fabric the
customer has not chosen only muddles the question.

An admin-uploaded photograph always outranks the sketch (`preview_custom` on the
record), and preview-refresh migrations skip those records. Real product
photography is the intended end state; the sketch is what ships until then.

11 predefined outfits — Men: Modern Senator, Classic Kaftan, Grand Agbada, Native
Two-Piece, Long Tunic. Women: Ankara Gown, Long Gown, Iro and Buba, Skirt and Blouse,
Peplum Top and Skirt, Bubu Boubou. Each row carries a `template_id` (the silhouette),
`garment_type` (`tops`/`bottoms`/`one-pieces`, passed straight to the try-on model),
`mask_type`, `default_prompt` (used only by MODE B) and `pattern_scale`. Admins can add
outfits by picking any registered template; previews render automatically.

## 8. Provider abstraction

```python
class VirtualTryOnProvider:
    name
    def generate(self, request: TryOnRequest) -> TryOnResult
    def get_status(self, generation_id: str) -> TryOnResult
    def is_configured(self) -> bool
    def describe(self) -> dict
```

`TryOnRequest(person_image, garment_image, garment_metadata, options)` speaks in modes
(`fast`/`quality`) and categories, never in model names. Application code only ever calls
`get_provider()`; no module outside `virtual_tryon/` imports a concrete provider or
mentions a FASHN endpoint.

## 9. Mock provider

`VTON_PROVIDER=mock` runs the entire workflow — validation, fabric processing, garment
composition, history, admin stats — without any network call or credit. It returns a
clearly-labelled composite of the person photo and the composed garment so the plumbing is
visibly working and nobody mistakes it for a real try-on. The UI shows a "Development
mode" banner whenever the mock is active.

## 10. Testing

```bash
python3 -m unittest discover -t . -s tests
```

111 tests, ~28 s, no network, no credits, throwaway `DATA_DIR`. Coverage: JSON store and
path-traversal guards; colour extraction and pattern classification per swatch family;
fabric processing, caching, cache invalidation and "the original is never modified";
garment composition, cache keys and that the composed garment actually carries the
fabric's colours; every template renders; person-photo validation; provider switching,
FASHN input mapping per model, status and runtime-error mapping, rate limits, the
self-hosted provider's interface, the mock provider; catalogue search/filter/facets and
admin payload validation; the full HTTP surface including an end-to-end generation,
history isolation between clients and admin authorisation; importer guards and the
review/publish gate; migrations, idempotency, admin-record survival and asset repair.

## 11. Local development

```bash
pip install -r requirements.txt
cp .env.example .env          # set ADMIN_PASSWORD; FASHN_API_KEY only for real runs
VTON_PROVIDER=mock DATA_DIR=./.devdata ADMIN_PASSWORD=dev python3 server.py
```

Open <http://localhost:8000/> → **Fabric Studio**, and <http://localhost:8000/admin.html>
→ **Fabrics / Outfits / Fabric Imports**. First start seeds the catalogue in the
background (~15 s); the API returns an empty list until it finishes.

Switch to real generations with `VTON_PROVIDER=fashn_api` and a funded `FASHN_API_KEY`.

## 12. Deployment

Railway/gunicorn (the existing `Procfile` and `railway.json` are unchanged):

1. Add `pillow` and `numpy` — already in `requirements.txt`.
2. Mount a volume and set `DATA_DIR` to it (e.g. `/data`), so catalogues, processed
   fabrics and generated images survive redeploys. Without it the catalogue re-seeds on
   every boot and customer history is lost.
3. Set `VTON_PROVIDER=fashn_api` and `FASHN_API_KEY`.
4. Deploy. Migrations run on first boot; check `GET /api/admin/fabric-studio/status`.

Storage sizing: the seed catalogue is ~35 MB; each fabric+outfit pairing adds one cached
garment image (~150 KB) and each generation one result (~200 KB).

**Netlify:** the static/Netlify-functions path only proxies the original try-on endpoints.
Fabric Studio needs the Python app (image processing, catalogues, storage), so deploy it
on Railway (or any Python host) and point the domain there.

## 13. Switching to self-hosted FASHN VTON 1.5

```bash
VTON_PROVIDER=fashn_vton_15
FASHN_VTON15_URL=https://your-gpu-host
FASHN_VTON15_TOKEN=…            # optional
```

No code change, no data change: catalogues, fabric processing, garment composition,
segmentation, history, admin and the entire frontend sit above the provider interface.

`FashnVton15Provider` expects the inference server to expose the same envelope the cloud
API uses (`POST /run` with `{model_name, inputs}`, `GET /status/{id}` returning
`{id, status, output[], error}`). It also forwards local segmentation masks when a parsing
service is configured, so the GPU server can skip its own human parsing. **It has not been
exercised against a real deployment** — verify the input names your build expects and run
the mock-to-self-hosted comparison on a handful of fabrics before moving traffic.
Roll back by setting `VTON_PROVIDER=fashn_api`.

## 14. Known limitations

* **Segmentation is a stub by default.** `NoopSegmentationProvider` produces no masks;
  the try-on engine does its own human parsing. The interface, labels and a remote
  implementation are in place, but no parsing model runs locally today.
* **The live `fabric` path has not been exercised against the real API from this
  machine.** The sandbox this was built in blocks egress to `api.fashn.ai`
  specifically (`github.com` and `cdn.fashn.ai` resolve; that host does not), and
  moving the API key into the browser to work around it was not an acceptable
  trade. The request shape follows the documented contract and FASHN support's
  own guidance, and the whole pipeline is verified end to end against the mock —
  but the first real run is still ahead. Run it with:

      python3 tools/live_check.py path/to/person.jpg

  It generates three combinations (bold print, solid, lace), prints model,
  credits, timing and prompt for each, and saves the images. `--strategy template`
  runs the same comparison through the composed-flat-lay path.
* **`FashnVton15Provider` is untested against real hardware** (see §13).
* **Seed swatches are rendered, not photographed.** They are honest, licence-clean stand-ins
  and good enough to prove and benchmark the pipeline; a production catalogue wants real
  fabric photography imported through the admin tools.
* **Pattern detection is heuristic**, not a trained classifier. Tie-dye and embroidery land
  in the nearest family ("abstract"/"floral"). Curated catalogue metadata always overrides
  detection, and that is what the UI displays.
* **Garment templates are parametric silhouettes**, not tailored patterns. They read
  clearly as senator/kaftan/agbada/gown, but they are not garment-construction accurate.
* **No user accounts.** History is scoped by a browser-generated `X-BB-Client-Id`, matching
  the app's existing anonymous model. Result URLs are unguessable but not signed; clearing
  browser storage loses the link to past designs.
* **Generation runs on in-process threads** (max 4 concurrent) rather than a queue. Fine at
  current volume; a real queue is the next step under load.
* **MODE B (AI Design)** currently routes to `tryon-max` with a design prompt. It does not
  yet run a separate garment-design pass, so the prompt influences styling but the base
  garment is still the composed template.
* **Videos, payments and the original try-on are unchanged** — Fabric Studio results do not
  currently feed the paid video feature.

## 16. Theming (cream + dark)

The interface follows the supplied design reference — cream ground, white
floating cards, one accent colour — with a dark counterpart built from the same
vocabulary. The accent is **deep gold**: `#8A6410` on cream (4.8:1 against the
background, 5.4:1 under white text, so it clears AA at both jobs) and the
brighter `#D8B25A` on dark, where the CTA fills gold and takes dark text.

**How it works.** Every colour in `index.html` and `admin.html` is a `var()`
reference to a semantic token (`--bg`, `--surface`, `--text`, `--accent`,
`--cta-from/to`, `--border-rgb`, `--shadow-card`, …). A theme is one block of
token values, not a second copy of the UI:

```css
:root            { --bg:#F6F2EA; --surface:#FFF; --text:#1C1710; --accent:#8A6410; … }
[data-theme=dark]{ --bg:#0F0D0B; --surface:#1A1713; --text:#F4F1EA; --accent:#D8B25A; … }
```

* **Selection**: `data-theme` is set by a tiny inline script that runs *before
  first paint* — stored choice first, otherwise the OS `prefers-color-scheme` —
  so there is no flash of the wrong theme.
* **Toggle**: the sun/moon button in the header (and a row in the mobile menu)
  writes `localStorage.bbTheme` and updates the `theme-color` meta so the mobile
  browser chrome matches. The admin reads the same key, so the two surfaces stay
  in sync.
* **Rebranding** is a handful of token edits: `--accent`, `--accent-rgb`,
  `--accent-soft` and `--cta-from/--cta-to` in both blocks. The purple→gold
  change was exactly that — no markup was touched. Note `--on-accent` flips with
  the accent's lightness (white on cream's deep gold, near-black on dark's
  bright gold).

**Things the tokens deliberately do not cover**: text that sits on a photo scrim
(`--on-scrim`, always near-white in both themes), the brand colours of the social
share buttons, and `--photo-bg`, which matches the light backdrop baked into the
composed garment JPEGs.

**Reference details carried into Fabric Studio**: numbered step chips, purple
selection ring plus check badge on fabric and outfit tiles, the mode selector as
description cards, and a BEFORE/AFTER pair on the result screen (both panels
share one 3:4 crop so they read as a true comparison).

**Hero.** Headline with the accent line ("Wear it before / You own it"),
subtitle, primary CTA into Fabric Studio, secondary into the catalogue, a trust
row, and the before/after image; a four-item feature strip sits beneath the
hero.

The hero visual is `assets/hero-video.mp4` (1280x720, 10s, 2.3 MB) in a 16:9
frame, autoplaying muted on loop with `assets/hero-video-poster.jpg` as the
first paint. Two things make that reliable: the `muted` property is set in JS
(the attribute alone is unreliable through the React-based runtime, and without
it browsers refuse to autoplay), and `prefers-reduced-motion` leaves the poster
up with controls instead. If autoplay is refused anyway (data saver, low power
mode) the video falls back to controls rather than a frozen frame. `sw.js`
excludes video from its cache — the Cache API cannot store the 206 partial
responses that video Range requests produce.

The earlier before/after still image (`assets/hero-tryon.jpg` / `.png`) is no
longer referenced by any page.

The trust row reports live counts from the catalogue (`22 fabrics`,
`11 outfit styles`) via `/api/fabrics?limit=1` and `/api/outfits`; if either
call fails the hero still renders. The reference's "Join 10,000+ happy users"
avatar row was deliberately **not** copied — it is a fabricated metric, and this
is a real storefront.

## 15. Recommended next steps

1. Replace seed swatches with real fabric photography (admin upload or importer), starting
   with the fabrics that actually sell.
2. Run `tools/live_check.py` on a real photo, then repeat with
   `--strategy template`, and compare: fabric fidelity, garment shape, cost and
   latency are all recorded per generation. That decides whether the default
   strategy stays `fabric` or the composed template earns its place back.
3. Add a real human-parsing provider behind `SEGMENTATION_PROVIDER=remote` and measure
   whether supplying masks improves edges enough to justify the call.
4. Move generation onto a proper queue with webhooks (`POST /run?webhook_url=…`) instead of
   in-process polling threads once concurrency rises.
5. Give MODE B its own garment-design pass (`edit` on the composed garment before try-on)
   so a design brief can genuinely change collars and embroidery.
6. Offer Fabric Studio results to the existing paid video feature.
7. Add per-fabric "best outfits" curation once generation data shows which pairings work.
