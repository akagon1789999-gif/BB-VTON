"""HTTP surface for Fabric Studio (Flask blueprint).

Registered by server.py. Public endpoints serve the catalogues and drive
generation; admin endpoints reuse the app's existing HTTP-basic admin guard,
which is passed in rather than imported so this package stays independent of
server.py.
"""
import functools
import json
import re

from flask import Blueprint, Response, request, send_from_directory

from . import (
    catalog,
    config,
    garment_composer,
    garment_templates,
    generations,
    imaging,
    importer,
    migrations,
    prompts,
    segmentation,
    storage,
)
from .errors import FabricStudioError, NotFoundError, ValidationError, log_exception
from .virtual_tryon import available_providers, get_provider

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def json_response(status, payload):
    response = Response(json.dumps(payload, ensure_ascii=False), status=status,
                        mimetype="application/json")
    response.headers["Cache-Control"] = "no-store"
    return response


def api_route(function):
    """Turn Fabric Studio errors into safe JSON; never leak internals."""
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except FabricStudioError as exc:
            log_exception(function.__name__, exc)
            return json_response(exc.status, exc.to_payload())
        except Exception as exc:  # pragma: no cover - defensive
            log_exception(function.__name__, exc)
            payload = {"message": "Something went wrong. Please try again.", "code": "server_error"}
            if config.debug_errors():
                payload["detail"] = str(exc)
            return json_response(500, payload)
    return wrapper


def client_id():
    """Anonymous per-browser identity used to scope generation history.

    The app has no user accounts; the browser generates and stores this id.
    It scopes history, it is not a credential — result URLs are unguessable
    on their own.
    """
    candidate = (request.headers.get("X-BB-Client-Id") or "").strip()
    if not candidate and request.is_json:
        candidate = str((request.get_json(silent=True) or {}).get("clientId") or "").strip()
    if not candidate:
        candidate = (request.args.get("clientId") or "").strip()
    if candidate and CLIENT_ID_RE.match(candidate):
        return candidate
    return "anonymous"


def _int_arg(name, default, maximum=200):
    try:
        return max(0, min(int(request.args.get(name, default)), maximum))
    except (TypeError, ValueError):
        return default


