#!/usr/bin/env python3
"""Give seafood a real place in the ontology, then reclassify the rows that need it.

The master taxonomy grew up around a chicken-and-egg non-veg list: it has
`is_egg_dish` for the protein and `chicken_*` sub-categories for everything else.
Chennai is the first city list with fish, and the import filed all 8 fish dishes
under the closest chicken bucket it could find — `fish_kuzhambu` came through as
`sub_category: chicken_south_coastal`, `key_ingredient: chicken`, carrying
`is_south_chicken_gravy`. Only `primary_protein` was right.

That is not a Chennai problem, it is a missing branch of the taxonomy, so the fix
is here rather than in a per-city patch:

  * two new columns, `is_fish_dish` (mirrors `is_egg_dish`) and `is_seafood` (the
    umbrella, so a rule can say "seafood twice a week" without enumerating
    species). Added to EVERY city workbook, because `normalize_city_ontology.py`
    forces a new city's column set to the reference list's — a column missing
    from `bangalore.xlsx` cannot exist in any city;
  * `sub_category` moved off the chicken bucket, keeping the descriptive suffix:
    `chicken_south_coastal` -> `fish_south_coastal`. Nothing keys on these strings
    (the rules all use `is_*` flags), so the rename is safe, and keeping the
    suffix means anything that later reasons about "_chinese_dry" still works;
  * `key_ingredient` set to the protein. This one is a live correctness bug, not
    tidiness: `ingredient_ban_rule` matches on `key_ingredient` AND
    `primary_protein`, so a client banning chicken was banning the fish dishes
    too, and a client banning fish caught them only by luck of the second column;
  * chicken-specific flags cleared. `fish_kuzhambu` held `is_south_chicken_gravy`,
    which put a fish into `avoid_consecutive_south_chicken` (a rule about
    chicken) and into `_augment_nonveg_pair`'s "keep the regional chicken gravy"
    exemption. `is_nonveg_gravy` + `cuisine_family` + `is_fish_dish` already say
    everything true about the dish.

Idempotent and committed for the same reason as `pune_flag_corrections.py`:
re-importing a workbook through the normaliser drops these edits, so re-run it
afterwards. `tests/test_seafood_taxonomy.py` fails if the corrections are missing.

Usage:
    python scripts/seafood_taxonomy.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CITY_ITEMS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'raw', 'city_items')

#: Proteins that make a dish seafood. `primary_protein` is the trustworthy column
#: on these rows — it was right even when everything else pointed at chicken.
SEAFOOD_PROTEINS = {
    'fish', 'prawn', 'prawns', 'shrimp', 'crab', 'squid', 'seafood', 'lobster',
}
#: Of those, the ones `is_fish_dish` covers. Prawn/crab are seafood but not fish;
#: a rule wanting both should use `is_seafood`.
FISH_PROTEINS = {'fish'}

#: New columns, inserted directly after `is_egg_dish` so the protein-identity
#: flags read together rather than being appended to a 133-column tail. Declared
#: umbrella-first, which is the order they end up in on disk.
NEW_FLAG_COLUMNS = ('is_seafood', 'is_fish_dish')
_ANCHOR_COLUMN = 'is_egg_dish'

#: Named `cuisine_family` fixes. Chennai's import tagged three fish dishes
#: north_indian; the master files `chicken_65` as south_indian, so `fish_65`
#: sitting in north was inconsistent with the taxonomy's own convention — and it
#: matters, because the theme filter narrows `nonveg_main` by cuisine, so a
#: mis-tagged Chennai dish is simply unavailable on the city's south days.
#: `fish_tawa_fry` is deliberately NOT in this list: tawa fry is a north/street
#: preparation and the master keeps a `street_/_tawa_/_omelette_special` bucket.
CUISINE_FIXES = {
    'fish_65': 'south_indian',
    'fish_roast': 'south_indian',
    'fish_kuzhambu': 'south_indian',   # already correct; pinned so it stays
}


def _to01(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce').fillna(0).astype(int)


def _norm(value) -> str:
    return str(value or '').strip().lower()


def add_flag_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Ensure the seafood flag columns exist, defaulting to 0. Returns added names."""
    added = []
    for name in NEW_FLAG_COLUMNS:
        if name in df.columns:
            continue
        pos = (list(df.columns).index(_ANCHOR_COLUMN) + 1
               if _ANCHOR_COLUMN in df.columns else len(df.columns))
        # Offset by how many we have already inserted this pass, or the second
        # column lands on top of the first and the pair comes out reversed.
        df.insert(pos + len(added), name, 0)
        added.append(name)
    return df, added


