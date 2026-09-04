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
    #: `chuteny` is the word "chutney" misspelled and filed as a STARTER, so a
    #: solve serves it as the day's starter — one did. The typo is why the
    #: category-name check missed it: `chutney` is on Chennai's list above and
    #: this is not that string. Same shape as the `chciken`/`chivken` protein
    #: typos in `misspelled_protein_names.py`, where the misspelling is exactly
    #: what hid the row. Bangalore carries 10 real chutney rows; this is the
    #: category word, not an eleventh dish.
    'bangalore': ['curd_base', 'chuteny'],
    'chennai': [
        'brinjal', 'chutney', 'curd_base', 'darbar_soup', 'dry_sweet',
        'local_salna', 'milk_sweet', 'sweet', 'toast_salad', 'veg_gravy',
    ],
    'pune': [
        'curd_base', 'salad', 'sweet',
        # Found by the client's enrichment pass: a `papad` row with no
        # attributes at all, named for nothing.
        'bobby',
    ],
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
        # ------------------------------------------------------------------
        # A THIRD batch, found by the client's own enrichment pass
        # (`data/raw/source_workbooks/ncr_enriched_final.xlsx`) and adopted
        # after checking each carries the same fingerprint: filed `veg_gravy`
        # or `dal`, no `item_color`, and `key_ingredient` copied from the first
        # word of its own name (`june`, `march`, `stryker`, `pakeeza`).
        # ------------------------------------------------------------------
        # Three more sheet titles, in a different format from the three above.
        'stryker_lunch_08_june_to_13_june', 'stryker_lunch_15_june_to_20_june',
        'stryker_lunch_20_july_to_25_july',
        # Bare month and festival headers.
        'march', 'march_26_april', 'may_week', 'june', 'holi',
        # A client name, a caterer, a site note and an operator note — all
        # servable as the day's gravy.
        'junglee_games', 'pakeeza', 'new_vendor_at_manesar',
        'non_veg_not_serving_due_to_navratri',
        # A whole-meal label rather than a dish, and four name fragments.
        'navratre_thali', 'carrat', 'crisp', 'crisps', 'date',
        # ------------------------------------------------------------------
        # Two more category words, both wearing a disguise the exact-name check
        # could not see through.
        # ------------------------------------------------------------------
        # `samber` is "sambar" misspelled, filed `dal` with
        # `sub_category: leafy_dal` and `key_ingredient: samber` — the mapping
        # pipeline's first-word fingerprint. It is why `add_ncr_sambar.py` says
        # "NCR's raw list carried NO sambar": the list did carry one, under a
        # typo and in the wrong course. NCR now has 14 real sambar rows, so
        # nothing is lost by removing the word.
        'samber',
        # `vegetable` is a bare English noun, which is how it slipped past a
        # list of category names. It is filed `veg_gravy` AND carries
        # `is_premium_gravy`, so a row printed as "Vegetable" was eligible to
        # consume the week's `premium_veg_gravy_exactly_one` slot — the one
        # dish a client is paying for as the week's showcase.
        'vegetable',
        # DELIBERATELY NOT TAKEN from the enriched file: `veg_chowmin` and
        # `veg_avail` are real dishes misspelled (NCR carries `chowmin` and
        # `avial` too), so they were duplicates to adjudicate rather than
        # scaffolding to delete. Now adjudicated, as folds rather than
        # deletions, in `canonical_dish_spellings.DUPLICATES['ncr']` — along
        # with `avail`, the same misspelling without the `veg` qualifier.
    ],
}

# The enriched pass caught these in Bangalore too — the master list had its own
# scaffolding. `sprouts` goes with them: the file carries eight specific sprout
# salads (`green_sprouts`, `boiled_moong_sprouts_salad`, …), so a bare row named
# for the ingredient class is the same case as `veg_dry`.
#
# NOT taken either: `mix_veg`, `mixed_veg` and `sprouts`. The enriched file drops
# all three and they are DISH families, not slot names — the distinction this
# list turns on. A menu printing "Veg Gravy" or "Dessert" tells the diner
# nothing; one printing "Mixed Veg" or "Sprouts" tells them what they are
# getting. Corning Chakan's printed menu settles it: `mix_veg` is the gravy half
# of a "Puri + Mix Veg" cell that `import_corning_pune_menu.py` splits on
# purpose, and `test_corning_pune_import.py` asserts it lands in `veg_gravy`.
#
# NOT taken: the enriched file also drops Chennai's `carrot_raita`, which is a
# real dish — orange, `key_ingredient: carrot`, sitting beside six sibling
# raitas. That one looks like a casualty of their `raitha`/`raita` fold rather
# than a judgement, so it stays.
GENERIC_ROWS.setdefault('bangalore', []).extend([
    'bautra', 'c', 'holi_day', 'luncha', 'nnssww', 'special_lunch',
    'pani_puri_live',
])

# Hyderabad's list was SEEDED from Bangalore's, so Bangalore's scaffolding came
# along with it and has to go for the same reason. Mirrored rather than retyped
# — the same treatment `canonical_dish_spellings.DUPLICATES` gives the seeded
# city, and for the same reason: a verdict written twice can disagree with
# itself. Hyderabad's own entries are kept, so a deliberate divergence is still
# writable. Without this the rows survive only in Hyderabad AND, because
# `tests/cities/test_hyderabad_ontology.py` scopes "what Quest added" to rows
# absent from Bangalore, they read as part of Quest's import.
GENERIC_ROWS['hyderabad'] = sorted(
    set(GENERIC_ROWS.get('hyderabad', [])) | set(GENERIC_ROWS['bangalore']))


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