def create_blueprint(admin_required):
    bp = Blueprint("fabric_studio", __name__)

    def admin(function):
        return admin_required(api_route(function))

    # ---------------------------------------------------------- discovery --
    @bp.get("/api/fabric-studio/config")
    @api_route
    def studio_config():
        provider = get_provider()
        return json_response(200, {
            "enabled": imaging.PILLOW_AVAILABLE,
            "provider": provider.name,
            "providerConfigured": provider.is_configured(),
            "mockMode": provider.name == "mock",
            "supportsDesignMode": provider.supports_prompt,
            "segmentation": segmentation.get_segmentation_provider().describe(),
            "garmentStrategy": config.vton_garment_strategy(),
            "modes": [
                {"id": generations.MODE_FAST, "name": "Fabric Try-On",
                 "description": "Your fabric, tailored into the outfit you picked and fitted to your photo."},
                {"id": generations.MODE_DESIGN, "name": "AI Design",
                 "description": "Adds your own brief — collar, embroidery, styling — and generates at the highest quality."},
            ],
            "limits": {
                "maxUploadBytes": config.max_upload_bytes(),
                "minPhotoEdge": config.person_image_min_edge(),
            },
            "stageLabels": generations.STAGE_LABELS,
        })

    # ---------------------------------------------------------- catalogues --
    @bp.get("/api/fabrics")
    @api_route
    def list_fabrics():
        result = catalog.search_fabrics(
            query=request.args.get("search"),
            category=request.args.get("category"),
            pattern=request.args.get("pattern"),
            color=request.args.get("color"),
            tag=request.args.get("tag"),
            limit=_int_arg("limit", 60),
            offset=_int_arg("offset", 0, maximum=5000),
        )
        result["facets"] = catalog.facets()
        return json_response(200, result)

    @bp.get("/api/fabrics/<fabric_id>")
    @api_route
    def get_fabric(fabric_id):
        record = catalog.require_fabric(fabric_id)
        return json_response(200, catalog.fabric_view(record))

    @bp.get("/api/outfits")
    @api_route
    def list_outfits():
        category = (request.args.get("category") or "").strip()
        records = catalog.all_outfits()
        if category and category != "All":
            records = [r for r in records if r.get("category") == category]
        return json_response(200, {
            "items": [catalog.outfit_view(r) for r in records],
            "categories": sorted({r.get("category") for r in catalog.all_outfits() if r.get("category")}),
        })

    @bp.get("/api/outfits/<outfit_id>")
    @api_route
    def get_outfit(outfit_id):
        return json_response(200, catalog.outfit_view(catalog.require_outfit(outfit_id)))

    # ------------------------------------------------------------- preview --
    @bp.post("/api/fabric-studio/validate-photo")
    @api_route
    def validate_photo():
        payload = request.get_json(silent=True) or {}
        image = payload.get("personImage")
        if not image:
            raise ValidationError("Please choose a photo first.", detail="Missing personImage")
        _data_url, report = segmentation.validator.prepare(image)
        return json_response(200, {
            "ok": True,
            "warnings": report.get("warnings", []),
            "metrics": report.get("metrics", {}),
        })

    @bp.get("/api/fabric-studio/preview")
    @api_route
    def preview_garment():
        """The composed garment for a fabric+outfit pair, before generating."""
        fabric = catalog.ensure_fabric_processed(
            catalog.require_fabric(request.args.get("fabricId"))["id"]
        )
        outfit = catalog.require_outfit(request.args.get("outfitId"))
        composed = garment_composer.compose(fabric, outfit)
        return json_response(200, {
            "garmentImageUrl": composed["url"],
            "cached": composed["cached"],
            # What we will actually ask the model for. Surfaced so the studio
            # can show it and an admin can debug a disappointing result.
            "designBrief": prompts.build_tryon_prompt(outfit, fabric),
            "strategy": config.vton_garment_strategy(),
            "fabric": catalog.fabric_view(fabric),
            "outfit": catalog.outfit_view(outfit),
        })

    # ---------------------------------------------------------- generation --
    @bp.post("/api/fabric-studio/generate")
    @api_route
    def generate():
        payload = request.get_json(silent=True)
        if payload is None:
            raise ValidationError("Something went wrong. Please try again.", detail="Invalid JSON body")
        person_image = payload.get("personImage")
        if not person_image:
            raise ValidationError("Please upload your photo to continue.", detail="Missing personImage")
        fabric_upload = payload.get("fabricImage")
        garment_upload = payload.get("garmentImage")
        if not payload.get("outfitId") and not garment_upload:
            raise ValidationError("Please choose an outfit or upload a garment to continue.",
                                  detail="Missing outfitId and garmentImage")

        record = generations.start_generation(
            person_image=person_image,
            fabric_id=payload.get("fabricId"),
            outfit_id=payload.get("outfitId"),
            fabric_upload=fabric_upload,
            garment_upload=garment_upload,
            garment_name=(payload.get("garmentName") or "").strip()[:120] or None,
            user_id=client_id(),
            mode=payload.get("mode") or generations.MODE_FAST,
            prompt=payload.get("prompt"),
        )
        return json_response(202, generations.generation_view(record))

    @bp.get("/api/fabric-studio/generations/<generation_id>")
    @api_route
    def generation_status(generation_id):
        record = generations.get_generation(generation_id, user_id=client_id())
        if record is None:
            raise NotFoundError("We couldn't find that design.", detail="Generation %s" % generation_id)
        return json_response(200, generations.generation_view(record))

    @bp.get("/api/fabric-studio/generations")
    @api_route
    def generation_history():
        records = generations.list_generations(client_id(), limit=_int_arg("limit", 40))
        return json_response(200, {
            "items": [generations.generation_view(r) for r in records],
        })

    # --------------------------------------------------------------- media --
    @bp.get("/media/<path:filename>")
    def media(filename):
        try:
            storage.media_path(filename)
        except ValueError:
            return json_response(404, {"message": "Not found."})
        response = send_from_directory(storage.media_dir(), filename)
        if filename.startswith("generations/"):
            # A customer's generated look: cacheable by their browser only.
            response.headers["Cache-Control"] = "private, max-age=3600"
        else:
            # Catalogue assets are content-addressed, so cache them hard.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    # --------------------------------------------------------------- admin --
    @bp.get("/api/admin/fabric-studio/status")
    @admin
    def admin_status():
        provider = get_provider()
        return json_response(200, {
            "migrations": migrations.status(),
            "provider": provider.describe(),
            "availableProviders": list(available_providers()),
            "importer": importer.status(),
            "templates": garment_templates.ids(),
            "generations": generations.stats(),
        })

    @bp.post("/api/admin/fabric-studio/migrate")
    @admin
    def admin_migrate():
        return json_response(200, migrations.run_migrations())

    @bp.post("/api/admin/fabric-studio/repair")
    @admin
    def admin_repair():
        return json_response(200, migrations.repair_assets())

    @bp.get("/api/admin/fabrics")
    @admin
    def admin_list_fabrics():
        records = catalog.all_fabrics(include_inactive=True)
        records.sort(key=lambda r: (r.get("category") or "", r.get("name") or ""))
        return json_response(200, {
            "items": [catalog.fabric_view(r) for r in records],
            "pendingImports": [catalog.fabric_view(r) for r in importer.list_pending()],
            "categories": catalog.facets()["categories"],
        })

    @bp.post("/api/admin/fabrics")
    @admin
    def admin_create_fabric():
        cleaned = catalog.validate_fabric_payload(request.form)
        upload = request.files.get("image")
        if not upload or not upload.filename:
            raise ValidationError("Upload a fabric photo.", detail="Missing image file")
        raw = upload.read(config.max_upload_bytes() + 1)
        if len(raw) > config.max_upload_bytes():
            raise ValidationError("That image is too large.", detail="Upload exceeded limit")

        image = imaging.open_image(raw)
        from .fabric_processor import processor
        processor.validate_source(image)

        fabric_id = storage.new_id("fab")
        relative = "fabrics/original/%s.jpg" % fabric_id
        storage.write_media(relative, imaging.encode_image(image, "JPEG", 94))

        record = {
            "id": fabric_id,
            "image_path": relative,
            "image_url": storage.media_url(relative),
            "source_name": cleaned.get("source_name") or "BB Apparel",
            "license": cleaned.get("license") or "BB Apparel — uploaded asset",
            "review_status": catalog.REVIEW_APPROVED,
            "is_active": cleaned.get("is_active", True),
        }
        record.update(cleaned)
        catalog.save_fabric(record)
        return json_response(201, catalog.fabric_view(catalog.ensure_fabric_processed(fabric_id)))

    @bp.put("/api/admin/fabrics/<fabric_id>")
    @admin
    def admin_update_fabric(fabric_id):
        record = catalog.require_fabric(fabric_id, include_inactive=True)
        cleaned = catalog.validate_fabric_payload(request.form, partial=True)
        updated = dict(record)
        updated.update(cleaned)

        upload = request.files.get("image")
        if upload and upload.filename:
            raw = upload.read(config.max_upload_bytes() + 1)
            if len(raw) > config.max_upload_bytes():
                raise ValidationError("That image is too large.", detail="Upload exceeded limit")
            image = imaging.open_image(raw)
            from .fabric_processor import processor
            processor.validate_source(image)
            relative = "fabrics/original/%s.jpg" % fabric_id
            storage.write_media(relative, imaging.encode_image(image, "JPEG", 94))
            updated["image_path"] = relative
            updated["image_url"] = storage.media_url(relative)
            updated.pop("swatch", None)  # no longer a generated seed image

        catalog.save_fabric(updated)
        reprocess = bool(upload and upload.filename)
        return json_response(200, catalog.fabric_view(
            catalog.ensure_fabric_processed(fabric_id, force=reprocess)
        ))

    @bp.post("/api/admin/fabrics/<fabric_id>/reprocess")
    @admin
    def admin_reprocess_fabric(fabric_id):
        return json_response(200, catalog.fabric_view(catalog.ensure_fabric_processed(fabric_id, force=True)))

    @bp.delete("/api/admin/fabrics/<fabric_id>")
    @admin
    def admin_delete_fabric(fabric_id):
        hard = (request.args.get("hard") or "").lower() in ("1", "true", "yes")
        if hard:
            catalog.delete_fabric(fabric_id)
            return json_response(200, {"message": "Deleted."})
        return json_response(200, catalog.fabric_view(catalog.set_fabric_active(fabric_id, False)))

    @bp.post("/api/admin/fabrics/<fabric_id>/activate")
    @admin
    def admin_activate_fabric(fabric_id):
        return json_response(200, catalog.fabric_view(catalog.set_fabric_active(fabric_id, True)))

    @bp.get("/api/admin/outfits")
    @admin
    def admin_list_outfits():
        return json_response(200, {
            "items": [catalog.outfit_view(r) for r in catalog.all_outfits(include_inactive=True)],
            "templates": garment_templates.ids(),
        })

    @bp.post("/api/admin/outfits")
    @admin
    def admin_create_outfit():
        cleaned = catalog.validate_outfit_payload(request.form)
        outfit_id = storage.new_id("out")
        record = {"id": outfit_id, "is_active": True}
        record.update(cleaned)
        record.setdefault("garment_type", "one-pieces")
        record.setdefault("category", "Unisex")
        record.setdefault("mask_type", "full_body")
        catalog.save_outfit(record)
        _render_outfit_preview(outfit_id, request.files.get("preview"))
        return json_response(201, catalog.outfit_view(catalog.require_outfit(outfit_id, include_inactive=True)))

    @bp.put("/api/admin/outfits/<outfit_id>")
    @admin
    def admin_update_outfit(outfit_id):
        record = catalog.require_outfit(outfit_id, include_inactive=True)
        cleaned = catalog.validate_outfit_payload(request.form, partial=True)
        updated = dict(record)
        updated.update(cleaned)
        catalog.save_outfit(updated)
        upload = request.files.get("preview")
        if upload and upload.filename or cleaned.get("template_id"):
            _render_outfit_preview(outfit_id, upload)
        reference_report = _store_outfit_reference(outfit_id, request.files.get("reference"))
        payload = catalog.outfit_view(catalog.require_outfit(outfit_id, include_inactive=True))
        if reference_report:
            payload["referenceReport"] = reference_report
        return json_response(200, payload)

    @bp.delete("/api/admin/outfits/<outfit_id>")
    @admin
    def admin_delete_outfit(outfit_id):
        hard = (request.args.get("hard") or "").lower() in ("1", "true", "yes")
        if hard:
            catalog.delete_outfit(outfit_id)
            return json_response(200, {"message": "Deleted."})
        return json_response(200, catalog.outfit_view(catalog.set_outfit_active(outfit_id, False)))

    @bp.post("/api/admin/outfits/<outfit_id>/activate")
    @admin
    def admin_activate_outfit(outfit_id):
        return json_response(200, catalog.outfit_view(catalog.set_outfit_active(outfit_id, True)))

    # ------------------------------------------------------------ importer --
    @bp.get("/api/admin/fabric-imports")
    @admin
    def admin_list_imports():
        return json_response(200, {
            "items": [catalog.fabric_view(r) for r in importer.list_pending()],
            "status": importer.status(),
        })

    @bp.post("/api/admin/fabric-imports")
    @admin
    def admin_import_fabric():
        payload = request.get_json(silent=True) or request.form.to_dict()
        record = importer.import_fabric(
            url=payload.get("url"),
            payload=payload,
            imported_by="admin",
        )
        return json_response(201, catalog.fabric_view(record))

    @bp.post("/api/admin/fabric-imports/<fabric_id>/publish")
    @admin
    def admin_publish_import(fabric_id):
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        if payload:
            cleaned = catalog.validate_fabric_payload(payload, partial=True)
            if cleaned:
                record = catalog.require_fabric(fabric_id, include_inactive=True)
                record.update(cleaned)
                catalog.save_fabric(record)
        return json_response(200, catalog.fabric_view(importer.publish(fabric_id)))

    @bp.post("/api/admin/fabric-imports/<fabric_id>/reject")
    @admin
    def admin_reject_import(fabric_id):
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        return json_response(200, catalog.fabric_view(
            importer.reject(fabric_id, reason=payload.get("reason", ""))
        ))

    return bp


