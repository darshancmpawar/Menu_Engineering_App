#!/usr/bin/env python3
"""Give each dessert its real regional origin in `cuisine_family`.

The imports defaulted almost every dessert to `north_indian`: 221 of Bangalore's
249, 28 of Chennai's 32, 43 of Pune's 45. That is wrong for a large, identifiable
group — every *payasam* and *kesari* is South Indian, not North — and it is a
landmine (D1 in ``docs/data_fixes_for_client.md``). `cuisine_family` feeds the
theme filter; desserts are theme-*exempt* today, so nothing is broken right now,
but the moment anyone themes desserts a South Indian day's dessert pool collapses
from dozens of dishes to a handful, and a week with three south days goes
infeasible. Cheap to fix now, expensive to diagnose later.

## What this corrects, and what it deliberately does not

Two groups are reassigned by dish family, matched on whole name tokens (scoped to
rows whose `course_type` is `dessert`, so a savoury dish sharing a token is never
touched):

  * **South Indian** — the payasam / payasa family, rava *kesari*, *mysore pak*,
    *holige* / *obbattu*, sweet *pongal*, *badusha*, *adhirasam*, *ada pradhaman*,
    *paramannam*, and the Kannada/Tamil/Telugu names (ellu-bella, karjikai,
    sunnundalu, sukhinunde, halbai, surkumba, kakinada khaja).
  * **Continental** — western bakery: cake, brownie, muffin, cupcake, custard,
    pudding, tiramisu, ice cream. `milk_cake` and `ajmeri_milk_cake` are excluded
    by name — those are Indian *mawa* sweets that merely carry the word "cake".

Everything else keeps its existing value. That leaves two regional groups in
`north_indian` **on purpose**, because the `cuisine_family` vocabulary is
`{north_indian, south_indian, continental, chinese, drink, other}` with no East or
West bucket and no theme maps to one:

  * East Indian / Bengali — rasgulla, rasmalai, sandesh, chumchum, cham cham, raj
    bhog, langcha, ras kadam, chhena jalebi.
  * West Indian — modak, mohan thal, shrikhand, aamrakhand, aam ras, soan papdi,
    sindhi peda, the Bombay halwas.

Grouping them with the North Indian sweet counter is the conventional
menu-planning bucket and keeps them available if desserts are ever themed north.
Fresh fruit rows (cut fruit, whole banana, …) are left alone — a fruit has no
cuisine. ``tests/test_dessert_cuisine.py`` pins the reassignment and the two
deliberate exclusions.

Idempotent and committed for the same reason as the other correction scripts:
re-importing a workbook through the normaliser drops the edits, so re-run this
afterwards.

Usage:
    python scripts/dessert_cuisine_corrections.py [--dry-run]
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

#: Whole name tokens that identify a South Indian dessert family.
SOUTH_TOKENS = {
    'payasam', 'payasa', 'pradhaman', 'paramannam',
    'kesari', 'mysore', 'pongal', 'holige', 'obbattu', 'badusha',
    'adhirasam', 'athirasam', 'karadantu', 'karjikai', 'halbai',
    'sukhinunde', 'sunnundalu', 'sunundalu', 'ellu', 'bella',
    'savige', 'shavinge', 'shyavige', 'sabakki', 'surkumba', 'khaja',
}

#: Whole name tokens that identify a western/continental bakery dessert.
CONTINENTAL_TOKENS = {
    'cake', 'brownie', 'muffin', 'cupcake', 'custard', 'pudding', 'tiramisu',
}

#: Explicit whole-name continental cases the token set misses (`ice_cream` splits
#: into two common tokens, so match the dish name instead).
CONTINENTAL_NAMES = {'ice_cream', 'mango_ice_cream', 'vanilla_ice_cream_cup'}

#: Indian sweets that carry a continental token but are not continental. `cake`
#: here is Alwar/Ajmeri *milk cake*, a mawa sweet.
CONTINENTAL_EXCEPT = {'milk_cake', 'ajmeri_milk_cake'}


def classify(name: str):
    """Return the target `cuisine_family`, or ``None`` to leave the row as-is."""
    name = name.strip()
    tokens = set(name.split('_'))
    if tokens & SOUTH_TOKENS:
        return 'south_indian'
    if name in CONTINENTAL_EXCEPT:
        return None
    if name in CONTINENTAL_NAMES or (tokens & CONTINENTAL_TOKENS):
        return 'continental'
    return None


def apply_dessert_cuisine(df: pd.DataFrame):
    """Return ``(df, changes)``. Only `course_type == dessert` rows are touched."""
    df = df.copy()
    changes = []
    is_dessert = df['course_type'].astype(str).str.strip() == 'dessert'
    for idx in df.index[is_dessert]:
        name = str(df.at[idx, 'item']).strip()
        target = classify(name)
        if target is None:
            continue
        before = str(df.at[idx, 'cuisine_family']).strip()
        if before == target:
            continue
        df.at[idx, 'cuisine_family'] = target
        changes.append((name, before, target))
    return df, changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    total = 0
    for fname in sorted(f for f in os.listdir(CITY_ITEMS) if f.endswith('.xlsx')):
        city = os.path.splitext(fname)[0]
        path = os.path.join(CITY_ITEMS, fname)
        before = pd.read_excel(path)
        after, changes = apply_dessert_cuisine(before)
        if not changes:
            print(f'{city}: already correct')
            continue
        south = sum(1 for _n, _b, t in changes if t == 'south_indian')
        cont = sum(1 for _n, _b, t in changes if t == 'continental')
        print(f'{city}: {len(changes)} change(s) '
              f'({south} -> south_indian, {cont} -> continental)')
        total += len(changes)
        if not args.dry_run:
            after.to_excel(path, index=False)

    if args.dry_run:
        print('\nnothing written (--dry-run)')
    elif total:
        print(f'\nrewrote {total} row(s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
