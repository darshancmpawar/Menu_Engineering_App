#!/usr/bin/env python3
"""Import Stryker Bangalore's lunch menus into the Bangalore ontology.

Source: `data/raw/source_workbooks/stryker_blr_lunch_menus.xlsx` — seven weekly
sheets, each a buffet grid with the category in column 0 and one column per
weekday. The shared three-pass machinery (language -> similar items -> unique)
lives in `menu_import.py`; what is here is Stryker's grid and its label map.

**Only the buffet grid is imported.** Every sheet carries a second block below
it — "The Combo Spot" / "Buffet Grids ( Veg Mini Meal)" — which re-serves that
same week's buffet dishes as mini-meal combinations. It adds no dish the buffet
does not already have, and its rows are unlabelled continuations that would
otherwise be filed under whatever label sat above them.

Skipped rows, and why: `Rice` is white rice (a CONST slot), `PAPAPD/PICKLE` is
the fixed condiment station, and `Compond Salad/ Cut Fruit` mixes real salads
with "Cut Fruit" and "Whole Fruit Banana" — a fruit station rather than a
category, and its genuine salads also appear in the `SALAD` row.

`Spl item` is imported as `starter`, which is what most of it is (veg cutlet,
babycorn dry, gobi manchurian). It also runs the occasional egg dish, and the
shared builder re-files any dish whose NAME declares an animal protein into
`nonveg_main` rather than leaving it in a veg pool where `_nonveg_mask` would
make it unservable.

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
          / "stryker_blr_lunch_menus.xlsx")
BLR = ROOT / "data" / "raw" / "city_items" / "bangalore.xlsx"

from menu_import import (  # noqa: E402  (needs the sys.path line above)
    ImportSpec,
    norm,
    run_import,
    to_item,
)
from menu_import import build as _build  # noqa: E402
from menu_import import vocab_from as _vocab_from  # noqa: E402

CLIENT_TOKEN = "Stryker"
COMMON_AT = 6

#: Everything from this row down is the mini-meal repackaging, not new dishes.
STOP_AT = ("the combo spot", "buffet grids ( veg mini meal)",
           "buffet grids (veg mini meal)")

DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday"}

#: Printed label (lower-cased, trimmed) -> the app's course_type.
CATEGORY_MAP = {
    "welcome drink": "welcome_drink",
    "indian bread": "bread",
    "flavour rice": "rice",
    "dal": "dal",
    "sambar": "sambar",
    "rasam": "rasam",
    "veg dry": "veg_dry",
    "veg gravy": "veg_gravy",
    "curd/raitha": "curd_side",
    "salad": "salad",
    "desert": "dessert",
    "non veg": "nonveg_main",
    "spl item": "starter",
}

#: Rows that are a heading, a fixed condiment, or a station rather than a
#: category. `rice` here is the white-rice CONST slot, not flavoured rice.
SKIP_LABELS = {"buffet grids", "rice", "papapd/pickle", "papad/pickle",
               "compond salad/ cut fruit", "compound salad/ cut fruit"}

#: Dishes that are a station, a condiment, an allergen note or a bare category.
#: `mosaru` is curd in Kannada; `eggs`/`egg` alone name a protein, not a dish.
SKIP_ITEMS = {"white_rice", "steamed_rice", "curd", "plain_curd", "mosaru",
              "papad", "fryms", "fryums", "cut_fruit", "whole_fruit_banana",
              "diy_salad", "counter", "golgappa_counter", "salad",
              "gluten", "dairy", "daiyr", "nuts", "soya", "egg", "eggs",
              "gluten_dairy", "dairy_nuts", "daiyr_nuts", "aop_pasta_salad",
              "watermelon_cut_fruit", "pop", "mouth_freshner",
              "papad_pickle_and_mouth_freshner", "assorted_papad"}


#: Dishes the SOURCE files under two different categories, because one of the
#: stacked grids in `Jun 29 To Jul03` is shifted by a row for some days. Where a
#: dish lands in two courses, `COURSE_PRIORITY` picks one, and for these it
#: picks the wrong one — so the dish name decides instead. Each is a judgement
#: about what the dish IS, not about which row it was printed on.
COURSE_OVERRIDES = {
    "mavinakayi_chitharana": "rice",       # mango chitranna is a rice
    "bella_panaka": "welcome_drink",       # jaggery-lemon drink
}


def vocab_from(frame) -> dict:
    return _vocab_from(frame, CLIENT_TOKEN)


def refile(item: str, course: str) -> str:
    """Name-based filing for the lentil family, then the explicit overrides."""
    from menu_import import refile_lentils

    return COURSE_OVERRIDES.get(item, refile_lentils(item, course))


#: A "Live Counter- Jhal Muri" is jhal muri, cooked in front of you. The prefix
#: is the station, not part of the dish.
_LIVE_PREFIX = re.compile(
    r"^\s*live\s*(?:counter|preparation|station)?\s*[-:–]?\s*", re.I)

#: The nutrition block `July20 to July24` carries between its day columns. The
#: numbers are filtered as numeric, but `allergen` holds TEXT — "gluten",
#: "dairy", "soya", "daiyr,nuts" — which imported as six dishes.
_NUTRITION_HEADERS = {"kcal", "pro", "fat", "carb", "carbs", "fiber", "fibre",
                      "allergen", "allergens", "kg/pcs", "qty"}

#: No dish name is this long. `Aug10th to Aug14th` carries a second grid to the
#: right whose row 0 is "Stryker -Blr Independence Day Special Lunch Menu…".
MAX_NAME_CHARS = 60


def clean_name(raw: str) -> str:
    """Stryker writes "dish / what it is served with" — keep the dish.

    "Veg Cutlet /Green Chutney", "Baby Corn Chilli Dry/Hot Garlic Tmt Sauce".
    Taken whole these become one very long dish name; split in two they add a
    chutney and a sauce as if they were menu items. The part before the slash
    is the dish, and a live-counter prefix is the station rather than the dish.
    """
    text = _LIVE_PREFIX.sub("", str(raw).split("/")[0])
    # "Babycorn Dry with Manchurian Gravy Sauce" is a babycorn dry served with
    # a sauce; the sauce is not part of the dish's name.
    text = re.split(r"\s+wi?th\s+", text, maxsplit=1, flags=re.I)[0]
    return to_item(text, drop_parentheticals=True)


def _nutrition_columns(sheet) -> set:
    """Columns holding kcal / protein / allergen rather than a dish."""
    cols = set()
    for r in range(min(8, sheet.shape[0])):
        row = [norm(sheet.iat[r, c]).strip().lower()
               for c in range(sheet.shape[1])]
        if sum(1 for v in row if v in _NUTRITION_HEADERS) >= 3:
            cols |= {c for c, v in enumerate(row) if v in _NUTRITION_HEADERS}
    return cols


def _label_columns(sheet, labels) -> list:
    """Columns that hold this menu's category names.

    Usually just column 0, but `Aug10th to Aug14th` carries a SECOND grid to the
    right (an Independence Day special) with its own label column. Reading that
    grid's dishes under the MAIN grid's row labels put an Amritsari veg dry into
    `rasam`; reading its labels as dishes added "Indian Bread" and "Spl item" as
    menu items.
    """
    cols = []
    for c in range(sheet.shape[1]):
        hits = sum(1 for r in range(sheet.shape[0])
                   if norm(sheet.iat[r, c]).strip().lower() in labels)
        if hits >= 3:
            cols.append(c)
    return cols or [0]


def _dishes(sheet, r, lo, hi, skip_cols, labels) -> list:
    """Dish cells in row *r*, between label column *lo* and the next one."""
    out = []
    for c in range(lo + 1, hi):
        if c in skip_cols:
            continue
        dish = norm(sheet.iat[r, c])
        low = dish.strip().lower()
        if (not dish or low in DAYS or low in labels
                or len(dish) > MAX_NAME_CHARS
                or re.match(r"^\d{4}-\d{2}-\d{2}", dish)
                or re.fullmatch(r"[\d.]+", low)):
            continue
        out.append(dish)
    return out


def parse_source(source=SOURCE) -> dict:
    """{'Lunch||<Label>': [raw dish, …]} across every weekly sheet.

    Two sheets are not the plain grid the rest are, and both were adding junk:

    * `July20 to July24` interleaves a nutrition block (kcal / protein / fat /
      carb / fiber / **allergen**) between the day columns. The numbers filter
      out as numeric, but the allergen cells are words — "gluten", "dairy",
      "soya", "daiyr,nuts" — and imported as six dishes.
    * `Aug10th to Aug14th` carries a SECOND grid to the right (an Independence
      Day special) with its own label column, so "Indian Bread", "Flavour rice",
      "VEG DRY", "Spl item" were read as dish names and filed into whatever
      category claimed them first.

    So nutrition columns are located by their header and skipped, and any cell
    whose text is one of this menu's own category labels is a label, not a dish.
    """
    if not source.exists():                                # pragma: no cover
        raise SystemExit(f"missing source workbook: {source}")
    labels = set(CATEGORY_MAP) | SKIP_LABELS
    out = defaultdict(set)
    book = pd.ExcelFile(source)
    for sheet_name in book.sheet_names:
        sheet = pd.read_excel(source, sheet_name=sheet_name, header=None)
        skip_cols = _nutrition_columns(sheet)
        label_cols = _label_columns(sheet, labels)
        stopped = set()
        carried = {}
        for r in range(sheet.shape[0]):
            # Which label columns are ACTING as one on this row. A column that
            # holds a dish here is not a label column here, whatever it does
            # elsewhere on the sheet.
            active = []
            for lo in label_cols:
                if lo in stopped:
                    continue
                low = norm(sheet.iat[r, lo]).strip().lower()
                if any(low.startswith(s) for s in STOP_AT):
                    stopped.add(lo)
                    carried.pop(lo, None)
                    continue
                if low in labels:
                    carried[lo] = low
                    active.append(lo)
                elif not low and lo in carried:
                    active.append(lo)       # blank cell continues the label
                else:
                    carried.pop(lo, None)   # this column holds a dish here
            for i, lo in enumerate(active):
                hi = active[i + 1] if i + 1 < len(active) else sheet.shape[1]
                label = carried.get(lo)
                if not label or label in SKIP_LABELS:
                    continue
                if not CATEGORY_MAP.get(label):
                    continue
                dishes = _dishes(sheet, r, lo, hi, skip_cols, labels)
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
    refile=refile,
    skip_items=SKIP_ITEMS,
    split_combos=True,           # "Veg Cutlet /Green Chutney", "Puri + Chapti"
    style_by_label={"Lunch||non veg": ""},   # one row, both forms — use the name
)


def build(frame, raw, spec=SPEC):
    return _build(frame, raw, spec)


def main(dry_run=False):
    return run_import(SPEC, dry_run=dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
