#!/usr/bin/env python3
"""One key format: `item_id` is `MENU######` in every city, on every row.

`item_id` is the ontology's primary key — `filter_eligible` dedupes on it, and
every script that adds a dish allocates "one past the city's highest". Two of
those allocators computed that maximum with `pd.to_numeric`, which coerces
`MENU004360` to NaN; the max of an all-NaN series is nothing, so they fell back
to 1 and stamped bare integers onto the rows they wrote. Sixty-four rows carry
one today — 56 in Chennai (`chennai_client_pools.py`: the kootus, the welcome
drinks, the veg biryanis) and 8 in Pune (`deepen_thin_pools.py`: the chaat
starters and leafy dries).

Nothing has broken yet, because the ids happen not to collide inside a city and
nothing parses the prefix. What makes it worth fixing rather than tolerating is
that it is silently self-perpetuating: the same bad maximum is recomputed on the
next run, so every future addition to those two cities would have started from 1
again and eventually collided with a row already numbered 1. The allocators are
fixed at the source; this repairs what they already wrote.

The new ids continue past the city's real maximum, so they cannot collide with
an existing row. `item_id` is only unique WITHIN a city — Chennai's
`MENU004360` and Bangalore's are different dishes, and always have been — so no
cross-city guarantee is being made or broken here.

Hyderabad's 101 imported rows are renumbered from `HYD######` for the same
reason: one format. The prefix was never wrong (its ids are unique and the
column is opaque) but a second convention is a second thing to know, and the
argument for it — keeping a seeded city's rows out of the master's number space
— does not hold, since Chennai, NCR and Pune already overlap Bangalore's range.

Idempotent: a workbook whose ids already match the format is left alone.
`tests/data/test_item_ids.py`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402

#: The one format. Six digits, matching every id the master ontology shipped.
ID_RE = re.compile(r"^MENU\d{6}$")


def mk_id(n: int) -> str:
    return f"MENU{n:06d}"


def numeric_part(value) -> int | None:
    m = re.search(r"(\d+)", str(value))
    return int(m.group(1)) if m else None


def _atomic_to_excel(frame, path):
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_excel(tmp, index=False)
    tmp.replace(path)


def renumber(df: pd.DataFrame):
    """Return (df, [(old, new, item)]). Safe to call twice."""
    df = df.copy()
    ids = df["item_id"]
    ok = ids.map(lambda v: bool(ID_RE.match(str(v).strip())))
    if ok.all():
        return df, []
    # A workbook whose ids are ALL integers reads back as an int64 column, and
    # pandas refuses to write a string into one. Chennai and Pune happened to
    # be mixed (so `object`) and slipped through; widening first means the
    # repair does not depend on that accident.
    df["item_id"] = df["item_id"].astype(object)
    # Continue past the highest number already in the file, whatever its
    # prefix, so a new id cannot land on an existing row.
    highest = max((numeric_part(v) or 0 for v in ids), default=0)
    changed = []
    for i in df.index[~ok]:
        highest += 1
        old = df.at[i, "item_id"]
        df.at[i, "item_id"] = mk_id(highest)
        changed.append((str(old), mk_id(highest), str(df.at[i, "item"])))
    return df, changed


def main(dry_run: bool = False) -> int:
    total = 0
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                                  # pragma: no cover
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        out, changed = renumber(df)
        if not changed:
            print(f"[{city}] all {len(df)} ids already MENU######")
            continue
        total += len(changed)
        print(f"[{city}] renumbered {len(changed)} id(s)")
        for old, new, item in changed[:4]:
            print(f"    {old:12s} -> {new}  {item}")
        if len(changed) > 4:
            print(f"    ... and {len(changed) - 4} more")
        assert not out["item_id"].duplicated().any(), city
        if not dry_run:
            _atomic_to_excel(out, path)
            print(f"[{city}] wrote {city}.xlsx")
    print(f"\n{total} id(s) normalised" if total else "\nnothing to normalise")
    if dry_run:
        print("[dry-run] nothing written")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
