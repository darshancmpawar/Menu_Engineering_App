#!/usr/bin/env python3
"""Dishes filed under the wrong `course_type`, in any city list.

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

`scripts/audit_course_types.py` is the other half: it flags name/course_type
disagreements so a new import cannot introduce this class of error unnoticed. Every
correction below started as one of its findings.

Idempotent and committed for the same reason as `seafood_taxonomy.py` and
`pune_flag_corrections.py`: re-importing a workbook through the normaliser drops
the edits, so re-run this afterwards.

Usage:
    python scripts/course_type_corrections.py [--dry-run]
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

#: ``city -> {item: (course_type, sub_category, dessert_form_or_None)}``.
#: `dessert_form` is set on new desserts because `dessert_form_non_consecutive`
#: groups on it — a dessert arriving with a blank there is silently exempt from the
#: variety rule. None means "leave whatever is there".
CORRECTIONS = {
    'chennai': {
        # Payasams filed as a mixed-veg curry. `wet` matches the other payasams.
        'millet_payasam':              ('dessert', 'payasam_/_kheer', 'wet'),
        'semiya_pal_payasam':          ('dessert', 'payasam_/_kheer', 'wet'),
        # Sweet pongal filed as rice. `semi_dry` matches the kesari/halwa family —
        # sweet pongal is spoonable, not pourable.
        'kalkandu_pongal':             ('dessert', 'sweet_pongal', 'semi_dry'),
        'mapillai_samba_sweet_pongal': ('dessert', 'sweet_pongal', 'semi_dry'),
    },
    'bangalore': {
        # A moong dal DOSA filed as the day's dal, with sub_category `leafy_dal`
        # (wrong twice — it is not leafy either). 37 other dosas are `bread`; this
        # was the only one that was not, so a client with a dal slot could be
        # served a dosa as their dal. `lentil-based_dosa_(adai/pesarattu)` is the
        # sub_category pesarattu and adai_dosa already use.
        'moong_dal_dosa': ('bread', 'lentil-based_dosa_(adai/pesarattu)', None),
    },
}

def apply_corrections(df: pd.DataFrame, city: str):
    """Return ``(df, changes)`` for one city. Pure, so tests can call it."""
    df = df.copy()
    changes = []
    for item, (course, sub, form) in CORRECTIONS.get(city, {}).items():
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
            if form and 'dessert_form' in df.columns:
                df.at[idx, 'dessert_form'] = form
            changes.append((item, f'{before[0]}/{before[1]}', f'{course}/{sub}',
                            form or ''))
    return df, changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    total, missing_any = 0, False
    for city in sorted(CORRECTIONS):
        path = os.path.join(CITY_ITEMS, f'{city}.xlsx')
        if not os.path.exists(path):
            print(f'{city}: no workbook at {path}', file=sys.stderr)
            missing_any = True
            continue
        before = pd.read_excel(path)
        after, changes = apply_corrections(before, city)
        missing = [c for c in changes if c[1] == 'MISSING']
        real = [c for c in changes if c[1] != 'MISSING']
        if missing:
            missing_any = True
            print(f'{city}: NOT FOUND (renamed?): {[m[0] for m in missing]}',
                  file=sys.stderr)
        if not real:
            print(f'{city}: already correct')
            continue
        print(f'{city}:')
        for item, old, new, form in real:
            extra = f'  (dessert_form={form})' if form else ''
            print(f'  {item:30s} {old:34s} -> {new}{extra}')
        total += len(real)
        if not args.dry_run:
            after.to_excel(path, index=False)

    if args.dry_run:
        print('\nnothing written (--dry-run)')
    elif total:
        print(f'\nrewrote {total} row(s)')
    return 1 if missing_any else 0


if __name__ == '__main__':
    raise SystemExit(main())
