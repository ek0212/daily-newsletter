#!/usr/bin/env python3
"""Merge browser-exported likes JSON into site/likes.json."""

import argparse
import json
from pathlib import Path

SITE_LIKES = Path(__file__).resolve().parent.parent / "site" / "likes.json"


def main():
    parser = argparse.ArgumentParser(description="Merge newsletter likes into site/likes.json")
    parser.add_argument("--input", required=True, help="Path to browser-exported likes JSON file")
    args = parser.parse_args()

    incoming = json.loads(Path(args.input).read_text())
    incoming_items = incoming.get("items", [])

    existing = {"version": 1, "items": []}
    if SITE_LIKES.exists():
        existing = json.loads(SITE_LIKES.read_text())

    existing_ids = {item["id"] for item in existing["items"]}
    new_count = 0
    for item in incoming_items:
        if item.get("id") and item["id"] not in existing_ids:
            existing["items"].append(item)
            existing_ids.add(item["id"])
            new_count += 1

    SITE_LIKES.parent.mkdir(parents=True, exist_ok=True)
    SITE_LIKES.write_text(json.dumps(existing, indent=2))
    print(f"Merged {new_count} new items ({len(existing['items'])} total)")


if __name__ == "__main__":
    main()
