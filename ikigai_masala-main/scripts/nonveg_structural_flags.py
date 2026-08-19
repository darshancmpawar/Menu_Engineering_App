#!/usr/bin/env python3
"""A non-veg dish with no form flag can never be served — fill them from the name.

`slot_composition`'s `nonveg_main_daily_pair` composes a 2-to-4 slot non-veg
counter as **one `is_nonveg_dry` + one north/south chicken gravy, every day**
(biryani and chinese swap the first component on their theme days). Both cells
of a 2-slot counter are therefore spoken for, so a dish carrying *none* of those
flags cannot be placed at all. It sits in the pool, passes every diagnostic, and
is simply never chosen.

That is invisible until something forces the issue. Stripe's `min: 1` fish rule
did: with `fish_finger` and `tawa_fish_fry` carrying no form flag, requiring one
of them per week left the composition a single cell for two components and the
whole counter went INFEASIBLE — reported as "the rules cannot all be satisfied",
with nothing pointing at the real cause.

The menu imports created 18 such rows by zeroing every `is_*` on a cloned
template, but they are not the whole story: **111 Bangalore rows and 5 NCR rows**
carry no form flag, most of them predating any import. Chennai has none.

What this fills, and on what evidence:

* `biryani` in the name  -> `is_nonveg_biryani` + `is_biryani_item`
* a gravy word (curry, masala, korma, butter, kadai, do pyaza, …)
  -> `is_nonveg_gravy`, plus `is_north_chicken_gravy` / `is_south_chicken_gravy`
     when the dish is chicken, chosen by its `cuisine_family`
* a dry word (dry, fry, roast, sukka, kebab, tikka, 65, tandoori, pepper, …)
  -> `is_nonveg_dry`

Both words present ("chicken tikka masala") reads as gravy: that is the dish's
form, and the dry word is describing how the protein was cooked first.

`STYLE_OVERRIDES` carries the dishes whose NAME says nothing but whose printed
menu row does — Stripe prints "Non-Veg Semi Dry or Dry" and "Non-Veg Curry or
Main Course" as separate rows, so the source is explicit even where the name is
silent. Each entry cites its row.

A row the name cannot classify is **left alone and reported**, not guessed:
`afghani_chicken` and `kolhapuri_chicken` name a place and a protein and nothing
else, and inventing a form for them would put a dish on a plate in the wrong
role. Those need the client's menu to say.

Note `mutton_curry` (NCR's only mutton) gets `is_nonveg_gravy` but no chicken
gravy flag, because it is not chicken — so it still cannot satisfy the pair
composition's gravy component. That is correct, and it means a mutton dish needs
either its own composition or a counter with 5 non-veg slots.

Idempotent; re-run after any re-import. `tests/data/test_nonveg_structural_flags.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CITIES = ("bangalore", "pune", "chennai", "ncr")

from menu_import import nonveg_structural_flags  # noqa: E402

#: Only `nonveg_main` is composed by `nonveg_main_daily_pair`, so only its rows
#: need a dry/gravy/biryani form. A `nonveg_soup` has one form — soup — and
#: giving a shorba `is_nonveg_gravy` would be wrong data for no gain.
COMPOSED_COURSE = "nonveg_main"

#: Every flag that makes a non-veg dish placeable by some composition. A row
#: carrying at least one of these is left alone — this script fills holes, it
#: does not re-adjudicate dishes the ontology already classified.
STRUCTURAL_FLAGS = (
    "is_nonveg_dry", "is_nonveg_gravy", "is_north_chicken_gravy",
    "is_south_chicken_gravy", "is_nonveg_biryani", "is_chinese_chicken_gravy",
    "is_continental_chicken_gravy", "is_continental_chicken_dry",
    "is_semidry_nonveg_main", "is_tandoor_nonveg_dry",
    "is_deep_fried_nonveg_dry", "is_nonveg_starter",
)

#: dish -> the form its PRINTED MENU ROW gives it, where the name is silent.
#: Better evidence than any heuristic; each cites the row it came from.
STYLE_OVERRIDES = {
    # Stripe, "Non-Veg Semi Dry or Dry"
    "boneless_chicken_in_hot_garlic_sauce": "dry",
    "dijon_chicken": "dry",
    # Stripe, "Non-Veg Curry or Main Course"
    "laal_murgh": "gravy",
    "rara_murgh": "gravy",
}


def _has_a_flag(row, cols) -> bool:
    for c in cols:
        try:
            if int(pd.to_numeric([row[c]], errors="coerce")[0] or 0) == 1:
                return True
        except (TypeError, ValueError):            # pragma: no cover
            continue
    return False


def apply(df: pd.DataFrame):
    """Return (df, filled, unresolved). Safe to call twice."""
    df = df.copy()
    cols = [c for c in STRUCTURAL_FLAGS if c in df.columns]
    if not cols:                                    # pragma: no cover
        return df, [], []

    course = df["course_type"].astype(str).str.strip().str.lower()
    filled, unresolved = [], []
    for idx in df.index[course.eq(COMPOSED_COURSE)]:
        row = df.loc[idx]
        if _has_a_flag(row, cols):
            continue
        item = str(row["item"]).strip().lower()
        want = nonveg_structural_flags(
            item,
            str(row.get("primary_protein") or "").strip().lower(),
            str(row.get("cuisine_family") or "").strip().lower(),
            STYLE_OVERRIDES.get(item, ""),
        )
        if not want:
            unresolved.append(item)
            continue
        for c in want:
            if c in df.columns:
                df.at[idx, c] = 1
        filled.append((item, sorted(want)))
    return df, filled, unresolved


def main(dry_run: bool = False):
    total_filled = total_left = 0
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                        # pragma: no cover
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        out, filled, unresolved = apply(df)
        total_filled += len(filled)
        total_left += len(unresolved)
        print(f"[{city}] filled {len(filled)}, "
              f"{len(unresolved)} left for the client to say")
        for item, flags in filled[:6]:
            print(f"    {item:<42} {', '.join(flags)}")
        if len(filled) > 6:
            print(f"    … and {len(filled) - 6} more")
        if unresolved:
            print(f"    ! no form in the name: {sorted(unresolved)[:8]}"
                  f"{' …' if len(unresolved) > 8 else ''}")
        if filled and not dry_run:
            out.to_excel(path, index=False)
            print(f"[{city}] wrote {path.name}")
    print(f"\n{total_filled} dish(es) made placeable; "
          f"{total_left} still need the client's menu to say dry or gravy")
    if dry_run:
        print("[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
