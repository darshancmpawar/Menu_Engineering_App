#!/usr/bin/env python3
"""Precompute ``{city: [client pool tokens]}`` so /editor-metadata need not parse
every workbook.

The editor's first request asks one small question — which per-client pool tokens
exist, per city — and answering it cost **4.8 seconds**: three workbooks, 4,956
rows, fully parsed by openpyxl, to produce about eight short strings per city.
Reading only the `client` column does not help (openpyxl parses the whole sheet
regardless; measured at 1.1x), and the request cannot be scoped either, because
the editor fetches metadata before the user has chosen a city.

So the answer is cached on disk instead. It is a derived artefact, which means it
can go stale — the mitigation is that `tests/test_pool_token_map.py` recomputes it
from the workbooks and fails if the committed file disagrees. Re-run this after any
re-import, alongside the correction scripts; the source_workbooks README lists it.

Usage:
    python scripts/build_pool_token_map.py [--check]

``--check`` writes nothing and exits non-zero if the committed map is stale, which
is what CI and the test use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ontology.paths import CITY_ITEMS_DIR, city_excel_path  # noqa: E402
from src.preprocessor.client_pool_filter import available_pool_tokens  # noqa: E402

OUTPUT = os.path.join(str(CITY_ITEMS_DIR), 'pool_tokens.json')


def compute() -> dict:
    """``{city_slug: sorted tokens}`` keyed by the resolved workbook, not the city.

    Keyed by workbook basename because several cities share one file — Hyderabad
    and NCR both resolve to bangalore.xlsx — and holding one entry per city would
    invite them to drift apart while describing the same rows.
    """
    import pandas as pd
    out = {}
    for fname in sorted(os.listdir(str(CITY_ITEMS_DIR))):
        if not fname.endswith('.xlsx'):
            continue
        df = pd.read_excel(os.path.join(str(CITY_ITEMS_DIR), fname))
        out[fname] = sorted(available_pool_tokens(df))
    return out


def load() -> dict | None:
    """The committed map, or None when it is absent or unreadable.

    Absent is not an error: callers fall back to computing from the workbooks, so
    a fresh checkout that has not run this script is slow, never wrong.
    """
    try:
        with open(OUTPUT, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def tokens_for_city(city) -> list | None:
    """Tokens for one city from the committed map, or None if unavailable."""
    data = load()
    if not data:
        return None
    return data.get(os.path.basename(city_excel_path(city)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true',
                    help='write nothing; exit 1 if the committed map is stale')
    args = ap.parse_args(argv)

    fresh = compute()
    committed = load()

    if args.check:
        if committed == fresh:
            print(f'up to date ({len(fresh)} workbook(s))')
            return 0
        print('STALE — re-run scripts/build_pool_token_map.py', file=sys.stderr)
        for k in sorted(set(fresh) | set(committed or {})):
            if (committed or {}).get(k) != fresh.get(k):
                print(f'  {k}: committed={(committed or {}).get(k)} '
                      f'actual={fresh.get(k)}', file=sys.stderr)
        return 1

    with open(OUTPUT, 'w', encoding='utf-8') as fh:
        json.dump(fresh, fh, indent=2, sort_keys=True)
        fh.write('\n')
    for k, v in sorted(fresh.items()):
        print(f'  {k:18s} {len(v)} token(s): {v}')
    print(f'\nwrote {os.path.relpath(OUTPUT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
