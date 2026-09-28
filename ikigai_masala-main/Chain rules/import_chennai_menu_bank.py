#!/usr/bin/env python3
"""Enrich the Chennai item list from the client's nine-site menu bank.

Source: `data/raw/source_workbooks/chennai_menu_bank_with_colours.xlsx` — one
sheet per site (Wells Fargo, RNTBCI, Accenture, World Bank, LTM, TCL, Gartner,
Toast Tab, Icon) plus a `Colour Legend`. Each row is
``Client | Category | Items | Colour``.

Two things make this file different from the other client menus, and both are
why it is worth importing:

* it names the **food colour of every dish**, with a legend. `item_color` is
  what `MenuSolver._add_color_constraints` reasons about, and a dish with a
  blank colour is invisible to every colour-variety rule — so a day could serve
  five colourless dishes and satisfy nothing. This is the first source that
  supplies colour directly rather than leaving it to be inferred.
* it is a **bank**, not a service grid: no dates, no weekday columns, just what
  each site can serve. So there is nothing to parse positionally.

**Meal combos are skipped.** 41 rows are a whole plate written as one line —
"3 Chapati+Dry Veg+Dal", "Jeera Rice+Paneer Sabji+Dal Fry", "Chapati / Phulka +
Chicken Curry". Imported literally each becomes a single "dish" no kitchen has
an entry for and no rule can reason about, and its components are already in
the file separately. The `Combo` and `Combo / Meals` categories go the same way.

**Categories are a starting point, not the verdict.** Several are genuinely
mixed — `Tiffin / South Indian` holds both dosas (bread) and vadas (starter),
`Main Meal` holds sambar, rasam and white rice, `Other` holds papad and poori.
So a category maps to a *default* course and the dish NAME overrides it through
`course_from_name`, the same principle `refile_lentils` and `refile_rice`
already apply: a printed row says where a dish was served, the name says what it
is.

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
          / "chennai_menu_bank_with_colours.xlsx")
CHENNAI = ROOT / "data" / "raw" / "city_items" / "chennai.xlsx"

from menu_import import (  # noqa: E402  (needs the sys.path line above)
    ImportSpec,
    course_from_name,
    looks_like_a_plate,
    norm,
    run_import,
    to_item,
)
from menu_import import build as _build  # noqa: E402
from menu_import import vocab_from as _vocab_from  # noqa: E402

CLIENT_TOKEN = "Chennai Bank"
COMMON_AT = 6

#: The legend's badge -> the app's `item_color` vocabulary, which is exactly
#: {red, brown, green, yellow, white, orange, black}. "Multi colour / varies"
#: maps to **nothing**: a dish with no single colour genuinely has none, and a
#: blank is excluded from the colour rules rather than counted as a wrong one.
COLOUR_MAP = {
    "white / light yellow": "white",
    "white / yellow": "white",
    "white": "white",
    "light yellow": "yellow",
    "yellow": "yellow",
    "yellow / light brown": "yellow",
    "yellow/brown": "yellow",
    "brown/ yellow": "brown",
    "golden brown": "brown",
    "light brown / golden": "brown",
    "brown": "brown",
    "brown / orange": "brown",
    "green": "green",
    "red / orange": "red",
    "red / orange / brown": "red",
    "dark brown / black": "black",
    # deliberately unmapped -> blank
    "multi colour / varies": "",
    "multi colour": "",
    "varies": "",
    "browm/white/yellow": "",
    "white/brown/red": "",
    "white/red": "",
}

#: Printed category -> the course a dish in it defaults to. The NAME overrides
#: this wherever `course_from_name` recognises the dish.
CATEGORY_MAP = {
    "rice": "rice",
    "variety rice": "rice",
    "special biryani": "rice",
    "biryani": "rice",
    "noodles": "rice",
    "gravy": "veg_gravy",
    "gravy / accompaniment": "veg_gravy",
    "chinese / continental": "veg_gravy",
    "chinese": "veg_gravy",
    "roti / bread": "bread",
    "indian bread": "bread",
    "dosa": "bread",
    "tiffin / south indian": "bread",
    "south indian": "sambar",
    "main meal": "sambar",
    "main meals": "sambar",
    "starter": "starter",
    "live": "starter",
    "snacks": "starter",
    "ready to eat": "bread",
    "sweets / dessert": "dessert",
    "desert": "dessert",
    "dairy / beverage": "welcome_drink",
    "other": "starter",
    "others": "starter",
    "lunch / dinner": "rice",
    "lunch and dinner": "rice",
}

#: Categories that are a whole plate rather than a dish.
SKIP_CATEGORIES = {"combo", "combo / meals"}

#: Rows that name a portion, a choice or a whole meal rather than a dish. A
#: menu bank lists what a site SELLS, so it mixes dishes with the forms they are
#: sold in — "Bajji Varieties", "Masala Vada (2Pcs)", "Any Sundal", "Executive
#: Veg Meal", "Rice and Curry of the Day". None of these names a dish a kitchen
#: can cook or a rule can reason about.
#: NB the boundaries are lookarounds, not `\b`. An underscore is a word
#: character, so `\bmeals?\b` never fires inside `chicken_meal` — the same trap
#: that made every `menu_import.SPELLING` correction inert on multi-word names.
def _w(*words):
    return r"(?<![a-z0-9])(?:" + "|".join(words) + r")(?![a-z0-9])"


SKIP_PATTERNS = (
    r"(?<![a-z0-9])\d+_?(?:pcs?|no_s|nos)(?![a-z0-9])",
    _w("varieties", "variety", "any", "meal", "meals", "combo", "assorted",
       "set", "single", "spl", "special"),
    _w("of_the_day"), _w("extra"), _w("al_cart", "al_carte"),
    # bare category names and non-dishes this bank lists as line items
    r"^(?:corn|green_peas|maggi|poriyal|sprouts_fry|bread)$",
)
_SKIP_RE = re.compile("|".join(SKIP_PATTERNS))

#: Rows the filters cannot classify, adjudicated by hand.
#:
#: `hyderabadi_chicken_biryani_donne_biryani_...` is FOUR biryanis in one cell,
#: a choice offered rather than a dish. `idli_sambar` is a tiffin plate — idli
#: served with sambar — and filed as `sambar` it would be served as the day's
#: sambar. The Jain rows are a dietary preparation of dishes the list already
#: carries.
EXTRA_SKIP_ITEMS = {
    "hyderabadi_chicken_biryani_donne_biryani_ambur_biryani_malabar_biryani",
    "idli_sambar", "jain_mix_veg", "jain_paneer_burji", "chapathi_kurma_combo",
}

#: Chaats the classifier reads as breads, because `puri`/`poori` is a bread
#: tail and these names end in it. A pani puri is not a poori.
COURSE_OVERRIDES = {
    "pani_puri": "starter",
    "pani_poori": "starter",
    "bhel_puri": "starter",
    "sev_potato_puri": "starter",
    "dahi_sev_puri": "starter",
    "sev_potato_papadi": "starter",
    # a dosa style, not a roast meat — the "Gravy" row it was printed in is
    # what sent it to veg_gravy
    "ghee_masala_roast": "bread",
}


#: Portion notes and station names rather than dishes.
SKIP_ITEMS = {
    "sweet", "any_dry_sweet", "any_special_sundal", "any_paneer_gravy_combo",
    "extra_dal", "extra_rice", "extra_curd", "white_rice", "steam_rice",
    "steamed_rice", "curd", "papad", "appalam", "pickle", "sambar", "rasam",
    "bread", "chutney", "malli_chutney", "butter_milk", "buttermilk",
    "any_variety_rice", "any_sundal", "salad", "fryums",
} | EXTRA_SKIP_ITEMS


def vocab_from(frame) -> dict:
    return _vocab_from(frame, CLIENT_TOKEN)


def clean_name(raw: str) -> str:
    return to_item(raw, drop_parentheticals=True)


def refile(item: str, course: str) -> str:
    """Hand adjudication first, then the dish name, then the printed category."""
    if item in COURSE_OVERRIDES:
        return COURSE_OVERRIDES[item]
    return course_from_name(item) or course


def parse_source(source=SOURCE) -> dict:
    """{'<Site>||<category>': [raw dish, …]} across every site sheet."""
    if not source.exists():                                # pragma: no cover
        raise SystemExit(f"missing source workbook: {source}")
    out = defaultdict(set)
    book = pd.ExcelFile(source)
    for sheet_name in book.sheet_names:
        if sheet_name.strip().lower() == "colour legend":
            continue
        d = pd.read_excel(source, sheet_name=sheet_name)
        d.columns = [str(c).strip() for c in d.columns]
        if "Items" not in d.columns:                       # pragma: no cover
            continue
        for _, r in d.iterrows():
            item = norm(r.get("Items"))
            category = norm(r.get("Category")).lower()
            if not item or category in SKIP_CATEGORIES:
                continue
            # A whole plate written as one line is not a dish. This file
            # writes them three ways: with "+", with "with"/"and" joining two
            # courses, and as a named meal or portion.
            if "+" in item:
                continue
            name = clean_name(item)
            if not name or _SKIP_RE.search(name) or looks_like_a_plate(name):
                continue
            out[f"{sheet_name.strip()}||{category}"].add(item)
    return {k: sorted(v) for k, v in out.items()}


def site_index(source=SOURCE) -> dict:
    """{snake_case dish: {site, …}} — which of the nine sites serve each dish.

    The `client` column is what `source_pools` narrows on, so tagging a dish
    with the sites that actually serve it is what makes it reachable. A dish on
    six or more of the nine becomes `common`, the same threshold every other
    import uses.
    """
    if not source.exists():                                # pragma: no cover
        return {}
    out = defaultdict(set)
    book = pd.ExcelFile(source)
    for sheet_name in book.sheet_names:
        if sheet_name.strip().lower() == "colour legend":
            continue
        d = pd.read_excel(source, sheet_name=sheet_name)
        d.columns = [str(c).strip() for c in d.columns]
        if "Items" not in d.columns:                       # pragma: no cover
            continue
        for _, r in d.iterrows():
            item = norm(r.get("Items"))
            if not item or "+" in item:
                continue
            if _SKIP_RE.search(clean_name(item)) or looks_like_a_plate(clean_name(item)):
                continue
            # the sheet's own Client column names the site; fall back to the
            # sheet name, which is the site abbreviation
            site = norm(r.get("Client")) or sheet_name.strip()
            out[clean_name(item)].add(site)
    return dict(out)


def colour_index(source=SOURCE) -> dict:
    """{snake_case dish: item_color} from the file's own colour column."""
    if not source.exists():                                # pragma: no cover
        return {}
    out = {}
    book = pd.ExcelFile(source)
    for sheet_name in book.sheet_names:
        if sheet_name.strip().lower() == "colour legend":
            continue
        d = pd.read_excel(source, sheet_name=sheet_name)
        d.columns = [str(c).strip() for c in d.columns]
        if "Items" not in d.columns or "Colour" not in d.columns:
            continue                                       # pragma: no cover
        for _, r in d.iterrows():
            item = norm(r.get("Items"))
            if not item or "+" in item:
                continue
            colour = COLOUR_MAP.get(norm(r.get("Colour")).lower(), "")
            if colour:
                out.setdefault(clean_name(item), colour)
    return out


SPEC = ImportSpec(
    client_token=CLIENT_TOKEN,
    city_path=CHENNAI,
    parse=parse_source,
    category_map={},          # filled below, once the sheet names are known
    common_at=COMMON_AT,
    clean_name=clean_name,
    refile=refile,
    skip_items=SKIP_ITEMS,
)


def _category_map() -> dict:
    """'<Site>||<category>' -> course, for every site sheet in the workbook."""
    if not SOURCE.exists():                                # pragma: no cover
        return {}
    sheets = [s.strip() for s in pd.ExcelFile(SOURCE).sheet_names
              if s.strip().lower() != "colour legend"]
    return {f"{s}||{cat}": course
            for s in sheets for cat, course in CATEGORY_MAP.items()}


def _ready(spec=SPEC):
    spec.category_map = _category_map()
    spec.client_by_item = site_index()
    spec.colour_by_item = colour_index()
    return spec


def build(frame, raw, spec=SPEC):
    return _build(frame, raw, _ready(spec))


def main(dry_run=False):
    return run_import(_ready(), dry_run=dry_run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
