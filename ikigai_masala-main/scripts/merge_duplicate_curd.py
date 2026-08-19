#!/usr/bin/env python3
"""`plain_curd` and `curd` are the same dish — keep one row, in every city.

Both rows are identical in substance: ``course_type=curd_side``,
``is_plain_curd=1``, ``item_color=white``. Carrying both means the same bowl of
curd competes with itself for a slot, counts twice toward "distinct dishes
available", and can be served on two days of a week as if it were variety.

`curd` is the surviving name, not `plain_curd`, because
:data:`src.constants.REPEATABLE_ITEM_BASES` matches the literal string ``curd``
— that is what exempts the daily curd from `unique_items` and the cooldown.
Keeping `plain_curd` instead would silently switch that staple exemption off.

The client pool tokens are **merged, not dropped**. In NCR the two rows carry
different tokens (``curd`` -> Junglee Games…, ``plain_curd`` -> Airtel Noida), so
deleting `plain_curd` outright would take Airtel Noida's curd away with it. The
survivor inherits the union.

Idempotent; re-run after any re-import. `test_duplicate_curd.py` pins it.
"""
from __future__ import annotations

import argparse
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


ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CITIES = ["bangalore", "pune", "chennai", "ncr"]

KEEP = "curd"
DROP = "plain_curd"


def _norm(s) -> str:
    return str(s).strip().lower() if s is not None else ""


def _tokens(value) -> list:
    if value is None:
        return []
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def merge(df: pd.DataFrame) -> pd.DataFrame:
    names = df["item"].map(_norm)
    keep_m = names == KEEP
    drop_m = names == DROP
    if not drop_m.any():
        return df
    if not keep_m.any():
        # No survivor to merge into: rename the duplicate instead of losing it.
        df = df.copy()
        df.loc[drop_m, "item"] = KEEP
        return df

    df = df.copy()
    if "client" in df.columns:
        merged, seen = [], set()
        for v in list(df.loc[keep_m, "client"]) + list(df.loc[drop_m, "client"]):
            for t in _tokens(v):
                if t.lower() not in seen:
                    seen.add(t.lower())
                    merged.append(t)
        if merged:
            df.loc[keep_m, "client"] = ",".join(merged)
    return df[~drop_m].reset_index(drop=True)


def main(dry_run=False):
    for slug in CITIES:
        path = CITY_DIR / f"{slug}.xlsx"
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        before = len(df)
        out = merge(df)
        if len(out) == before:
            print(f"{slug}: already merged")
            continue
        kept = out[out["item"].map(_norm) == KEEP]
        tok = kept.iloc[0].get("client") if len(kept) else ""
        print(f"{slug}: merged {DROP} -> {KEEP} (client now: {tok})")
        if not dry_run:
            _atomic_to_excel(out, path, index=False)
    if dry_run:
        print("[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)
