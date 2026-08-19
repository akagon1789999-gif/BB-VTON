#!/usr/bin/env python3
"""Attach flat-lay garment photographs to outfits in the catalogue.

    python3 tools/import_garment_photos.py photo.jpg --outfit out_grand_agbada

    python3 tools/import_garment_photos.py sheet.jpg --split 3 \
        --outfits out_grand_agbada,out_modern_senator,out_classic_kaftan

Each photo is checked with the same gate composition uses (no model in frame,
garment separable from the background, garment plain enough to re-fabric) and
the verdict is printed. Rejected photos are still stored on the record so you
can see what was tried; composition falls back to the vector template for them.
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def split_panels(image, count, trim=0.01):
    """Cut a contact sheet into `count` equal vertical panels."""
    width, height = image.size
    panel_width = width // count
    edge = int(min(width, height) * trim)
    panels = []
    for index in range(count):
        left = index * panel_width
        box = (left + edge, edge, left + panel_width - edge, height - edge)
        panels.append(image.crop(box))
    return panels


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photo", help="flat-lay photograph, or a sheet of them")
    parser.add_argument("--outfit", help="outfit id for a single photo")
    parser.add_argument("--outfits", help="comma-separated outfit ids, one per panel")
    parser.add_argument("--split", type=int, default=1, help="split the image into N panels")
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR"))
    parser.add_argument("--dry-run", action="store_true",
                        help="report the verdicts without writing to the catalogue")
    args = parser.parse_args()

    if args.data_dir:
        os.environ["DATA_DIR"] = args.data_dir

    from fabric_studio import catalog, imaging, refabric, storage
    from fabric_studio.migrations import run_migrations

    run_migrations()
    storage.ensure_dirs()

    source = pathlib.Path(args.photo)
    if not source.exists():
        sys.exit("No such file: %s" % source)
    with imaging.Image.open(str(source)) as opened:
        image = imaging.to_rgb(opened.copy())

    panels = split_panels(image, args.split) if args.split > 1 else [image]
    if args.outfits:
        outfit_ids = [o.strip() for o in args.outfits.split(",") if o.strip()]
    elif args.outfit:
        outfit_ids = [args.outfit]
    else:
        outfit_ids = []
    if outfit_ids and len(outfit_ids) != len(panels):
        sys.exit("Got %d panels but %d outfit ids." % (len(panels), len(outfit_ids)))

    review_dir = source.parent / "panels"
    review_dir.mkdir(exist_ok=True)

    accepted = 0
    for index, panel in enumerate(panels):
        outfit_id = outfit_ids[index] if outfit_ids else None
        label = outfit_id or "panel-%d" % (index + 1)
        panel_path = review_dir / ("%s.jpg" % label)
        panel.save(panel_path, quality=92)

        report = refabric.usability(panel)
        print("\n%s  (%dx%d)" % (label, panel.size[0], panel.size[1]))
        print("  saved for review : %s" % panel_path)
        print("  usable           : %s" % ("yes" if report["ok"] else "NO"))
        print("  garment coverage : %s of frame" % report.get("coverage"))
        for reason in report["reasons"]:
            print("  - %s" % reason)

        if not outfit_id or args.dry_run:
            continue
        outfit = catalog.get_outfit(outfit_id, include_inactive=True)
        if outfit is None:
            print("  ! no outfit with id %s — skipped" % outfit_id)
            continue
        relative = "outfits/%s-reference.jpg" % outfit_id
        storage.write_media(relative, imaging.encode_image(imaging.fit_within(panel, 1400), "JPEG", 92))
        catalog.OUTFIT_STORE.update(outfit_id, {
            "reference_image_path": relative,
            "reference_usable": report["ok"],
            "reference_notes": report["reasons"],
            "updated_at": catalog.now(),
        })
        accepted += 1 if report["ok"] else 0
        print("  attached to      : %s (%s)" % (outfit.get("name"), outfit_id))

    if outfit_ids and not args.dry_run:
        print("\n%d of %d photos will be used for composition; the rest fall back to the template."
              % (accepted, len(panels)))


if __name__ == "__main__":
    main()
