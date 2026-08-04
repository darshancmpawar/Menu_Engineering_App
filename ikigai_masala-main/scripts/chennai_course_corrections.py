#!/usr/bin/env python3
"""Dishes filed under the wrong `course_type` in the Chennai list.

`course_type` decides which slot pool a dish lands in, so a misfiled row is not a
cosmetic problem — it becomes servable in the wrong position on the plate. Found
by running ToastTab CHN's real config and reading the output: Tuesday's
`veg_gravy__1` came back as `semiya_pal_payasam`, a milk-and-vermicelli dessert,
sitting beside a kuzhambu as one of the day's two "gravies".

Two families are wrong, and both are internally inconsistent — the same workbook
files the sibling dishes correctly:

  * `millet_payasam` and `semiya_pal_payasam` are `veg_gravy / mixed_veg_curry`,
    while `semiya_payasam`, `rice_kheer`, `semiya_kheer` and
    `moong_dal_thengai_kheer` are all correctly `dessert / payasam_/_kheer`.
  * `kalkandu_pongal` and `mapillai_samba_sweet_pongal` are `rice /
    south_one_pot_rice`. Sweet pongal is a dessert; the client's own sample serves
    kalkandu pongal in the dessert position. Savoury `pongal` and
    `semiya_kichadi` stay as rice, which is correct.

Idempotent and committed for the same reason as `seafood_taxonomy.py` and
`pune_flag_corrections.py`: re-importing the workbook through the normaliser drops
the edits, so re-run this afterwards.

Usage:
    python scripts/chennai_course_corrections.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORKBOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'raw', 'city_items', 'chennai.xlsx')

#: ``item -> (course_type, sub_category, dessert_form)``. `dessert_form` is set
#: because `dessert_form_non_consecutive` groups on it — a dessert arriving with a
#: blank there would be silently exempt from the variety rule.
CORRECTIONS = {
    # Payasams filed as a mixed-veg curry. `wet` matches the other payasams.
    'millet_payasam':              ('dessert', 'payasam_/_kheer', 'wet'),
    'semiya_pal_payasam':          ('dessert', 'payasam_/_kheer', 'wet'),
    # Sweet pongal filed as rice. `semi_dry` matches the kesari/halwa family,
    # which is the closest form — sweet pongal is spoonable, not pourable.
    'kalkandu_pongal':             ('dessert', 'sweet_pongal', 'semi_dry'),
    'mapillai_samba_sweet_pongal': ('dessert', 'sweet_pongal', 'semi_dry'),
}


def apply_corrections(df: pd.DataFrame):
    """Return ``(df, changes)``. Pure, so tests can call it directly."""
    df = df.copy()
    changes = []
    for item, (course, sub, form) in CORRECTIONS.items():
        hits = df.index[df['item'].astype(str).str.strip() == item]
        if len(hits) == 0:
            changes.append((item, 'MISSING', '', ''))
            continue
        for idx in hits:
            before = (str(df.at[idx, 'course_type']).strip(),
                      str(df.at[idx, 'sub_category']).strip())
            if before == (course, sub):
                continue
            df.at[idx, 'course_type'] = course
            df.at[idx, 'sub_category'] = sub
            if 'dessert_form' in df.columns:
                df.at[idx, 'dessert_form'] = form
            changes.append((item, f'{before[0]}/{before[1]}', f'{course}/{sub}', form))
    return df, changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    before = pd.read_excel(WORKBOOK)
    after, changes = apply_corrections(before)
    missing = [c for c in changes if c[1] == 'MISSING']
    real = [c for c in changes if c[1] != 'MISSING']

    if missing:
        print('NOT FOUND in the workbook (did the item get renamed?):',
              [m[0] for m in missing], file=sys.stderr)
    if not real:
        print('nothing to change — corrections already applied')
        return 1 if missing else 0
    for item, old, new, form in real:
        print(f'  {item:30s} {old:34s} -> {new}  (dessert_form={form})')
    if args.dry_run:
        print('\nnothing written (--dry-run)')
    else:
        after.to_excel(WORKBOOK, index=False)
        print(f'\nrewrote {os.path.basename(WORKBOOK)} ({len(real)} row(s))')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
