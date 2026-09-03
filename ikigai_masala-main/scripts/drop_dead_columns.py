#!/usr/bin/env python3
"""Remove columns that are empty in every city workbook and read by nothing.

`universe` is blank on all 8,787 rows across Bangalore, Chennai, Pune and NCR,
and no module, rule config or script reads it — the only match for the word
anywhere in the repo is a sentence in a test docstring about Pune's client
column. It is a column the master ontology shipped with and nobody ever filled.

An always-empty column is not free: it is one more thing a normaliser has to
carry, one more column a new city's import has to line up, and one more field
someone reading the schema has to decide whether they need. The client asked
for the ontology to be complete, and a column that can never be complete is
better gone than permanently blank.

The schema goes 135 -> 134 columns. `test_course_type_audit.py` pins the count,
so the change is visible rather than silent.

Idempotent: a workbook that no longer has the column is left alone. Refuses to
drop a column that turns out to hold data in any city — this removes dead
weight, not information.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402

#: Columns to remove, each verified empty in every city before anything is
#: written. Add to this list only after checking nothing reads the column.
DEAD_COLUMNS = ("universe",)

#: Numeric columns whose BLANK means zero, listed here so the same cell reads
#: the same way in every city.
#:
#: `richness_score` was 1,022 blanks in NCR and an explicit 0 in the other four,
#: which made it the one column whose dtype differed across the workbooks —
#: float64 where the NaNs were, int64 everywhere else. Nothing reads it (77
#: non-zero rows in Bangalore, 25 in NCR), so this is not a behaviour change; it
#: is the difference between "no score" and "a score of zero" being spelled two
#: ways, which is exactly the kind of drift a five-city schema should not carry.
#:
#: It does NOT qualify for DEAD_COLUMNS: it holds real values in every city, so
#: dropping it would lose data however unused it is today.
ZERO_FILL_COLUMNS = ("richness_score",)


def _atomic_to_excel(frame, path):
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def main(dry_run: bool = False):
    frames = {}
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                              # pragma: no cover
            continue
        d = pd.read_excel(path)
        d.columns = [c.strip() for c in d.columns]
        frames[city] = d

    # Verify emptiness across EVERY city before touching any of them. A column
    # holding data anywhere is not dead, whatever the others say.
    droppable = []
    for col in DEAD_COLUMNS:
        holders = {c: int(d[col].notna().sum())
                   for c, d in frames.items() if col in d.columns}
        if not holders:
            print(f"{col}: already gone from every workbook")
            continue
        nonempty = {c: n for c, n in holders.items() if n}
        if nonempty:
            print(f"{col}: REFUSED — holds data in {nonempty}")
            continue
        print(f"{col}: empty in {sorted(holders)} ({sum(holders.values())} values)")
        droppable.append(col)

    # Blank-vs-zero, independent of the drops above: a column can need this
    # while being far from dead.
    zero_filled = {}
    for col in ZERO_FILL_COLUMNS:
        for city, d in frames.items():
            if col not in d.columns:                       # pragma: no cover
                continue
            blanks = int(d[col].isna().sum())
            if not blanks:
                continue
            d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0)
            if d[col].eq(d[col].round()).all():
                d[col] = d[col].astype("int64")
            zero_filled.setdefault(city, []).append(f"{col} ({blanks})")
    for city, cols in zero_filled.items():
        print(f"[{city}] zero-filled {', '.join(cols)}")
        if not dry_run:
            _atomic_to_excel(frames[city], CITY_DIR / f"{city}.xlsx")
            print(f"[{city}] wrote {city}.xlsx")
    if not zero_filled:
        print("no blank numeric cells to zero-fill")

    if not droppable:
        print("nothing to drop")
        return

    for city, d in frames.items():
        present = [c for c in droppable if c in d.columns]
        if not present:
            continue
        out = d.drop(columns=present)
        print(f"[{city}] {len(d.columns)} -> {len(out.columns)} columns")
        if not dry_run:
            _atomic_to_excel(out, CITY_DIR / f"{city}.xlsx")
            print(f"[{city}] wrote {city}.xlsx")
    if dry_run:
        print("[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
