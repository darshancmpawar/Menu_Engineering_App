#!/usr/bin/env python3
"""Flag dishes whose NAME disagrees with the `course_type` they are filed under.

`course_type` decides which slot pool a dish lands in, so a misfile is not a
labelling nit — the dish becomes servable in the wrong position on the plate. Two
real examples, both found by reading generated menus rather than by reading data:

  * `semiya_pal_payasam` was `veg_gravy`, so a milk-and-vermicelli dessert came
    back as one of the day's two gravies;
  * `moong_dal_dosa` was `dal` (37 other dosas are `bread`), so a client with a dal
    slot could be served a dosa as their dal.

Neither triggered any rule, diagnostic or test. Nothing in the engine knows what a
dish *is* — only what the columns say — so the only way to catch this class is to
compare the dish's name against its filing, which is what this does.

## Why token matching, and why an allow-list

Substring matching is useless here: `kadai_mushroom` contains "adai", `kolhapuri`
contains "puri", `sweet_corn_soup` contains "sweet". A first pass with substrings
produced 238 hits for Bangalore, essentially all false. Splitting the name on `_`
and matching whole tokens drops that to 9, which a human can actually adjudicate.

The remainder still needs judgement, so two escape hatches encode it:

  * `LEGITIMATE_PAIRS` — whole categories of overlap that are correct by design. A
    chicken biryani belongs in `nonveg_main`, not `rice`. `kesari_bath` is a sweet
    named for a rice dish. `healthy_rice` IS a rice slot.
  * `ADJUDICATED` — individual rows reviewed and accepted, each with the reason.
    `sambar_rice` really is a rice dish; `capsicum_pulao_raita` really is a raita.

Anything left is unadjudicated and exits non-zero. `tests/test_course_type_audit.py`
runs this, so a re-import that introduces a new mismatch fails the build instead of
surfacing months later as a dessert in the gravy slot.

Usage:
    python scripts/audit_course_types.py            # all cities
    python scripts/audit_course_types.py --verbose  # also list what was allowed
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

#: ``course_type`` -> name tokens that imply it. Whole tokens only.
NAME_SIGNALS = {
    'dessert': {
        'payasam', 'payasa', 'kheer', 'halwa', 'kesari', 'laddu', 'laddoo',
        'burfi', 'barfi', 'jamun', 'jalebi', 'jelabi', 'custard', 'peda', 'pak',
        'badusha', 'adhirasam', 'tukda', 'malpua', 'chumchum', 'rasmalai',
        'basundi', 'kulfi', 'sheera', 'pudding', 'kalkandu', 'mishti', 'holige',
        'obbattu', 'sandesh', 'rabri', 'phirni', 'shrikhand',
    },
    'rice': {'biryani', 'biriyani', 'pulao', 'pulav', 'rice', 'bisibelebath',
             'khichdi', 'bagara'},
    'bread': {'roti', 'paratha', 'parotta', 'naan', 'chapati', 'chapatti',
              'kulcha', 'phulka', 'dosa', 'dosai', 'idly', 'idli', 'appam',
              'uttapam', 'uthappam', 'thepla', 'bhatura', 'rumali', 'pesarattu',
              'poori', 'puri', 'kotthu'},
    'rasam': {'rasam', 'rassam'},
    'sambar': {'sambar', 'sambhar'},
    'soup': {'soup', 'shorba', 'broth', 'chowder'},
    'salad': {'salad', 'kosambari', 'koshimbir'},
    'curd_side': {'raita', 'majjige'},
    #: Drinks. `butter_milk`, `masala_butter_milk` and `boondi_butter_milk` sat in
    #: `veg_gravy / mixed_veg_curry` while eight sibling buttermilks were correctly
    #: `welcome_drink`. Note `majjige`/`huli` is NOT here — majjige huli is a
    #: buttermilk curry and belongs in veg_gravy, which is why the token list is
    #: `buttermilk`-shaped rather than `majjige`-shaped.
    'welcome_drink': {'buttermilk', 'lassi', 'juice', 'sharbath', 'sherbat',
                      'sherbet', 'panna', 'jaljeera', 'kokum', 'sambaram',
                      'mojito', 'cooler', 'smoothie', 'milkshake'},
}

#: ``(filed course_type, name-implied course_type)`` pairs that are correct by
#: design, so the whole class is skipped rather than listed row by row.
LEGITIMATE_PAIRS = {
    ('nonveg_main', 'rice'),        # chicken biryani lives in nonveg_main
    ('nonveg_main', 'bread'),       # kotthu parotta with chicken
    ('healthy_rice', 'rice'),       # healthy_rice is itself a rice slot
    ('white_rice', 'rice'), ('curd_rice', 'rice'), ('rice', 'rice'),
    ('dessert', 'rice'),            # kesari bath, rice kheer, mishti pulao
    ('dessert', 'bread'),           # badam puri, bread halwa
    ('dessert', 'rasam'),           # adhirasam
    ('starter', 'bread'),           # bhel puri, pani poori
    ('accompaniment', 'bread'),     # akki papad, dosa chutney
    ('welcome_drink', 'rice'),      # rice sherbat, kokum sharbath
    ('welcome_drink', 'curd_side'), ('welcome_drink', 'sambar'),  # sambaram
    ('welcome_drink', 'rasam'),     # kokum rasam is served as a drink
    ('veg_gravy', 'curd_side'), ('veg_gravy', 'sambar'),          # majjige huli
    # identity pairs
    ('dessert', 'dessert'), ('bread', 'bread'), ('rasam', 'rasam'),
    ('sambar', 'sambar'), ('soup', 'soup'), ('salad', 'salad'),
    ('curd_side', 'curd_side'),
}

#: ``(city, item)`` -> why this specific row is correct despite the mismatch.
ADJUDICATED = {
    ('bangalore', 'sambar_rice'):
        'a rice dish named for its sambar, not a sambar',
    ('chennai', 'sambar_rice'): 'same',
    ('chennai', 'rasam_rice'): 'a rice dish named for its rasam',
    ('bangalore', 'capsicum_pulao_raita'):
        'a raita named for the pulao it accompanies',
    ('bangalore', 'chutney_raita_corn_salad'): 'a corn salad, correctly a salad',
    ('bangalore', 'lemon_rice_chilli_bhaji'):
        'a dry bhaji served WITH lemon rice; the bhaji is the dish',
    ('bangalore', 'mint_rice_chutney'): 'a chutney, correctly an accompaniment',
    ('bangalore', 'pepper_rice_chutney'): 'likewise',
    ('bangalore', 'veg_raita_masala_papad'):
        'masala papad served with raita; the papad is the dish',
    ('ncr', 'dal_rasam'):
        'a dal-based thin curry (key_ingredient dal, sub_category leafy_dal); '
        'filed as dal by its base — NCR runs no rasam station',
    ('ncr', 'sambar_masala'):
        'a sambar-spiced dal, filed as dal by its base; NCR is a North list '
        'with no sambar station',
    ('ncr', 'masala_raita_aam_panna'):
        'a masala raita (is_raita=1); aam panna is a modifier in the name, the '
        'dish is the raita — correctly curd_side',
}


def unservable_rows(df: pd.DataFrame):
    """Rows that no slot can ever serve, found structurally rather than by name.

    `PoolBuilder._nonveg_mask` drops any row with a non-veg `primary_protein` from
    every slot except `nonveg_main`. So a row carrying a non-veg protein while its
    `course_type` is something else is dropped from its own pool and never joins
    nonveg_main either — it simply cannot appear on a menu.

    `egg_fried_rice` was exactly this: course_type `rice`, primary_protein `egg`,
    silently unservable. Every chicken biryani in the master is `nonveg_main` for
    this reason; that one row missed the convention. No name check would find it —
    the name is perfectly descriptive — which is why this check is structural.
    """
    from src.constants import NONVEG_PROTEINS, NONVEG_SLOT
    prot = df['primary_protein'].astype(str).str.strip().str.lower()
    course = df['course_type'].astype(str).str.strip().str.lower()
    bad = df[prot.isin(NONVEG_PROTEINS) & (course != NONVEG_SLOT)]
    return [(str(r['item']), str(r['course_type']), str(r['primary_protein']))
            for _i, r in bad.iterrows()]


def audit_city(df: pd.DataFrame, city: str):
    """Return ``(unadjudicated, allowed)`` lists of ``(item, filed, implied)``."""
    ct = df['course_type'].astype(str).str.strip().str.lower()
    nm = df['item'].astype(str).str.strip().str.lower()
    unadjudicated, allowed = [], []
    for i in range(len(df)):
        tokens = set(nm.iloc[i].split('_'))
        for course, signal in NAME_SIGNALS.items():
            if not (tokens & signal) or ct.iloc[i] == course:
                continue
            row = (nm.iloc[i], ct.iloc[i], course)
            if (ct.iloc[i], course) in LEGITIMATE_PAIRS:
                allowed.append(row + ('by-design pair',))
            elif (city, nm.iloc[i]) in ADJUDICATED:
                allowed.append(row + (ADJUDICATED[(city, nm.iloc[i])],))
            else:
                unadjudicated.append(row)
    return unadjudicated, allowed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--verbose', action='store_true',
                    help='also list the mismatches that were allowed, and why')
    args = ap.parse_args(argv)

    total = 0
    for fname in sorted(f for f in os.listdir(CITY_ITEMS) if f.endswith('.xlsx')):
        city = os.path.splitext(fname)[0]
        df = pd.read_excel(os.path.join(CITY_ITEMS, fname))
        bad, ok = audit_city(df, city)
        orphans = unservable_rows(df)
        total += len(bad) + len(orphans)
        print(f'{city}: {len(bad)} unadjudicated, {len(ok)} allowed, '
              f'{len(orphans)} unservable')
        for item, course, protein in orphans:
            print(f'  UNSERVABLE {item:36s} course={course:14s} '
                  f'protein={protein} — non-veg outside nonveg_main is dropped '
                  f'from every pool')
        for item, filed, implied in bad:
            print(f'  MISMATCH {item:38s} filed {filed:14s} name says {implied}')
        if args.verbose:
            for item, filed, implied, why in ok:
                print(f'    ok     {item:38s} {filed:14s} vs {implied:11s} — {why}')

    if total:
        print(f'\n{total} unadjudicated mismatch(es). Either the row is misfiled — '
              f'fix it in scripts/course_type_corrections.py — or it is fine, in '
              f'which case add it to ADJUDICATED here WITH THE REASON.',
              file=sys.stderr)
        return 1
    print('\nno unadjudicated mismatches')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
