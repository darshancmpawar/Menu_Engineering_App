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
        # Accompaniment that the client serves as a gravy — see the Bangalore entry
        # below. ToastTab's own Friday sample has it in the veg-gravy position.
        'tomato_thokku': ('veg_gravy', 'mixed_veg_curry', None),
    },
    'bangalore': {
        # Drinks filed as a mixed-veg curry. Eight other buttermilks in the same
        # workbook are `welcome_drink / indian_regional_drink`, so the file
        # disagrees with itself. NOT touched: majjige_huli and its two variants,
        # which really are buttermilk CURRIES and correctly `veg_gravy / kadhi`.
        'butter_milk':        ('welcome_drink', 'indian_regional_drink', None),
        'masala_butter_milk': ('welcome_drink', 'indian_regional_drink', None),
        'boondi_butter_milk': ('welcome_drink', 'indian_regional_drink', None),
        # Filed `accompaniment / non-herb_chutney`, so it could never be selected
        # for `veg_gravy` — yet ToastTab's Friday sample serves tomato thokku in
        # the veg-gravy position (D2 in docs/data_fixes_for_client.md). The client
        # confirmed it is a gravy for them. `mixed_veg_curry` matches its South
        # Indian tomato siblings `tomato_gojju` / `tomato_masala`, not the
        # continental `tomato_base_gravy` bucket.
        'tomato_thokku': ('veg_gravy', 'mixed_veg_curry', None),
        # UNSERVABLE, not merely misfiled: course_type `rice` with
        # primary_protein `egg`. PoolBuilder._nonveg_mask drops non-veg rows from
        # every slot except nonveg_main, so this was dropped from the rice pool —
        # and being course_type `rice` it never entered nonveg_main either. It
        # could not be served at all. Every chicken biryani in the master is
        # nonveg_main for exactly this reason; the egg rice was the one that
        # missed the convention.
        'egg_fried_rice': ('nonveg_main', 'chicken_chinese_dry', None),
        # A moong dal DOSA filed as the day's dal, with sub_category `leafy_dal`
        # (wrong twice — it is not leafy either). 37 other dosas are `bread`; this
        # was the only one that was not, so a client with a dal slot could be
        # served a dosa as their dal. `lentil-based_dosa_(adai/pesarattu)` is the
        # sub_category pesarattu and adai_dosa already use.
        'moong_dal_dosa': ('bread', 'lentil-based_dosa_(adai/pesarattu)', None),
    },
    # NCR arrived from a mapping pipeline that inherited a modal flag vector per
    # sub_category, so a dish landing in the wrong sub_category (e.g. a chicken
    # curry whose section header read like a bread) also got the wrong
    # course_type. The auditor flagged 34; the 31 below are genuine misfiles
    # (the other 3 are adjudicated in audit_course_types.py). sub_categories are
    # NCR's own except the two non-veg fried rices, which reuse the master's
    # `chicken_chinese_dry` bucket the Bangalore `egg_fried_rice` fix already set.
    'ncr': {
        # UNSERVABLE — non-veg protein filed outside nonveg_main (see the
        # egg_fried_rice note above). Dropped from their own pool by
        # `_nonveg_mask` and never joined nonveg_main, so they could not appear.
        'chicken_fried_rice':  ('nonveg_main', 'chicken_chinese_dry', None),
        'dhaba_chicken_curry': ('nonveg_main', 'chicken_north_masala', None),
        'egg_curry_masala':    ('nonveg_main', 'north_style_masala_curry', None),
        'kolhapuri_chicken':   ('nonveg_main', 'chicken_north_masala', None),
        # `soya_keema` is minced SOYA (key_ingredient soya), not meat — the
        # `primary_protein: mutton` is a bad fuzzy match on "keema". Cleared to
        # veg below (PROTEIN_CORRECTIONS) and filed as the soya veg dry it is.
        'soya_keema':          ('veg_dry', 'chole_and_soya_dry', None),
        # Sweets filed as veg_gravy/dal — would have plated as a "gravy".
        'badami_moong_dal_barfi': ('dessert', 'burfi', 'semi_dry'),
        'gaund_pak':              ('dessert', 'burfi', 'semi_dry'),
        'gond_pak':               ('dessert', 'burfi', 'semi_dry'),
        'kesari_rawa':            ('dessert', 'halwa', 'semi_dry'),
        'rava_kesari':            ('dessert', 'halwa', 'semi_dry'),
        'kulfi':                  ('dessert', 'custard_/_pudding', 'wet'),
        'massor_pak':             ('dessert', 'burfi', 'semi_dry'),
        'mathura_peda':           ('dessert', 'burfi', 'semi_dry'),
        'pudding_ala_cream':      ('dessert', 'custard_/_pudding', 'wet'),
        'sweet_laddoo':           ('dessert', 'laddu', 'semi_dry'),
        # Drinks filed as veg_gravy/dessert.
        'gulab_sherbat':       ('welcome_drink', 'indian_regional_drink', None),
        'jaljeera_treat':      ('welcome_drink', 'indian_regional_drink', None),
        'kokum':               ('welcome_drink', 'indian_regional_drink', None),
        'kokum_shikanj':       ('welcome_drink', 'indian_regional_drink', None),
        'kokum_shikanji':      ('welcome_drink', 'indian_regional_drink', None),
        'lemon_mint_mojito':   ('welcome_drink', 'fruit_spritzer_/_punch', None),
        'mint_mojito':         ('welcome_drink', 'fruit_spritzer_/_punch', None),
        'punjabi_sweet_lassi': ('welcome_drink', 'lassi', None),
        # Soups filed as veg_gravy.
        'cucumber_soup':         ('soup', 'clear_/_broth_soup', None),
        'spinach_soup':          ('soup', 'chunky_veg_soup', None),
        'tomato_dhaniya_shorba': ('soup', 'clear_/_broth_soup', None),
        'veg_noodle_soup':       ('soup', 'asian_soup', None),
        # A pulao filed as bread; a steamed idli/vada plate filed as a gravy.
        'jodhpuri_pulao': ('rice', 'north_rich_pulao', None),
        'idly_vada':      ('bread', 'idli_/_steamed', None),
        # Raitas filed as `dessert / payasam_/_kheer` — a raita served as sweet.
        'kheera_raita':             ('curd_side', 'raita', None),
        'kheera_raita_lemon_water': ('curd_side', 'raita', None),
    },
}

