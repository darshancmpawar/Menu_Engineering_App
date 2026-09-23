#!/usr/bin/env python3
"""Import MOengage Bangalore's 3-month menu into the Bangalore ontology.

Source: `data/raw/source_workbooks/moengage_menu_3_months.xlsx` — one sheet,
thirteen week blocks stacked vertically, each opened by a `CATEGORY` header row
with the category in column 0 and one column per weekday. The shared three-pass
machinery lives in `menu_import.py`; what is here is MOengage's grid and its
label map.

Three things this menu does that the others do not:

* **The `RICE` row is steamed rice**, and the flavoured rice sits on the
  UNLABELLED row directly beneath it. An unlabelled row continues the label
  above, which is right here — both rows are rice — so `RICE` maps to `rice`
  and `steamed_rice` is dropped as a const-slot staple by name.
* **"Na", "-" and "--" mean the category is not served that day.** Imported
  literally they become dishes called `na` and `nil`; the shared reader treats
  them as placeholders.
* **Cells hold combos**: "Puri + Chapti", "Idli + Chutney", "Aloo Bonda +
  Chutney". Split on `+`, so the bread row yields puri and chapati rather than
  one dish named after both.

Skipped: `SALAD DRESSING` (a dressing is not a slot), `ACCOMPANIMENTS` (curd
and papad, both const slots), and the make-your-own-salad station rows — "MYOS
( carrots, cucumber, onion )" and "Make your Own Salad" name an assembly bar,
not a dish.

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
SOURCE = (ROOT / "data" / "raw" / "source_workbooks"
          / "moengage_menu_3_months.xlsx")
BLR = ROOT / "data" / "raw" / "city_items" / "bangalore.xlsx"

from menu_import import (  # noqa: E402  (needs the sys.path line above)
    ImportSpec,
    norm,
    run_import,
    to_item,
)
from menu_import import build as _build  # noqa: E402
from menu_import import vocab_from as _vocab_from  # noqa: E402

CLIENT_TOKEN = "MOengage"
COMMON_AT = 6

DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday"}

#: Printed label (lower-cased, trimmed) -> the app's course_type.
CATEGORY_MAP = {
    "welcome drink": "welcome_drink",
    "salad": "salad",
    "veg starter": "starter",
    "bread": "bread",
    "rice": "rice",                     # steamed rice + the flavoured rice row
    "veg dry": "veg_dry",
    "veg gravy": "veg_gravy",
    "dal": "dal",
    "sambar": "sambar",
    "dal / sambar": "dal",              # refile_lentils splits it by name
    "rasam": "rasam",
    "healthy options": "healthy_rice",
    "sweet": "dessert",
    "non veg starter": "nonveg_main",
    "non veg starter/ dry": "nonveg_main",
    "non veg biryani /gravy": "nonveg_main",
}

#: The printed menu's own row labels tell us how each non-veg dish is served,
#: which is what makes it placeable — see `menu_import.nonveg_structural_flags`.
STYLE_BY_LABEL = {
    "Lunch||non veg starter": "dry",
    "Lunch||non veg starter/ dry": "dry",
    "Lunch||non veg biryani /gravy": "gravy",
}

#: Header rows and rows that are not a menu slot.
SKIP_LABELS = {"category", "salad dressing", "accompaniments"}

#: Const-slot staples the menu repeats daily, plus the assembly-bar stations.
SKIP_ITEMS = {"steamed_rice", "white_rice", "rice", "curd", "papad",
              "masala_papad", "applam_south", "spicy_papad_south", "raita",
              "curd_raita", "myos", "make_your_own_salad", "chutney",
              "green_chutney", "na", "nil"}


def vocab_from(frame) -> dict:
    return _vocab_from(frame, CLIENT_TOKEN)


def clean_name(raw: str) -> str:
    """Drop the parenthesised contents list MOengage writes after a station."""
    return to_item(raw, drop_parentheticals=True)


def _dishes(sheet, r) -> list:
    out = []
    for c in range(1, sheet.shape[1]):
        dish = norm(sheet.iat[r, c])
        low = dish.strip().lower()
        if (not dish or low in DAYS
                or re.match(r"^\d{4}-\d{2}-\d{2}", dish)
                or re.fullmatch(r"[\d.]+", low)):
            continue
        out.append(dish)
    return out


def parse_source(source=SOURCE) -> dict:
    """{'Lunch||<label>': [raw dish, …]} across every week block."""
    if not source.exists():                                # pragma: no cover
        raise SystemExit(f"missing source workbook: {source}")
    sheet = pd.read_excel(source, sheet_name=0, header=None)
    out = defaultdict(set)
    label = None
    for r in range(sheet.shape[0]):
        raw_label = norm(sheet.iat[r, 0])
        low = raw_label.strip().lower()
        if raw_label:
            # A block heading ("LUNCH MENU 19 JAN-23JAN") resets the carry, or
            # the first row of the next block inherits the last block's label.
            label = low if (low in CATEGORY_MAP or low in SKIP_LABELS) else None
        if not label or label in SKIP_LABELS:
            continue
        if not CATEGORY_MAP.get(label):
            continue
        dishes = _dishes(sheet, r)
        if dishes:
            out[f"Lunch||{label}"].update(dishes)
    return {k: sorted(v) for k, v in out.items()}


SPEC = ImportSpec(
    client_token=CLIENT_TOKEN,
    city_path=BLR,
    parse=parse_source,
    category_map={f"Lunch||{k}": v for k, v in CATEGORY_MAP.items()},
    common_at=COMMON_AT,
    clean_name=clean_name,
    skip_items=SKIP_ITEMS,
    split_combos=True,
    style_by_label=STYLE_BY_LABEL,
)


def build(frame, raw, spec=SPEC):
    return _build(frame, raw, spec)


def main(dry_run=False):
    return run_import(SPEC, dry_run=dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
