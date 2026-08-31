#!/usr/bin/env python3
"""Remove rows whose name does not identify a dish.

Rows in the Chennai, Pune and NCR lists are named for a *category*, not a dish:
`sweet`, `veg_gravy`, `salad`, `soup`-shaped placeholders. A menu that prints
"Sweet" tells the diner nothing, and — worse for the engine — nothing can be
reasoned about a dish it cannot identify: no colour rule, no ingredient ban, no
variety check applies to a row literally named `veg_gravy` sitting in the
veg-gravy category.

The client reviewed these (D3 in ``docs/data_fixes_for_client.md``) and chose
removal over renaming. Two of them — `dry_sweet` and `sweet` — appear on
ToastTab's real sample menu, so those sample rows become unreproducible until the
client supplies the actual dish names; that trade was made deliberately.

NCR arrived with ten such bare labels (`dal`, `rice`, `sambar`, `rasam`, …),
including the *only* `rasam` and `sambar` rows — so removing them cleanly means
NCR carries no rasam/sambar station, which its North Indian menu never runs.
`curd`, `papad` and `pickle` are deliberately KEPT: each is a single fixed thali
condiment/staple printed as-is (there is no sibling `mango_pickle` making the
bare name ambiguous), exactly like Bangalore's stamped "Papad".

None of the removals starve a required slot: every affected pool keeps 26-50 rows
(the smallest, Chennai `chutney`, is an optional station and drops 4 -> 3). The
check is worth re-running if the lists change — a removal that empties a required
slot would turn `PoolBuilder.build_pools` into a hard ValueError.

Idempotent and committed for the same reason as the other correction scripts:
re-importing a workbook through the normaliser brings the rows back, so re-run this
afterwards. ``tests/test_generic_rows.py`` fails if any of them reappear.

Usage:
    python scripts/remove_generic_rows.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename.

    `to_excel` truncates the target before streaming into it, so an
    interrupted run leaves a 0-byte workbook and the city's item list is
    gone. That happened once; it must not happen twice.
    """
    import pathlib as _pl
    p = _pl.Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CITY_ITEMS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'raw', 'city_items')

#: ``city -> [item names]``. Names are matched exactly (stripped), never as
#: substrings, so removing `sweet` cannot take `dry_sweet` with it.
#: `curd_base` is the recipe base a raita is built FROM, not a dish — the client
#: confirmed it. It sits in `curd_side` in three cities with `sub_category: curd`
#: and `key_ingredient: yogurt`, so it looks servable to every diagnostic while
#: a menu printing "Curd Base" as the day's yogurt side says nothing. Same
#: argument as the category-named rows below, arriving by a different route: the
#: name describes a component of a dish rather than the dish.
GENERIC_ROWS = {
    'bangalore': ['curd_base'],
    'chennai': [
        'brinjal', 'chutney', 'curd_base', 'darbar_soup', 'dry_sweet',
        'local_salna', 'milk_sweet', 'sweet', 'toast_salad', 'veg_gravy',
    ],
    'pune': ['curd_base', 'salad', 'sweet'],
    'ncr': [
        'chutney', 'dal', 'dessert', 'gravy', 'raita', 'rasam', 'rice',
        'salad', 'sambar', 'veg_dry',
        # ------------------------------------------------------------------
        # Not dishes at all: the NCR mapping pipeline imported the SPREADSHEET
        # SCAFFOLDING as menu items. Every one of these is filed `veg_gravy`
        # with `key_ingredient` copied from the first word of its own name (the
        # pipeline's fingerprint — see ncr_bread_misfiles.py), so all of them
        # were servable, and a menu could print "Fri 19th June" as the day's
        # vegetable gravy. None has a colour, which is how they surfaced.
        # ------------------------------------------------------------------
        # 26 weekday-date column headers.
        'mon_1st_june', 'tue_2nd_june', 'wed_3rd_june', 'thu_4th_june',
        'fri_5th_june', 'mon_8th_june', 'tue_9th_june', 'wed_10th_june',
        'thu_11th_june', 'fri_12th_june', 'mon_15th_june', 'tue_16th_june',
        'wed_17th_june', 'thu_18th_june', 'fri_19th_june', 'mon_22nd_june',
        'tue_23rd_june', 'wed_24th_june', 'thu_25th_june', 'fri_26th_june',
        'mon_29th_june', 'tue_30th_june', 'wed_1st_july', 'thu_2nd_july',
        'fri_3rd_july',
        # Three sheet titles.
        'stryker_lunch_18_may_to_23_may', 'stryker_lunch_27_july_to_01_aug',
        'stryker_lunch_29th_june_to_4th_july',
        # A note to the operator, imported verbatim as a dish.
        'from_1st_aug_2026_new_vendor_at_bhondsi_is_gourmer_foods',
        # Single-word header fragments: weekday and month abbreviations, a
        # head-count column, and the veg / non-veg section labels. NB `pav` and
        # `pao` are three letters too and are REAL dishes — this list is exact
        # names, never a length rule.
        'apr', 'day', 'eid', 'may', 'mon', 'pax', 'tue', 'wed',
        'veg', 'non_veg',
        # ------------------------------------------------------------------
        # A SECOND sheet's scaffolding, missed the first time because its
        # headers are spelled out in full (`monday_3rd`) where the ones above
        # are abbreviated with a month (`mon_1st_june`), so neither an exact
        # name nor a shared prefix caught both. Same fingerprint, verified row
        # by row: every one is filed `veg_gravy`, carries no `item_color`, and
        # has `key_ingredient` copied from a word of its own name — `days`,
        # `week`, `plates`, `beverage`, `star`, `styker`.
        # ------------------------------------------------------------------
        # Five weekday column headers and two range labels.
        'monday_3rd', 'tuesday_4th', 'wednesday_5th', 'thursday_6th',
        'friday_7th', 'days', 'week',
        # A head-count cell and the beverage section label, singular and plural.
        '5_plates', 'beverage', 'beverages',
        # TWO VENDOR NAMES. `styker_x_gourmer_services` is the same sheet title
        # family as the three above (Stryker misspelled); `d_star_hospitality`
        # is the caterer. Both were servable as the day's vegetable gravy, so a
        # printed menu could have offered "D Star Hospitality" for lunch.
        'd_star_hospitality', 'styker_x_gourmer_services',
    ],
}


def apply_removals(df: pd.DataFrame, city: str):
    """Return ``(df, removed)`` for one city. Pure, so tests can call it."""
    df = df.copy()
    nm = df['item'].astype(str).str.strip()
    targets = set(GENERIC_ROWS.get(city, []))
    mask = nm.isin(targets)
    removed = sorted(nm[mask].tolist())
    return df[~mask].reset_index(drop=True), removed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    total = 0
    for city in sorted(GENERIC_ROWS):
        path = os.path.join(CITY_ITEMS, f'{city}.xlsx')
        if not os.path.exists(path):
            print(f'{city}: no workbook at {path}', file=sys.stderr)
            continue
        before = pd.read_excel(path)
        after, removed = apply_removals(before, city)
        if not removed:
            print(f'{city}: already clean')
            continue
        print(f'{city}: removing {len(removed)} row(s): {removed}')
        total += len(removed)
        if not args.dry_run:
            _atomic_to_excel(after, path, index=False)

    if args.dry_run:
        print('\nnothing written (--dry-run)')
    elif total:
        print(f'\nremoved {total} row(s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
