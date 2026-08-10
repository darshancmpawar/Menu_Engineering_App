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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CITY_ITEMS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'raw', 'city_items')

#: ``city -> [item names]``. Names are matched exactly (stripped), never as
#: substrings, so removing `sweet` cannot take `dry_sweet` with it.
GENERIC_ROWS = {
    'chennai': [
        'brinjal', 'chutney', 'darbar_soup', 'dry_sweet', 'local_salna',
        'milk_sweet', 'sweet', 'toast_salad', 'veg_gravy',
    ],
    'pune': ['salad', 'sweet'],
    'ncr': [
        'chutney', 'dal', 'dessert', 'gravy', 'raita', 'rasam', 'rice',
        'salad', 'sambar', 'veg_dry',
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
            after.to_excel(path, index=False)

    if args.dry_run:
        print('\nnothing written (--dry-run)')
    elif total:
        print(f'\nremoved {total} row(s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