#: ``city -> {item: primary_protein}``. A separate map because the fix runs the
#: OTHER way: the dish is filed in the right category and its *protein* is wrong.
#:
#: `urandai_kuzhambu` was `veg_gravy` with `primary_protein: egg`, which made it
#: unservable — `_nonveg_mask` drops non-veg rows from every slot except
#: nonveg_main, so it left the veg_gravy pool and joined nothing. Urundai kuzhambu
#: is a lentil-dumpling gravy; `is_egg_dish` is 0 on the row and all 11 sibling veg
#: kuzhambus carry no protein at all, so the column was simply wrong. Moving it to
#: nonveg_main would have "fixed" the symptom by making a veg dish non-veg.
PROTEIN_CORRECTIONS = {
    'chennai': {
        'urandai_kuzhambu': '',   # '' -> blank, i.e. vegetarian
    },
    'ncr': {
        # Minced soya, not meat — `mutton` was a fuzzy match on "keema". Cleared
        # to veg; the course_type fix above files it as a soya veg dry.
        'soya_keema': '',
    },
}


def apply_corrections(df: pd.DataFrame, city: str):
    """Return ``(df, changes)`` for one city. Pure, so tests can call it."""
    df = df.copy()
    changes = []
    for item, want in PROTEIN_CORRECTIONS.get(city, {}).items():
        hits = df.index[df['item'].astype(str).str.strip() == item]
        if len(hits) == 0:
            changes.append((item, 'MISSING', '', ''))
            continue
        for idx in hits:
            before = str(df.at[idx, 'primary_protein']).strip()
            if before in ('', 'nan', 'None') and want == '':
                continue
            if before == want:
                continue
            df.at[idx, 'primary_protein'] = want
            changes.append((item, f'protein={before}',
                            f'protein={want or "(veg)"}', ''))

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
    for city in sorted(set(CORRECTIONS) | set(PROTEIN_CORRECTIONS)):
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
