"""Copy 10 sambar dishes from the Bangalore ontology into the NCR ontology.

NCR is North Indian and its raw list had no servable sambar — `course_type ==
sambar` was empty — so Stryker NCR's "a sambar once every 15 days in the
dal/sambar category" had nothing to serve. The client asked for 10 sambar to be
brought in from the Bangalore master list.

Strictly the list DID contain the word: a row named `samber`, filed
`course_type: dal` with `sub_category: leafy_dal` and `key_ingredient: samber`
— the mapping pipeline's copy-the-first-word fingerprint. It was the category
name misspelled and misfiled, not a dish, so it could never have satisfied the
rule and is now removed by `remove_generic_rows.py`. Recorded here because "the
list carried no sambar" read as a fact about the cuisine when it was really a
fact about a typo, and the next person to check would have found the row and
doubted the import.

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

def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename.

    `to_excel` truncates the target before streaming into it, so an
    interrupted run leaves a 0-byte workbook and the city's item list is
    gone. That happened once; it must not happen twice.
    """
    import pathlib as _pl
    p = _pl.Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)


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
    _atomic_to_excel(out, _NCR, index=False)
    after = int((out['course_type'] == 'sambar').sum())
    print(f"NCR sambar: {before} -> {after} (+{added} row(s) written to {_NCR})")


if __name__ == '__main__':
    main()
