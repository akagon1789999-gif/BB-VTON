#!/usr/bin/env python3
"""Verify the fabric-to-garment pipeline against the live FASHN API.

    python3 tools/live_check.py path/to/person.jpg [--mode design] [--strategy fabric]

Runs three real generations (bold print, solid, lace) through whichever
provider is configured, prints the model, credits, timing and result URL for
each, and saves the images next to the person photo.

Costs real credits: tryon-max is ~2 per image on balanced/1k, ~3 on quality.
Reads FASHN_API_KEY from .env or the environment, exactly as the app does.
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COMBOS = [
    ("fab_ankara_royal_geo", "out_grand_agbada", "bold Ankara print -> agbada"),
    ("fab_senator_charcoal", "out_modern_senator", "solid charcoal -> senator"),
    ("fab_lace_ivory_chantilly", "out_long_gown", "ivory lace -> long gown"),
]


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("person", help="full-length photo of a person")
    parser.add_argument("--mode", default="fast", choices=("fast", "design"))
    parser.add_argument("--strategy", default=None, choices=("fabric", "template", "edit"))
    parser.add_argument("--prompt", default="", help="extra design brief (design mode)")
    parser.add_argument("--data-dir", default="/tmp/bb-fabric-live")
    args = parser.parse_args()

    load_env()
    os.environ["DATA_DIR"] = args.data_dir
    os.environ.setdefault("VTON_PROVIDER", "fashn_api")
    if args.strategy:
        os.environ["VTON_GARMENT_STRATEGY"] = args.strategy

    from fabric_studio import generations, imaging
    from fabric_studio.generations import GENERATION_STORE
    from fabric_studio.migrations import run_migrations
    from fabric_studio.virtual_tryon import get_provider

    provider = get_provider()
    print("provider : %s (configured=%s)" % (provider.name, provider.is_configured()))
    if not provider.is_configured():
        sys.exit("FASHN_API_KEY is not set — nothing to verify.")

    print("seeding catalogue in %s …" % args.data_dir)
    run_migrations()

    person_path = pathlib.Path(args.person)
    person = imaging.to_data_url(person_path.read_bytes())
    out_dir = person_path.parent

    summary = []
    for fabric_id, outfit_id, label in COMBOS:
        print("\n--- %s" % label, flush=True)
        started = time.time()
        record = generations.start_generation(
            person_image=person, fabric_id=fabric_id, outfit_id=outfit_id,
            user_id="livecheck", mode=args.mode, prompt=args.prompt, run_async=False,
        )
        final = GENERATION_STORE.get(record["id"])
        meta = final.get("metadata") or {}
        print("  status  : %s" % final["status"])
        print("  model   : %s   strategy: %s" % (meta.get("model"), meta.get("strategy")))
        print("  credits : %s" % meta.get("creditsUsed"))
        print("  seconds : %.1f" % (time.time() - started))
        if final.get("error"):
            print("  error   : %s" % final["error"])
        url = final.get("provider_result_url")
        if url:
            target = out_dir / ("result-%s.jpg" % fabric_id)
            try:
                urllib.request.urlretrieve(url, target)
                print("  saved   : %s" % target)
            except Exception as exc:
                print("  (download failed: %s)" % exc)
        if meta.get("builtPrompt"):
            print("  prompt  : %s" % meta["builtPrompt"])
        summary.append((label, final["status"]))

    print("\n=== SUMMARY ===")
    for label, status in summary:
        print("%-34s %s" % (label, status))


if __name__ == "__main__":
    main()
