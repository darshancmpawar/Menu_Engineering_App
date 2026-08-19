#!/usr/bin/env python3
"""Import Citrix (CSG) Bangalore's master menu into the Bangalore ontology.

Source: `data/raw/source_workbooks/citrix_csg_master_menu.xlsx` — one sheet per
service (Breakfast / Lunch / Dinner / Nonveg / Snacks / Juice), each a stack of
week blocks with the category in column 0 and a **portion-size column between
every pair of day columns**. The shared three-pass machinery lives in
`menu_import.py`; what is here is CSG's grid and its label map.

**Lunch, Dinner and Nonveg are imported.** Breakfast is idlis, dosas and
uppittu — a separate service the tool does not plan, and the same call the
Booking import made. Snacks is rolls, sandwiches and burgers, and Juice is a
beverage counter; neither maps to a solver slot, and the Lunch and Dinner
sheets carry their own `Welcome Drink/Soup` row.

Three things specific to this workbook:

* the `Kg/Pcs` columns are skipped by header. Their numbers would filter out as
  numeric anyway, but the cells also hold "Adq" (adequate), which imports as a
  dish.
* `Welcome Drink/Soup` is **one row for two slots** — buttermilk on some days,
  roasted tomato soup on others. It is re-filed by name, since a dish called a
  soup belongs in `soup` however the row is labelled.
* dish names carry cuisine markers — "Carrot methi subzi NI", "Udupi Veg Kurma
  SI", "Veg Hyderabadi gravy N". These annotate the row, not the dish, so they
  are stripped; left in they make `udupi_veg_kurma_si` a different dish from
  the `udupi_veg_kurma` the ontology already has.

`Rice - I` is white rice (a CONST slot) and is skipped. `Rice - II` is red rice
every day, which is the healthy-rice station rather than the flavoured-rice one.

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
          / "citrix_csg_master_menu.xlsx")
BLR = ROOT / "data" / "raw" / "city_items" / "bangalore.xlsx"

from menu_import import (  # noqa: E402  (needs the sys.path line above)
    ImportSpec,
    norm,
    quantity_columns,
    refile_lentils,
    run_import,
    to_item,
)
from menu_import import build as _build  # noqa: E402
from menu_import import vocab_from as _vocab_from  # noqa: E402

CLIENT_TOKEN = "Citrix"
COMMON_AT = 6

#: Sheets that carry a plated service. Breakfast / Snacks / Juice are skipped.
SHEETS = ("Lunch", "Dinner", "Nonveg")

DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday"}

#: Printed label (lower-cased, trimmed) -> the app's course_type.
CATEGORY_MAP = {
    "welcome drink/soup": "welcome_drink",   # refiled to `soup` by name
    "starter": "starter",
    "dry veg(si/ni)": "veg_dry",
    "gravy veg( ni/si)": "veg_gravy",
    "gravy veg(ni/si)": "veg_gravy",
    "sambar": "sambar",
    "rasam": "rasam",
    "dal": "dal",
    "phulka": "bread",
    "indian bread(si/ni)": "bread",
    "rice - ii": "healthy_rice",             # red rice, every day
    "riceiii(si/ni)flavoured rice": "rice",
    "raitha/chutney": "curd_side",
    "salad": "salad",
    "sweet": "dessert",
    # the Nonveg sheet's two rows
    "lunch": "nonveg_main",
    "dinner": "nonveg_main",
}

#: Headings, the white-rice CONST slot, and the fixed curd station.
SKIP_LABELS = {"lunch menu", "dinner menu", "nonveg menu", "breakfast menu",
               "snacks", "date", "menu grib", "day", "rice - i", "curd"}

#: Const-slot staples and the condiments the Raitha/Chutney row also carries.
SKIP_ITEMS = {"white_rice", "steamed_rice", "red_rice", "curd", "papad",
              "pickle", "chutney", "sauce", "raitha", "raita", "adq",
              "green_chutney", "tomato_sauce"}

#: A trailing cuisine marker: "Carrot methi subzi NI", "Udupi Veg Kurma SI".
_CUISINE_SUFFIX = re.compile(r"[\s\-–]+(?:ni|si|n|s)\s*$", re.I)


def vocab_from(frame) -> dict:
    return _vocab_from(frame, CLIENT_TOKEN)


def clean_name(raw: str) -> str:
    text = _CUISINE_SUFFIX.sub("", str(raw).strip())
    return to_item(text, drop_parentheticals=True)


def refile(item: str, course: str) -> str:
    """`Welcome Drink/Soup` is one row for two slots — the name decides."""
    if course == "welcome_drink":
        toks = set(item.split("_"))
        if toks & {"soup", "shorba", "broth", "chowder"}:
            return "soup"
        return "welcome_drink"
    return refile_lentils(item, course)


def _dishes(sheet, r, skip_cols) -> list:
    out = []
    for c in range(1, sheet.shape[1]):
        if c in skip_cols:
            continue
        dish = norm(sheet.iat[r, c])
        low = dish.strip().lower()
        if (not dish or low in DAYS
                or re.match(r"^\d{4}-\d{2}-\d{2}", dish)
                or re.fullmatch(r"[\d.]+", low)):
            continue
        out.append(dish)
    return out


def parse_source(source=SOURCE) -> dict:
    """{'<Sheet>||<label>': [raw dish, …]} for the plated services."""
    if not source.exists():                                # pragma: no cover
        raise SystemExit(f"missing source workbook: {source}")
    out = defaultdict(set)
    for sheet_name in SHEETS:
        # The Dinner sheet reports 1,048,575 rows (Excel's maximum) and is
        # almost entirely empty, so the read is bounded rather than trusted.
        sheet = pd.read_excel(source, sheet_name=sheet_name, header=None,
                              nrows=4000)
        skip_cols = quantity_columns(sheet)
        for r in range(sheet.shape[0]):
            label = norm(sheet.iat[r, 0]).strip().lower()
            if not label or label in SKIP_LABELS:
                continue
            if not CATEGORY_MAP.get(label):
                continue
            dishes = _dishes(sheet, r, skip_cols)
            if dishes:
                out[f"{sheet_name}||{label}"].update(dishes)
    return {k: sorted(v) for k, v in out.items()}


SPEC = ImportSpec(
    client_token=CLIENT_TOKEN,
    city_path=BLR,
    parse=parse_source,
    category_map={f"{s}||{k}": v
                  for s in SHEETS for k, v in CATEGORY_MAP.items()},
    common_at=COMMON_AT,
    clean_name=clean_name,
    refile=refile,
    skip_items=SKIP_ITEMS,
)


def build(frame, raw, spec=SPEC):
    return _build(frame, raw, spec)


def main(dry_run=False):
    return run_import(SPEC, dry_run=dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
