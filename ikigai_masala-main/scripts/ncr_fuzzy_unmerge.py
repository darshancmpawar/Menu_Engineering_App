#!/usr/bin/env python3
"""Undo the NCR fuzzy matches that merged two *different* dishes into one.

The NCR workbook arrived from a mapping pipeline that fuzzy-matched each source
dish name to the master ontology at a 0.82 string-similarity threshold and, on a
match, REPLACED the source name with the master name (its `Mapping_Log` decision
`ACCEPT_REVIEW`, 190 of them, each flagged "verify"). Most are harmless
transliteration variants — `kadhai`→`kadai`, `chola`→`chole`, `laddoo`→`laddu`,
`ajwain`→`ajawin`. But string similarity is blind to meaning, and a handful
collapsed genuinely distinct menu items:

    aloo_matar (potato+PEAS)   -> aloo_tamatar (potato+TOMATO)
    paneer_butter              -> paneer_mutter (butter -> peas)
    lauki_kofta (bottle gourd) -> malai_kofta   (gourd -> cream)
    kala_chana (BLACK gram)    -> kabul_chana   (black -> white chickpea)
    bhuna_chicken (N. Indian)  -> hunan_chicken (Indian -> Chinese)
    punjabi_kadhi (yogurt curry) -> punjabi_kadai (kadhi -> wok)
    ... (see RENAMES / SPLITS below)

The client confirmed only pure spelling variants may merge; a dish that became a
different dish must be restored. Tellingly, the merged rows kept the *source*
dish's attributes (the `aloo_tamatar` row is key_ingredient=`potato`, the
`malai_kofta` row is `bottle_gourd`), so the corruption is in the NAME, not the
columns — which makes most fixes a rename.

Two targets are COLLISIONS: a real dish and a spelling variant *also* merged into
the same master row, so a bare rename would lose the real dish. Those are split —
the existing row stays as the real dish and a fresh row is added for the restored
one, with a new item_id above the workbook's current max.

Idempotent and committed for the same reason as the other correction scripts
(`seafood_taxonomy.py`, `course_type_corrections.py`, `remove_generic_rows.py`):
re-importing the raw workbook through the normaliser brings the merged names back,
so re-run this afterwards. `tests/test_ncr_fuzzy_unmerge.py` fails if any merged
name reappears or a restored one goes missing.

Usage:
    python scripts/ncr_fuzzy_unmerge.py [--dry-run]
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

CITY = 'ncr'

#: merged name -> restored source name. Single-source merges: the row IS the
#: source dish (only its name was overwritten), so a rename is the whole fix.
RENAMES = {
    'aloo_tamatar_dry':     'aloo_matar_dry',
    'aloo_tamatar_gravy':   'aloo_matar_gravy',
    'soya_tamatar':         'soya_matar',
    'paneer_mutter':        'paneer_butter',
    'malai_mushroom_curry': 'matar_mushroom_curry',
    'malai_kofta_gravy':    'lauki_kofta_gravy',
    'kabul_chana_gravy':    'kala_chana_gravy',
    'hunan_chicken':        'bhuna_chicken',
    'paneer_chingari_masala': 'paneer_achari_masala',
    'punjabi_kadai':        'punjabi_kadhi',
    'veg_kadai':            'veg_kadhi',
}

#: restored name -> {column: value}. Fixes attributes that reflect the WRONG dish
#: and would change engine behaviour:
#:  * bhuna_chicken was filed `chicken_chinese_gravy` (bhuna is North Indian, not
#:    Chinese) — left alone it plans as a Chinese dish on chinese days only.
#:  * paneer_achari lost its paneer identity (tagged key_ingredient=carrot,
#:    mixed_veg_curry), so the paneer rules (prefers mix/south/north days; not on
#:    a soya/chana day) would skip it.
ATTR_FIXES = {
    'bhuna_chicken': {
        'sub_category': 'chicken_bhuna_kadai',
        'is_chinese_chicken_gravy': 0,
        'is_north_chicken_gravy': 1,
    },
    'paneer_achari_masala': {
        'primary_protein': 'paneer',
        'key_ingredient': 'paneer',
        'sub_category': 'paneer_curry',
        'is_paneer_gravy': 1,
    },
}

#: (row to keep as-is, restored name to ADD). A real dish and a spelling variant
#: both merged here, so the kept row is the real dish and the restored one needs
#: a fresh row. Attributes are copied from the kept row (same base ingredient),
#: keeping its client tags so availability is unchanged for those clients.
SPLITS = [
    ('aloo_tamatar', 'aloo_matar'),    # keep potato+tomato, add potato+peas
    ('paneer_kadai', 'paneer_adraki'),  # keep kadai paneer, add ginger paneer
]


def _next_ids(df: pd.DataFrame, n: int):
    nums = (df['item_id'].astype(str)
            .str.extract(r'MENU(\d+)')[0].dropna().astype(int))
    start = int(nums.max()) + 1 if len(nums) else 1
    return [f'MENU{start + i:06d}' for i in range(n)]


def apply_unmerge(df: pd.DataFrame):
    """Return ``(df, changes)``. Pure, so tests can call it."""
    df = df.copy()
    names = set(df['item'].astype(str).str.strip())
    changes = []

    for merged, restored in RENAMES.items():
        if merged not in names:
            continue                       # already renamed (idempotent)
        if restored in names:
            changes.append((merged, 'SKIP', f'{restored} already present'))
            continue
        idx = df.index[df['item'].astype(str).str.strip() == merged]
        df.loc[idx, 'item'] = restored
        fixes = ATTR_FIXES.get(restored, {})
        for col, val in fixes.items():
            if col in df.columns:
                df.loc[idx, col] = val
        names.add(restored)
        names.discard(merged)
        changes.append((merged, 'RENAME',
                        restored + (f'  +attrs{list(fixes)}' if fixes else '')))

    to_add = [(keep, new) for keep, new in SPLITS
              if new not in names and keep in names]
    new_ids = _next_ids(df, len(to_add))
    for (keep, new), new_id in zip(to_add, new_ids):
        row = df[df['item'].astype(str).str.strip() == keep].iloc[0].copy()
        row['item'] = new
        row['item_id'] = new_id
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        names.add(new)
        changes.append((keep, 'SPLIT', f'added {new} ({new_id})'))

    return df, changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    path = os.path.join(CITY_ITEMS, f'{CITY}.xlsx')
    if not os.path.exists(path):
        print(f'{CITY}: no workbook at {path}', file=sys.stderr)
        return 1
    before = pd.read_excel(path)
    after, changes = apply_unmerge(before)
    real = [c for c in changes if c[1] != 'SKIP']
    skips = [c for c in changes if c[1] == 'SKIP']
    if not real:
        print(f'{CITY}: already unmerged')
        return 0
    print(f'{CITY}:')
    for item, kind, detail in changes:
        print(f'  {kind:7} {item:26} -> {detail}')
    if not args.dry_run:
        after.to_excel(path, index=False)
        print(f'\nrewrote {len(real)} change(s) ({len(skips)} skipped)')
    else:
        print('\nnothing written (--dry-run)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
