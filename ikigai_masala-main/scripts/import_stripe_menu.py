#!/usr/bin/env python3
"""Import Stripe's two sample menus into the Bangalore ontology.

Sources: `data/raw/source_workbooks/stripe_menu_2026_06_29.xlsx` and
`stripe_menu_2026_07_27.xlsx` — one printed week each, three sheets (breakfast,
Lunch, Dinner). The shared three-pass machinery (language -> similar items ->
unique) lives in `menu_import.py`; what is here is Stripe's own grid and its
label -> slot map.

**Only the plated meals are imported**, which is what the tool plans:

* the LUNCH block (the top of the Lunch sheet, above `SALAD BAR`);
* the `Dinner Menu` block (the bottom of the Dinner sheet, below the DIY
  sandwich station);
* from the SALAD BAR block, only `Veg Soup` and `Beverage` — the two rows that
  are real solver slots (`soup`, `welcome_drink`) rather than components a
  diner assembles.

Skipped by design, because no solver slot corresponds to them: the salad-bar
components (raw vegetables, cooked vegetables, pulses/grains, veg protein,
toppings, dressings, breads), the `DIY SANDWICH` station, `Steamed Rice` and the
condiment/accompaniment rows (fixed condiments the app pins as CONST_SLOTS),
and the breakfast sheet.

**A defect in the July workbook is detected, not assumed.** In that file the
salad-bar block lost a row, so from `SALAD BAR` down every label sits one row
above its dishes: the row labelled `Veg Soup` holds beverages and `Beverage`
holds garlic bread. Importing by label would file five juices as soups. So
`parse_source` runs an alignment check on that block — the `Veg Soup` row must
actually contain a soup, the `Beverage` row a drink — and if it fails, retries
with the labels shifted one row and re-checks. A block that passes neither is
skipped with a warning rather than imported wrong. June passes as-is; July
passes after the shift.

Dish names carry parenthesised asides — "Chicken tikka Masala(Boneless)",
"Mysore Rasam (Karnataka)", "Soya veg Cutlet(tasting)" — that describe how a
dish is served rather than name it, so `clean_name` drops them; keeping them
would produce a near-duplicate of the same dish written plainly.

Stripe's menu carries **no mutton**, so the mutton rule its logic would want
stays unconfigured — see `docs/client_logics.md`. It does carry two fish dishes
(`Fish Finger`, `Tawa fish fry`), which is thin: under the 20-day item cooldown
two dishes support fish roughly every other week, not weekly.

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
SOURCE_DIR = ROOT / "data" / "raw" / "source_workbooks"
SOURCES = (SOURCE_DIR / "stripe_menu_2026_06_29.xlsx",
           SOURCE_DIR / "stripe_menu_2026_07_27.xlsx")
BLR = ROOT / "data" / "raw" / "city_items" / "bangalore.xlsx"

from menu_import import (  # noqa: E402  (needs the sys.path line above)
    ImportSpec,
    norm,
    run_import,
    to_item,
)
from menu_import import build as _build  # noqa: E402
from menu_import import vocab_from as _vocab_from  # noqa: E402

CLIENT_TOKEN = "Stripe"
COMMON_AT = 6          # >= this many clients make it -> `common`

#: A row in column 0 that opens a block rather than labelling dishes.
BLOCK_HEADERS = {
    "lunch": "Lunch",
    "salad bar": "Salad Bar",
    "diy sandwich": "Sandwich",
    "dinner menu": "Dinner",
}

#: Rows that are a block's own heading or its day/date strip, never a dish label.
HEADER_LABELS = {"menu pattern", "menu spread", "snacks - sandwich",
                 "dinner menu", "lunch", "salad bar", "diy sandwich"}

DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday"}

#: '<Block>||<Label>' -> the app's course_type. A label absent here is skipped,
#: so this map doubles as the list of rows worth importing.
CATEGORY_MAP = {
    # --- plated lunch -------------------------------------------------------
    "Lunch||Salad": "salad",
    "Lunch||Indian Breads (Live)": "bread",
    # The label reads "Starter OR Subzi" and the station is Stripe's live
    # counter, so it is filed as `starter` — the same call the Booking import's
    # `Live` row got. The dinner sheet has its own explicit `Veg dry` row.
    "Lunch||Veg Starter OR Subzi": "starter",
    "Lunch||Gravy Veg": "veg_gravy",
    "Lunch||Flavoured Rice": "rice",
    "Lunch||North Indian Lentile": "dal",
    "Lunch||South Indian Lentile": "sambar",
    "Lunch||Indian Rasam or Soup": "rasam",
    "Lunch||Curd": "curd_side",
    "Lunch||Non-Veg Semi Dry or Dry": "nonveg_main",
    "Lunch||Non-Veg Curry or Main Course": "nonveg_main",
    "Lunch||Dessert": "dessert",
    # --- the two salad-bar rows that are real slots -------------------------
    "Salad Bar||Veg Soup": "soup",
    "Salad Bar||Beverage": "welcome_drink",
    # --- plated dinner ------------------------------------------------------
    "Dinner||Salad": "salad",
    "Dinner||Indian Bread": "bread",
    "Dinner||Veg dry": "veg_dry",
    "Dinner||Veg Gravy": "veg_gravy",
    "Dinner||Lentil": "dal",
    "Dinner||Flavoured Rice": "rice",
    "Dinner||Curd": "curd_side",
    "Dinner||Sweet tooth": "dessert",
    "Dinner||Non Veg": "nonveg_main",
}

#: Fixed condiments the app pins as CONST_SLOTS, plus the unlabelled rows that
#: continue them. Listed so the run prints nothing about them.
SKIP_LABELS = {"Steamed Rice", "Accompaniments", "Condiment Station"}

#: Stripe prints its two non-veg rows as "Semi Dry or Dry" and "Curry or Main
#: Course", which is the menu telling us how each dish is served — better
#: evidence than any name heuristic, and load-bearing: a non-veg dish carrying
#: neither `is_nonveg_dry` nor a chicken-gravy flag cannot be placed by
#: `nonveg_main_daily_pair` on a 2-4 slot counter at all.
STYLE_BY_LABEL = {
    "Lunch||Non-Veg Semi Dry or Dry": "dry",
    "Lunch||Non-Veg Curry or Main Course": "gravy",
    "Dinner||Non Veg": "gravy",
}

#: The alignment check for the salad-bar block: each label must actually carry
#: what it names. `word in name` rather than a token match — "dhaniya_shorba"
#: and "tom_yum" are soups without the word "soup" in them.
ALIGNMENT_PROBE = {
    "Veg Soup": ("soup", "shorba", "rasam", "broth", "yum"),
    "Beverage": ("juice", "sharbat", "sharbath", "mojito", "lime", "punch",
                 "butter_milk", "buttermilk", "thandai", "lassi", "cooler",
                 "smoothie", "shake"),
}


def clean_name(raw: str) -> str:
    """Stripe writes "Masala(Boneless)" and "Rasam (Karnataka)" — drop the aside."""
    return to_item(raw, drop_parentheticals=True)


def vocab_from(frame) -> dict:
    """Token frequency of the Bangalore names that predate this import."""
    return _vocab_from(frame, CLIENT_TOKEN)


_WEEKDAY_START = re.compile(r"^(" + "|".join(sorted(DAYS)) + r")\b")


def _is_day_strip(values) -> bool:
    """A row of day headings, not dishes.

    Written as bare weekdays on some sheets and as the day's theme on others —
    "Monday ( Rajasthan)", "Tuesday - continental", "Thursday-chinese". Left in,
    those five strings import as five dishes; the LUNCH salad row sits directly
    under this strip, so they landed in `salad`.
    """
    named = [v for v in values if v]
    return len(named) >= 3 and all(_WEEKDAY_START.match(v.lower())
                                   for v in named)


def _dishes(row_values) -> list:
    """The real dish names in one grid row, or [] if the row is a day strip."""
    out = []
    for v in row_values:
        dish = norm(v)
        low = dish.lower()
        if (not dish or low in DAYS
                or re.match(r"^\d{4}-\d{2}-\d{2}", dish)
                or re.fullmatch(r"[\d.]+", low)):
            continue
        out.append(dish)
    return [] if _is_day_strip(out) else out


def _block_rows(sheet: pd.DataFrame):
    """{block: [(label|None, [dish, …]), …]} for one sheet, in row order.

    Every row carrying dishes is kept, INCLUDING one whose column-0 text is a
    block heading rather than a label — in the July workbook the salad bar's
    dishes sit one row above their labels, so the soups land on the row
    labelled "Menu Pattern". Dropping header rows here would delete them before
    the re-pairing below could reach them.

    An unlabelled row continues the label above it, which is how the printed
    grid writes a multi-line category.
    """
    out, block, label = defaultdict(list), None, None
    for r in range(sheet.shape[0]):
        raw_label = norm(sheet.iat[r, 0])
        low = raw_label.lower()
        dishes = _dishes(sheet.iat[r, c] for c in range(1, sheet.shape[1]))
        if low in BLOCK_HEADERS:
            block, label = BLOCK_HEADERS[low], None
        elif low in HEADER_LABELS:
            label = None
        elif raw_label:
            label = raw_label
        if block is None:
            continue
        if label is None and block == "Lunch" and dishes and not out[block]:
            label = "Salad"          # the unlabelled plated-salad row
        if dishes:
            out[block].append((label, dishes))
    return out


def _aligned(pairs) -> bool:
    """Does every probe-able label in this block actually carry what it names?"""
    seen = 0
    for label, dishes in pairs:
        probes = ALIGNMENT_PROBE.get(label)
        if not probes:
            continue
        seen += 1
        names = [to_item(d) for d in dishes]
        if not any(p in n for n in names for p in probes):
            return False
    return seen > 0


def _shift_labels(pairs):
    """Pair each row's dishes with the label on the row BELOW (the July defect)."""
    return [(pairs[i + 1][0], dishes)
            for i, (_label, dishes) in enumerate(pairs[:-1])]