def apply_seafood_taxonomy(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Set the seafood flags and repair the columns the chicken bucket polluted.

    Pure apart from the frame it is handed, so the tests can call it directly.
    """
    df = df.copy()
    df, added = add_flag_columns(df)
    for name in NEW_FLAG_COLUMNS:
        df[name] = _to01(df[name])

    protein = df['primary_protein'].map(_norm)
    is_seafood = protein.isin(SEAFOOD_PROTEINS)
    changes = {'columns_added': added, 'seafood_rows': int(is_seafood.sum()),
               'flags_set': 0, 'sub_category': [], 'key_ingredient': [],
               'chicken_flags_cleared': [], 'cuisine_family': []}
    if not is_seafood.any():
        return df, changes

    df.loc[is_seafood, 'is_seafood'] = 1
    df.loc[protein.isin(FISH_PROTEINS), 'is_fish_dish'] = 1
    changes['flags_set'] = int(is_seafood.sum())

    chicken_flag_cols = [c for c in df.columns
                         if c.startswith('is_') and 'chicken' in c]

    for idx in df.index[is_seafood]:
        item = str(df.at[idx, 'item'])
        prot = _norm(df.at[idx, 'primary_protein'])

        # sub_category: swap the chicken bucket for the protein, keep the suffix.
        sub = _norm(df.at[idx, 'sub_category'])
        if sub.startswith('chicken_'):
            new_sub = f'{prot}_{sub[len("chicken_"):]}'
            if new_sub != sub:
                df.at[idx, 'sub_category'] = new_sub
                changes['sub_category'].append((item, sub, new_sub))

        # key_ingredient: the ingredient-ban bug.
        key = _norm(df.at[idx, 'key_ingredient'])
        if key != prot:
            df.at[idx, 'key_ingredient'] = prot
            changes['key_ingredient'].append((item, key, prot))

        # Chicken-specific flags do not belong on a fish.
        for col in chicken_flag_cols:
            if int(pd.to_numeric([df.at[idx, col]], errors='coerce')[0] or 0) == 1:
                df.at[idx, col] = 0
                changes['chicken_flags_cleared'].append((item, col))

        want = CUISINE_FIXES.get(item)
        if want and _norm(df.at[idx, 'cuisine_family']) != want:
            changes['cuisine_family'].append(
                (item, _norm(df.at[idx, 'cuisine_family']), want))
            df.at[idx, 'cuisine_family'] = want

    return df, changes


def _describe(city: str, changes: dict) -> None:
    added = changes['columns_added']
    n = changes['seafood_rows']
    if not added and not n:
        print(f'  {city:12s} no seafood rows, columns already present')
        return
    bits = []
    if added:
        bits.append(f'+{len(added)} column(s) {added}')
    if n:
        bits.append(f'{n} seafood row(s)')
    print(f'  {city:12s} {"; ".join(bits)}')
    for label, key in (('sub_category', 'sub_category'),
                       ('key_ingredient', 'key_ingredient'),
                       ('cuisine_family', 'cuisine_family')):
        for item, old, new in changes[key]:
            print(f'      {label:15s} {item:24s} {old or "(blank)"} -> {new}')
    for item, col in changes['chicken_flags_cleared']:
        print(f'      cleared         {item:24s} {col}')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true',
                    help='report what would change; write nothing')
    args = ap.parse_args(argv)

    paths = sorted(f for f in os.listdir(CITY_ITEMS_DIR) if f.endswith('.xlsx'))
    if not paths:
        print(f'no workbooks in {CITY_ITEMS_DIR}', file=sys.stderr)
        return 1

    print(f'{"DRY RUN — " if args.dry_run else ""}seafood taxonomy '
          f'over {len(paths)} workbook(s)')
    wrote = 0
    for fname in paths:
        city = os.path.splitext(fname)[0]
        full = os.path.join(CITY_ITEMS_DIR, fname)
        before = pd.read_excel(full)
        after, changes = apply_seafood_taxonomy(before)
        _describe(city, changes)
        identical = before.equals(after)
        if identical:
            continue
        if not args.dry_run:
            after.to_excel(full, index=False)
            wrote += 1

    if args.dry_run:
        print('\nnothing written (--dry-run)')
    else:
        print(f'\nrewrote {wrote} workbook(s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
