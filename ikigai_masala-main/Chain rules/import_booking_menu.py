#!/usr/bin/env python3
"""Import Booking.com's 3-month menu into the Bangalore ontology.

Source: `data/raw/source_workbooks/booking_menu_3_months.xlsx` — a printed
Lunch / Dinner / Breakfast grid, week blocks laid side by side. **Only Lunch and
Dinner are imported**: the tool plans lunch, and the breakfast sheet is cereals,
cut fruit, milk and juice as much as it is dishes. The one thing breakfast has
that lunch does not is the infused-water list, and Lunch carries the same 50
under "Detox water", so nothing is lost.

Three passes, the order every earlier city import used:

1. **Language.** The source spells the same dish several ways — `Chciken` /
   `Chcken` / `Chiceken`, `Chilli Parataha` / `Chilli Paratha`, `Brown Rice
   Kanjee` / `Brown rice kanjee`, `Apple&Celery Infused Wate`. Names are
   lowercased to the ontology's snake_case and the known misspellings corrected.
2. **Similar items.** What survives is folded at 0.90 similarity, so
   `beet_and_celery_detox_water` and `beetroot_and_celery_detox_water` become
   one dish rather than two.
3. **Unique.** Anything Bangalore already carries is dropped — the import only
   ever adds dishes that are new.

`client` tagging follows the rule the client stated: an item made by **6 or more
clients is `common`**, otherwise it lists the clients that make it. A dish new to
the ontology is made by Booking alone, so it is tagged `Booking.com`; a dish
Bangalore already has gains `Booking.com` in its list, and if that takes the
count to 6 the row is promoted to `common`.

Two new categories come out of this menu and are created here:
`infused_water` (Detox water) and `nonveg_soup` (Non Veg Soup).

Attributes are set only where the dish NAME supports them — course_type,
cuisine_family, primary_protein, the veg/non-veg flags — and left at the
schema default otherwise. Guessing `is_premium_gravy` or a colour for 628 dishes
would be inventing data the rules then act on; the cloned-template approach in
`expand_side_pools.py` sets the same honest minimum.

All three passes plus the row builder are shared with every other client menu
import and live in `menu_import.py`; what stays here is Booking's own workbook
grid and its label -> slot map.

Idempotent: re-running adds nothing and re-tags nothing.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "raw" / "source_workbooks" / "booking_menu_3_months.xlsx"
BLR = ROOT / "data" / "raw" / "city_items" / "bangalore.xlsx"

# The shared three-pass machinery. Re-exported here because this module is the
# public face of the Booking import — its tests, and anyone reading it, expect
# `to_item`/`fold_similar`/`KEEP_APART` to be reachable from the importer they
# are testing rather than from a helper they would have to go looking for.
from menu_import import (  # noqa: E402,F401  (needs the sys.path line above)
    KEEP_APART,
    SAME_DISH,
    ImportSpec,
    _existing_twin,
    fold_similar,
    norm,
    run_import,
    to_item,
)
from menu_import import build as _build  # noqa: E402
from menu_import import vocab_from as _vocab_from  # noqa: E402

CLIENT_TOKEN = "Booking.com"
COMMON_AT = 6          # >= this many clients make it -> `common`

#: Booking's menu-pattern label -> the app's course_type. Breakfast omitted.
CATEGORY_MAP = {
    "Lunch||Welcome Drink": "welcome_drink",
    "Lunch||Detox water": "infused_water",
    "Lunch||Veg Soup": "soup",
    "Lunch||Non Veg Soup": "nonveg_soup",
    "Lunch||Main Entrée - Dry": "veg_dry",
    "Lunch||Main Entrée - 2": "veg_gravy",
    "Lunch||Live": "starter",
    "Lunch||Indian Bread": "bread",
    "Lunch||Flavoured Bread": "bread",
    "Lunch||Flavoured Rice": "rice",
    "Lunch||Dal  (Buffet 1)": "dal",
    "Lunch||Dal (Buffet 1)": "dal",
    "Lunch||Pulses - 1": "sambar",
    "Lunch||Pulses - 2": "rasam",
    "Lunch||Non-Veg": "nonveg_main",
    "Lunch||Dessert": "dessert",
    "Lunch||Healthy Option": "healthy_rice",
    "Dinner||Welcome Drink": "welcome_drink",
    "Dinner||Salad": "salad",
    "Dinner||Veg Dry": "veg_dry",
    "Dinner||Veg Gravy": "veg_gravy",
    "Dinner||Indian Bread": "bread",
    "Dinner||Flavoured Rice": "rice",
    "Dinner||Dal/Sambar": "dal",
    "Dinner||Rasam": "rasam",
    "Dinner||Dessert": "dessert",
    "Dinner||Non Veg": "nonveg_main",
}

#: Steamed rice / curd are fixed condiments the app pins as CONST_SLOTS, and
#: `Accompaniments` is a single "Fryums" row. Nothing to import.
SKIP_LABELS = {"Steamed Rice", "Curd", "Accompaniments", "Live Salad Counter"}


def vocab_from(frame) -> dict:
    """Token frequency of the Bangalore names that predate this import."""
    return _vocab_from(frame, CLIENT_TOKEN)


def parse_source() -> dict:
    """{'<Sheet>||<Label>': [raw dish, …]} for the Lunch and Dinner sheets."""
    LABEL_HINTS = {"menu pattern", "dinner menu", "lunch", "menu spread",
                   "descrption", "description", "breakfast"}
    DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"}
    out = defaultdict(set)
    for sheet in ("Lunch", "Dinner"):
        d = pd.read_excel(SOURCE, sheet_name=sheet, header=None)
        label_cols = []
        for c in range(d.shape[1]):
            vals = [norm(v).lower() for v in d[c] if norm(v)]
            if len(vals) >= 5 and (any(v in LABEL_HINTS for v in vals)
                                   or len(set(vals)) < len(vals) * 0.9):
                label_cols.append(c)
        for lc in label_cols:
            end = next((c for c in label_cols if c > lc), d.shape[1])
            for r in range(d.shape[0]):
                label = norm(d.iat[r, lc])
                if not label or label.lower() in LABEL_HINTS:
                    continue
                for c in range(lc + 1, end):
                    dish = norm(d.iat[r, c])
                    low = dish.lower()
                    if (not dish or low in DAYS
                            or re.match(r"^\d{4}-\d{2}-\d{2}", dish)
                            or re.fullmatch(r"[\d.]+", low)):
                        continue
                    out[f"{sheet}||{label}"].add(dish)
    return {k: sorted(v) for k, v in out.items()}


SPEC = ImportSpec(
    client_token=CLIENT_TOKEN,
    city_path=BLR,
    parse=parse_source,
    category_map=CATEGORY_MAP,
    skip_labels=SKIP_LABELS,
    common_at=COMMON_AT,
)


def build(frame, raw, spec=SPEC):
    """Booking's rows out of the shared builder (see `menu_import.build`)."""
    return _build(frame, raw, spec)


def main(dry_run=False):
    return run_import(SPEC, dry_run=dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
