#!/usr/bin/env python3
"""Flag corrections applied to `data/raw/city_items/pune.xlsx`.

Two Pune rulebook rules select on flags the raw workbook left at 0, which made
them silently inert:

* **R14** "Black chana gravies: max once/week" — `is_black_chana_gravy` was 0 for
  every row, including `black_chana_malwani`.
* **R31** "Leafy-veg dry items: only once in 15 days" and **R43** "Only one
  leafy-based dish per menu" — `is_leafy_based_dish` was set on a rice, a dal and
  a salad but on none of the veg dries or gravies built on spinach, fenugreek or
  coriander.

This script is committed rather than the edit being made by hand so the change is
reviewable and, more importantly, **re-appliable**: re-importing a fresh workbook
from the ops team through `normalize_city_ontology.py` would otherwise silently
drop these corrections. Run it after any such re-import.

Idempotent — it reports what it changed and writes nothing when there is nothing
to change.

    python scripts/pune_flag_corrections.py --dry-run
    python scripts/pune_flag_corrections.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PUNE_XLSX = REPO_ROOT / 'data' / 'raw' / 'city_items' / 'pune.xlsx'

# item -> {column: value} for non-flag corrections (text columns).
# Kept separate from CORRECTIONS because these are taxonomy fixes, not 0/1 flags.
COLUMN_CORRECTIONS = {
    # `potato_chilli` was tagged `key_ingredient: paneer` while being a potato
    # dish. That made it the only paneer-tagged veg dry in the list, so it counted
    # against a client's "one paneer a week" rule whenever it was chosen —
    # a paneer budget spent on a potato dish. Client-confirmed correction.
    'potato_chilli': {'key_ingredient': 'potato'},

    # Two soya dishes were left on their vegetable's key_ingredient, so the
    # "no soya on a paneer day" rule could not see them (it selects
    # `key_ingredient: soy`, the tag the list's other four soya dishes carry).
    # Both are named after the soya, which is what makes the fix unambiguous.
    'aloo_soya_sukha': {'key_ingredient': 'soy'},
    'soya_capsicum_chatpata': {'key_ingredient': 'soy'},
}

# item -> {flag: value}. Every entry carries its reason in the comment above it.
CORRECTIONS = {
    # R14. The only black-chana *gravy* in the list. `black_chana_dry` is a veg
    # dry, so the gravy flag does not apply to it.
    'black_chana_malwani': {'is_black_chana_gravy': 1},

    # R31 / R43. The convention already in the data is "the defining ingredient
    # is a leafy green" — `coriander_rice`, `dal_palak`, `green_salad` and
    # `methi_mutter_masala` were flagged, so palak / methi / coriander / mint
    # dishes are in and cucumber (`khamang_kakadi`) and cabbage are out.
    'palak_paneer': {'is_leafy_based_dish': 1},              # spinach gravy
    'palak_peas_curry': {'is_leafy_based_dish': 1},           # spinach gravy
    'lasooni_aloo_palak_dry': {'is_leafy_based_dish': 1},     # spinach veg dry
    'moong_methi_dry': {'is_leafy_based_dish': 1},            # fenugreek leaves
    'mix_veg_hariyali': {'is_leafy_based_dish': 1},           # green herb paste
    'dal_methi': {'is_leafy_based_dish': 1},                  # fenugreek leaves
    'dal_coriander': {'is_leafy_based_dish': 1},              # coriander
    'mint_rice': {'is_leafy_based_dish': 1},                  # mint, as coriander_rice
}


def apply(df: pd.DataFrame) -> tuple:
    """Return ``(df, changes)`` — pure, so it is unit-testable."""
    changes = []
    missing = []
    for item, flags in CORRECTIONS.items():
        rows = df.index[df['item'] == item]
        if not len(rows):
            missing.append(item)
            continue
        for flag, value in flags.items():
            if flag not in df.columns:
                missing.append(f'{item}.{flag}')
                continue
            before = df.loc[rows[0], flag]
            if int(pd.to_numeric(before, errors='coerce') or 0) != value:
                df.loc[rows[0], flag] = value
                changes.append((item, flag, before, value))
    for item, columns in COLUMN_CORRECTIONS.items():
        rows = df.index[df['item'] == item]
        if not len(rows):
            missing.append(item)
            continue
        for column, value in columns.items():
            if column not in df.columns:
                missing.append(f'{item}.{column}')
                continue
            before = df.loc[rows[0], column]
            if str(before).strip() != str(value):
                df.loc[rows[0], column] = value
                changes.append((item, column, before, value))
    return df, (changes, missing)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--path', default=str(PUNE_XLSX))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    df = pd.read_excel(args.path)
    df, (changes, missing) = apply(df)

    for item, flag, before, after in changes:
        print(f"  {item:26s} {flag:22s} {before} -> {after}")
    if missing:
        print(f"!! not found in {args.path}: {missing}")
    if not changes:
        print("nothing to change — the corrections are already applied")
        return 1 if missing else 0
    if args.dry_run:
        print(f"dry run: would rewrite {args.path} ({len(changes)} change(s))")
        return 0
    df.to_excel(args.path, index=False)
    print(f"wrote {args.path} ({len(changes)} change(s))")
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