def _store_outfit_reference(outfit_id, upload):
    """Store a photograph of the real garment, and say whether it is usable.

    The photo is kept either way — an operator may want it on record — but
    composition only uses it when refabric.usability() passes.
    """
    if not upload or not upload.filename:
        return None
    from . import refabric

    raw = upload.read(config.max_upload_bytes() + 1)
    if len(raw) > config.max_upload_bytes():
        raise ValidationError("That image is too large.", detail="Reference upload exceeded limit")
    image = imaging.fit_within(imaging.open_image(raw), 1400)
    relative = "outfits/%s-reference.jpg" % outfit_id
    storage.write_media(relative, imaging.encode_image(image, "JPEG", 92))

    report = refabric.usability(image)
    catalog.OUTFIT_STORE.update(outfit_id, {
        "reference_image_path": relative,
        "reference_usable": report["ok"],
        "reference_notes": report["reasons"],
        "updated_at": catalog.now(),
    })
    return report


def _render_outfit_preview(outfit_id, upload=None):
    """Use an uploaded photograph if given, else render the garment sketch."""
    record = catalog.require_outfit(outfit_id, include_inactive=True)
    custom = bool(upload and upload.filename)
    relative = "outfits/%s.%s" % (outfit_id, "jpg" if custom else "png")
    if custom:
        raw = upload.read(config.max_upload_bytes() + 1)
        image = imaging.open_image(raw)
        storage.write_media(relative, imaging.encode_image(imaging.fit_within(image, 900), "JPEG", 86))
    else:
        preview = garment_composer.render_preview(record["template_id"])
        storage.write_media(relative, imaging.encode_image(preview, "PNG"))
    previous = record.get("preview_image_path")
    if previous and previous != relative:
        storage.delete_media(previous)
    catalog.OUTFIT_STORE.update(outfit_id, {
        "preview_image_path": relative,
        "preview_image_url": storage.media_url(relative),
        # A real photograph outranks the sketch and survives preview refreshes.
        "preview_custom": custom,
        "preview_version": garment_composer.PREVIEW_VERSION,
        "updated_at": catalog.now(),
    })
