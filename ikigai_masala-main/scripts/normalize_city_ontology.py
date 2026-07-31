#!/usr/bin/env python3
"""Normalise a city's raw menu workbook into the reference ontology format.

Each city has its own item list (``data/raw/city_items/<city>.xlsx``) and the
solver picks one per client from ``clients.city``. A city workbook arrives from
the ops team in whatever shape the spreadsheet happened to have, so this script
is the single place that turns it into the reference format instead of hand
edits nobody can review:

* column set + order forced to the reference ontology's (``bangalore.xlsx``);
  a missing column is added empty, an unknown column is dropped with a report
* ``is_*`` flag columns coerced to 0/1 ints (blank/NaN → 0), so a rule
  selector never has to cope with ``"1.0"`` or ``"yes"``
* text columns trimmed
* the ``client`` pool column set to ``--client-pool`` (default ``common``)

Why the ``client`` default is ``common``: that column is the F5 per-client pool
tag *within one city's* ontology. A city workbook that tags every row with the
same single token carries no per-client information, and a client configured
with ``source_pools = []`` (common-only, the default) would then see zero
items. Pass ``--client-pool keep`` to leave the column untouched once a city
really does split its list across several clients.

Nothing is written unless the result validates: the script builds the pools the
way the API does and reports every category the workbook does not cover.

Usage:
    python scripts/normalize_city_ontology.py pune ~/Downloads/pune_menu_items.xlsx
    python scripts/normalize_city_ontology.py pune src.xlsx --sheet Sheet1 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.constants import BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS  # noqa: E402
from src.preprocessor.column_mapper import ColumnMapper  # noqa: E402
from src.preprocessor.data_cleanser import DataCleanser  # noqa: E402
from src.preprocessor.pool_builder import PoolBuilder  # noqa: E402

CITY_ITEMS_DIR = REPO_ROOT / 'data' / 'raw' / 'city_items'
REFERENCE_CITY = 'bangalore'

_TRUTHY = {'1', '1.0', 'true', 'yes', 'y', 't'}


def _coerce_flag(value) -> int:
    """0/1 for a flag cell. Blank, NaN and anything unrecognised → 0."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    text = str(value).strip().lower()
    if not text or text in ('nan', 'none'):
        return 0
    return 1 if text in _TRUTHY else 0


def normalize(
    src: pd.DataFrame, reference: pd.DataFrame, client_pool: str = 'common',
) -> tuple:
    """Return ``(normalised_df, report)`` — pure, so it is unit-testable."""
    report = {
        'rows': len(src),
        'missing_columns': [c for c in reference.columns if c not in src.columns],
        'extra_columns': [c for c in src.columns if c not in reference.columns],
        'coerced_flag_columns': [],
        'duplicate_item_ids': 0,
    }

    out = pd.concat(
        [
            (
                src[col].reset_index(drop=True)
                if col in src.columns
                else pd.Series([pd.NA] * len(src), name=col)
            ).rename(col)
            for col in reference.columns
        ],
        axis=1,
    )

    # Flag columns: the ontology's contract is "0 or 1", and rule selectors read
    # them with pd.to_numeric. A float column of NaN/1.0 works by accident; an
    # Excel "Yes" does not.
    for col in out.columns:
        if not col.startswith('is_'):
            continue
        coerced = out[col].map(_coerce_flag).astype('int64')
        # Report only the columns the coercion actually changed, so the report
        # names the data that needed fixing instead of listing all ~100 flags.
        original = pd.to_numeric(out[col], errors='coerce').fillna(0).astype('int64')
        if not original.equals(coerced):
            report['coerced_flag_columns'].append(col)
        out[col] = coerced

    for col in out.columns:
        if col.startswith('is_'):
            continue
        if out[col].dtype == object or str(out[col].dtype).startswith('str'):
            out[col] = out[col].map(
                lambda v: v.strip() if isinstance(v, str) else v
            )

    if client_pool != 'keep':
        out['client'] = client_pool

    if 'item_id' in out.columns:
        report['duplicate_item_ids'] = int(out['item_id'].duplicated().sum())

    return out, report


def covered_categories(df: pd.DataFrame) -> tuple:
    """``(covered, missing)`` base slots for a normalised ontology.

    Runs the real preprocessing chain so what is reported is what the solver
    will see, not what the raw ``course_type`` column suggests.
    """
    mapper = ColumnMapper()
    raw = df.copy()
    mapper.detect(raw)
    validation = mapper.validate()
    if not validation['valid']:
        raise ValueError(validation['error'])
    cleaned = DataCleanser(mapper.apply(raw)).clean()
    pools = PoolBuilder.build_pools(cleaned, required_slots=set())
    covered, missing = [], []
    for slot in BASE_SLOT_NAMES:
        if len(pools.get(slot, [])) > 0:
            covered.append(slot)
        elif slot not in DEFAULT_OFF_SLOTS:
            missing.append(slot)
    return covered, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('city', help="city slug, e.g. 'pune' (output filename)")
    ap.add_argument('source', help='raw workbook to normalise')
    ap.add_argument('--sheet', default=0, help='sheet name or index (default: first)')
    ap.add_argument(
        '--client-pool', default='common',
        help="value for the `client` pool column, or 'keep' (default: common)",
    )
    ap.add_argument(
        '--reference', default=str(CITY_ITEMS_DIR / f'{REFERENCE_CITY}.xlsx'),
        help='reference ontology whose column set is the target format',
    )
    ap.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    args = ap.parse_args(argv)

    city = args.city.strip().lower()
    sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet

    reference = pd.read_excel(args.reference)
    src = pd.read_excel(args.source, sheet_name=sheet)
    out, report = normalize(src, reference, client_pool=args.client_pool)

    print(f"source          : {args.source} (sheet={sheet!r})")
    print(f"rows            : {report['rows']}")
    print(f"columns         : {len(out.columns)} (reference format)")
    if report['missing_columns']:
        print(f"added empty     : {report['missing_columns']}")
    if report['extra_columns']:
        print(f"dropped         : {report['extra_columns']}")
    if report['coerced_flag_columns']:
        print(f"flags coerced   : {report['coerced_flag_columns']}")
    if report['duplicate_item_ids']:
        print(f"!! duplicate item_id rows: {report['duplicate_item_ids']}")

    covered, missing = covered_categories(out)
    print(f"categories      : {len(covered)} covered — {', '.join(covered)}")
    if missing:
        print(f"NOT covered     : {', '.join(missing)}")
        print("                  (declare the covered set in "
              "data/raw/city_items/ontology_categories.json so loading this "
              "ontology does not fail the mandatory-slot check)")

    dest = CITY_ITEMS_DIR / f'{city}.xlsx'
    if args.dry_run:
        print(f"dry run         : would write {dest}")
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_excel(dest, index=False)
    print(f"wrote           : {dest}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