def parse_source(sources=SOURCES, verbose: bool = True) -> dict:
    """{'<Block>||<Label>': [raw dish, …]} across both weeks."""
    out = defaultdict(set)
    for path in sources:
        if not path.exists():                              # pragma: no cover
            raise SystemExit(f"missing source workbook: {path}")
        for sheet_name in ("Lunch", "Dinner"):
            sheet = pd.read_excel(path, sheet_name=sheet_name, header=None)
            for block, pairs in _block_rows(sheet).items():
                if block == "Salad Bar":
                    # The only block that has ever been misaligned, and the only
                    # one with probe-able labels. Verify before trusting it.
                    if not _aligned(pairs):
                        shifted = _shift_labels(pairs)
                        if _aligned(shifted):
                            if verbose:
                                print(f"  ! {path.name}/{sheet_name}: salad-bar "
                                      f"dishes sit one row above their labels — "
                                      f"re-paired")
                            pairs = shifted
                        else:
                            if verbose:
                                print(f"  ! {path.name}/{sheet_name}: salad-bar "
                                      f"block does not line up — skipped")
                            continue
                for label, dishes in pairs:
                    if not label or label in SKIP_LABELS:
                        continue
                    out[f"{block}||{label}"].update(dishes)
    return {k: sorted(v) for k, v in out.items()}


SPEC = ImportSpec(
    client_token=CLIENT_TOKEN,
    city_path=BLR,
    parse=parse_source,
    category_map=CATEGORY_MAP,
    skip_labels=SKIP_LABELS,
    common_at=COMMON_AT,
    clean_name=clean_name,
    style_by_label=STYLE_BY_LABEL,
)


def build(frame, raw, spec=SPEC):
    """Stripe's rows out of the shared builder (see `menu_import.build`)."""
    return _build(frame, raw, spec)


def main(dry_run=False):
    return run_import(SPEC, dry_run=dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
