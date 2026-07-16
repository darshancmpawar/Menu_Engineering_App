#!/usr/bin/env python3
"""
Migrate clients.json into Supabase.

Usage:
  export SUPABASE_URL="https://your-project.supabase.co"
  export SUPABASE_KEY="your-anon-or-service-role-key"
  python scripts/seed_supabase.py [--json data/configs/clients.json]

This script is idempotent — it uses upsert so re-running is safe.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from supabase import create_client


def main():
    parser = argparse.ArgumentParser(description="Seed Supabase from clients.json")
    parser.add_argument(
        "--json",
        default=str(Path(__file__).parent.parent / "data" / "configs" / "clients.json"),
        help="Path to clients.json (default: data/configs/clients.json)",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY environment variables.")
        sys.exit(1)

    sb = create_client(url, key)

    with open(args.json) as f:
        data = json.load(f)

    # The whole per-client config is one document in clients.counters. Fold the
    # legacy clients.json shape (menu_categories + slot_count_overrides +
    # theme_overrides) into a single primary counter per client.
    categories = data.get("menu_categories", {})
    slot_counts = data.get("slot_count_overrides", {})
    themes = data.get("theme_overrides", {})

    client_rows = []
    for c in data["clients"]:
        name = c["name"]
        cat = c.get("menu_category")
        counter = {
            "name": "Counter 1",
            "categories": categories.get(cat, []),
            "slot_counts": {
                slot: int(cnt) for slot, cnt in slot_counts.get(name, {}).items()
            },
            "theme_map": {
                day.lower(): theme for day, theme in themes.get(name, {}).items()
            },
        }
        client_rows.append({"name": name, "counters": [counter]})
    sb.table("clients").upsert(client_rows).execute()
    print(f"  Upserted {len(client_rows)} clients (config folded into counters)")

    # Upsert app settings
    settings = [
        {"key": "core_min_one_slots", "value": json.dumps(data.get("core_min_one_slots", []))},
        {"key": "constant_slots", "value": json.dumps(data.get("constant_slots", []))},
        {"key": "fallback_menu_category", "value": json.dumps(data.get("fallback_menu_category", ""))},
    ]
    sb.table("app_settings").upsert(settings).execute()
    print(f"  Upserted {len(settings)} app settings")

    print("\nDone! Supabase is now populated with your client configuration.")


if __name__ == "__main__":
    main()
