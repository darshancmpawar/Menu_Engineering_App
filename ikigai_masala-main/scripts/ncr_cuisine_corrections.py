#!/usr/bin/env python3
"""NCR dishes the mapping pipeline mislabeled `cuisine_family = continental`.

The NCR workbook came from a mapping pipeline that over-applied `continental` to
plainly Indian savoury dishes. It matters because `ThemeSlotFilterRule` enforces
*cuisine exclusivity* on the cuisine-main slots (rice / veg_gravy / veg_dry /
starter / nonveg_main): a continental dish appears ONLY on a continental day. No
NCR client runs a continental day, so every such row is silently **unservable**:

  * `nonveg_main` — 17 chicken curries (`butter_chicken`, `chicken_rogan_josh`,
    `chicken_lababdar`, `chicken_changezi`, …). Each already carries
    `sub_category = chicken_north_masala`/`chicken_north_creamy`, so the row
    contradicts itself — the sub_category says North, cuisine_family says
    continental. North wins.
  * `starter` — 7 Indian chaat / pakora / bajji / vada items (`samosa_chaat`,
    `kachori`, `aloo_bajji`, …). On a north day the filter dropped all but the
    one `north_indian` starter (`dhokla`), starving a themed starter slot (Airtel
    Plot 5's counter went INFEASIBLE on it).

So for those two slots the fix is unambiguous: `continental` → `north_indian`.

NOT touched, because their continental tag is correct: `veg_dry`
(`caramelized_onion`, `stirfried_vegetable` — genuinely western), `soup`
(sweet corn / cream soups), the western-bakery `dessert` rows (already set by
`dessert_cuisine_corrections.py`), and `salad` (a non-theme-filtered slot, so the
tag never reaches the solver).

Idempotent and committed like the other correction scripts: re-importing the raw
workbook through the normaliser drops the edit, so re-run this afterwards.
`tests/test_ncr_cuisine.py` fails if the misfiles reappear.

Usage:
    python scripts/ncr_cuisine_corrections.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

CITY_ITEMS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'raw', 'city_items')

CITY = 'ncr'

#: The cuisine-main slots whose `continental` tag was over-applied to Indian
#: dishes. Scoped tightly — NCR's nonveg_main is entirely chicken_north_* and its
#: starters are entirely Indian chaat/pakora, so there is no genuine continental
#: dish in either slot to catch by mistake.
FIX_SLOTS = ('nonveg_main', 'starter')
FROM_CUISINE = 'continental'
TO_CUISINE = 'north_indian'


def apply_corrections(df: pd.DataFrame):
    """Return ``(df, changed_items)``. Pure, so tests can call it."""
    df = df.copy()
    course = df['course_type'].astype(str).str.strip()
    cuisine = df['cuisine_family'].astype(str).str.strip().str.lower()
    mask = course.isin(FIX_SLOTS) & (cuisine == FROM_CUISINE)
    changed = sorted(df.loc[mask, 'item'].astype(str))
    df.loc[mask, 'cuisine_family'] = TO_CUISINE
    return df, changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    path = os.path.join(CITY_ITEMS, f'{CITY}.xlsx')
    if not os.path.exists(path):
        print(f'{CITY}: no workbook at {path}', file=sys.stderr)
        return 1
    before = pd.read_excel(path)
    after, changed = apply_corrections(before)
    if not changed:
        print(f'{CITY}: already correct')
        return 0
    print(f'{CITY}: {len(changed)} row(s) continental -> {TO_CUISINE}')
    for item in changed:
        print(f'  {item}')
    if not args.dry_run:
        after.to_excel(path, index=False)
        print(f'\nrewrote {len(changed)} row(s)')
    else:
        print('\nnothing written (--dry-run)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
