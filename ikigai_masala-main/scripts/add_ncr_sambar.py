"""Copy 10 sambar dishes from the Bangalore ontology into the NCR ontology.

NCR is North Indian and its raw list carried NO sambar (`course_type == sambar`
was empty), so Stryker NCR's "a sambar once every 15 days in the dal/sambar
category" had nothing to serve. The client asked for 10 sambar to be brought in
from the Bangalore master list.

The two workbooks share one 135-column schema, so a sambar row copies verbatim;
only the `item_id` is reassigned to a fresh value beyond NCR's current max so it
never collides with an existing NCR id, and `client` is blanked (NCR has no
`common` pool — every live NCR client plans from the full-list fallback, which
includes untagged rows, so a blank tag reaches every client).

Idempotent: re-running skips sambar already present by name. Re-run after any
NCR re-import (the same as the other correction scripts). `test_ncr_sambar.py`
fails if the 10 are missing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_BLR = _ROOT / 'data' / 'raw' / 'city_items' / 'bangalore.xlsx'
_NCR = _ROOT / 'data' / 'raw' / 'city_items' / 'ncr.xlsx'

# Ten diverse, recognisable vegetable sambars from the Bangalore master list.
SAMBAR_NAMES = [
    'drumstick_sambar', 'brinjal_sambar', 'carrot_sambar', 'beetroot_sambar',
    'cucumber_sambar', 'pumpkin_sambar', 'kerala_sambar', 'ulli_sambar',
    'chow_chow_sambar', 'kottu_sambar',
]


def _next_item_id(ncr: pd.DataFrame) -> int:
    """Highest numeric suffix in NCR's MENU###### ids, + 1."""
    nums = []
    for v in ncr['item_id'].astype(str):
        m = re.match(r'MENU(\d+)', v.strip())
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def add_sambar(blr: pd.DataFrame, ncr: pd.DataFrame) -> pd.DataFrame:
    """Return NCR with the missing sambar appended (pure; no I/O)."""
    blr = blr.copy()
    blr.columns = [c.strip() for c in blr.columns]
    ncr = ncr.copy()
    ncr.columns = [c.strip() for c in ncr.columns]

    present = set(ncr['item'].astype(str).str.strip())
    next_id = _next_item_id(ncr)
    new_rows = []
    for name in SAMBAR_NAMES:
        if name in present:
            continue  # idempotent
        src = blr[blr['item'].astype(str).str.strip() == name]
        if src.empty:
            raise SystemExit(f"Bangalore list has no sambar named {name!r}")
        row = src.iloc[0].to_dict()
        row = {c: row.get(c) for c in ncr.columns}  # align to NCR column order
        row['item_id'] = f'MENU{next_id:06d}'
        row['client'] = ''  # reachable via NCR's full-list fallback
        next_id += 1
        new_rows.append(row)

    if not new_rows:
        return ncr
    return pd.concat([ncr, pd.DataFrame(new_rows)], ignore_index=True)


def main() -> None:
    blr = pd.read_excel(_BLR)
    ncr = pd.read_excel(_NCR)
    before = int((pd.Series(ncr.columns).str.strip().eq('course_type')).any()
                 and (ncr['course_type'] == 'sambar').sum())
    out = add_sambar(blr, ncr)
    added = len(out) - len(ncr)
    out.to_excel(_NCR, index=False)
    after = int((out['course_type'] == 'sambar').sum())
    print(f"NCR sambar: {before} -> {after} (+{added} row(s) written to {_NCR})")


if __name__ == '__main__':
    main()
