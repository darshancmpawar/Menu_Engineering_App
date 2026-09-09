"""Find rows whose NAME is their own category — the mapping pipeline's fingerprint.

`remove_generic_rows.py` deletes a hand-listed set of rows named for a category
rather than a dish (`sweet`, `veg_gravy`, `salad`, and the misspelled
`chuteny` / `samber`). A hand-listed set only ever catches what someone already
noticed, and the three misspellings proved it: each escaped for years because
the typo is not the word the list searches for.

The obvious generalisation is a fuzzy pass — flag anything within edit distance
2 of a category name. **Measured, that does not work here.** Indian dish names
are short and collide heavily: at distance 2 it flags `adai`->`dal`,
`puri`->`curd`, `lime`->`rice`, `pav`->`dal`, `sev`->`veg`, all real dishes, and
at distance 1 it finds nothing the hand list has not already removed. A guard
that cries wolf gets deleted, so it is not worth adding.

This is the signal that does work, and it is structural rather than lexical: a
row whose single-token NAME equals its own `key_ingredient`, `course_type` or
`sub_category` is describing itself rather than naming a dish. That is exactly
the shape the mapping pipeline leaves behind — CLAUDE.md records
`key_ingredient` being copied from the first word of the name in several places,
and `samber` was `course_type: dal` with `key_ingredient: samber`.

**Report only.** It changes nothing: several hits are legitimate (`curd`,
`papad`, `pickle` are fixed condiments the client asked to keep; `roti`,
`halwa`, `kheer` are real dishes that happen to be single words). Deciding which
of the rest is junk, which is misfiled and which is fine is a menu question for
the client, so the output is a CSV to hand them. `ADJUDICATED` records the ones
already settled, so re-running only ever surfaces what is new.

Usage::

    python scripts/audit_self_named_rows.py            # rewrite the CSV
    python scripts/audit_self_named_rows.py --check    # fail if it is stale
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.city_list import CITIES                          # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CITY_ITEMS = os.path.join(_ROOT, 'data', 'raw', 'city_items')
REPORT = os.path.join(_ROOT, 'docs', 'self_named_rows.csv')

# Settled: a single-word name that IS the dish, or a condiment the client asked
# to keep. Keyed by name only — a dish called `curd` is the same decision in
# every city that carries it.
ADJUDICATED = {
    # Fixed condiments, deliberately kept (see remove_generic_rows.py).
    'curd': 'fixed condiment, client asked to keep',
    'papad': 'fixed condiment, client asked to keep',
    'pickle': 'fixed condiment, client asked to keep',
    'ghee': 'fixed condiment',
    'boondi': 'fixed condiment',
    # Real dishes whose name happens to be one word.
    'raita': 'a dish, not the category — the category is curd_side',
    'rasam': 'the plain rasam; the category is rasam and the dish exists',
    'sambar': 'the plain sambar; likewise',
    'roti': 'the plain roti',
    'thepla': 'a dish',
    'uthappam': 'a dish',
    'lassi': 'a dish',
    'thandai': 'a dish',
    'quinoa': 'a healthy-rice dish',
    'broccoli': 'a salad',
    'bruschetta': 'a starter',
    'banana': 'served as a dessert fruit',
    'imarti': 'a sweet',
    'rajbhog': 'a sweet',
    'burfi': 'a sweet',
    'bhaji': 'a dish (Maharashtrian)',
    'dal': 'the plain dal (Pune)',
    'curd_rice': 'a dish; only near its category, not equal to it',
    'infused_water': 'a welcome drink',
}


def _self_named(df: pd.DataFrame) -> pd.Series:
    """Rows whose one-word name equals their own category or key ingredient."""
    name = df['item'].astype(str).str.strip().str.lower()
    single = ~name.str.contains('_')
    same = pd.Series(False, index=df.index)
    for col in ('key_ingredient', 'course_type', 'sub_category'):
        if col in df.columns:
            same |= (df[col].astype(str).str.strip().str.lower() == name)
    return single & same


def audit():
    """Return the unadjudicated hits as a list of dicts, city by city."""
    rows = []
    for city in CITIES:
        path = os.path.join(CITY_ITEMS, f'{city}.xlsx')
        if not os.path.exists(path):
            continue
        df = pd.read_excel(path)
        hit = df[_self_named(df)]
        for _i, r in hit.iterrows():
            name = str(r['item']).strip().lower()
            if name in ADJUDICATED:
                continue
            rows.append({
                'city': city,
                'item': name,
                'course_type': str(r.get('course_type', '')).strip(),
                'sub_category': str(r.get('sub_category', '')).strip(),
                'key_ingredient': str(r.get('key_ingredient', '')).strip(),
                'client': str(r.get('client', '')).strip(),
            })
    rows.sort(key=lambda d: (d['city'], d['item']))
    return rows


FIELDS = ['city', 'item', 'course_type', 'sub_category', 'key_ingredient',
          'client']


def render(rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true',
                    help='fail if the committed CSV is stale')
    args = ap.parse_args(argv)

    rows = audit()
    text = render(rows)
    if args.check:
        current = open(REPORT, encoding='utf-8').read() if os.path.exists(REPORT) else ''
        if current != text:
            print(f'{REPORT} is stale — re-run this script', file=sys.stderr)
            return 1
        print(f'{REPORT} is current ({len(rows)} open row(s))')
        return 0

    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write(text)
    by_city = {}
    for r in rows:
        by_city[r['city']] = by_city.get(r['city'], 0) + 1
    print(f'{len(rows)} unadjudicated self-named row(s) -> {REPORT}')
    for city, n in sorted(by_city.items()):
        print(f'  {city}: {n}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
