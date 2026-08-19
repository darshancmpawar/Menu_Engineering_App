#!/usr/bin/env python3
"""One dish, one spelling: fold minority transliterations in dish NAMES.

The Bangalore list writes the same word two ways, and the split is lopsided
enough that one side is plainly the house spelling:

    chana  153 rows   vs  channa  16 rows
    kadhi   13 rows   vs  kadi     2 rows

Both minorities are the same word, not a different dish, so the ontology is
carrying near-duplicate names — `channa_chaat_salad` beside 153 `chana_*` rows,
`kadi_pakoda` beside `kadhi_pakodi`. That has two costs beyond tidiness:

* a selector on the name misses half the family. `name_contains: ["kadhi"]` —
  the escape hatch the rule grammar offers when a column is untrustworthy —
  never sees `kadi_pakoda` or `sol_kadi`.
* it de-stabilises menu imports. `menu_import.SPELLING` maps an incoming
  `channa` to `chana`; with both spellings alive in the ontology the fold reads
  the pair as two real words and keeps them apart, so a re-import adds a second
  row for a dish that is already there. Booking's import went from 0 new dishes
  to 9 for exactly this reason.

Deliberately NOT folded: **`chapatti` (34) vs `chapati` (14)**. Both are
ordinary transliterations with real weight behind them, and these names get
printed on a menu — picking a winner there is the client's call, not a
migration's. It is listed in `KNOWN_SPLITS` so the next person can see it was
considered rather than missed.

A rename that would collide with an existing name is reported and skipped, never
applied: two dishes must not be merged by a spelling migration (that is the
mistake `ncr_fuzzy_unmerge.py` had to reverse). Runs across every city.

Idempotent; re-run after any re-import. `tests/data/test_canonical_spellings.py`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CITIES = ("bangalore", "pune", "chennai", "ncr")

from menu_import import CANONICAL_SPELLINGS  # noqa: E402

#: The vocabulary lives in `menu_import.CANONICAL_SPELLINGS` — one source of
#: truth, because this script renames the WORKBOOK to the house spelling while
#: the importer rewrites every INCOMING name to it, and the two halves must not
#: disagree. Split across two lists, each import silently adds a second row for
#: a dish already present.
CANONICAL = dict(CANONICAL_SPELLINGS)

#: Splits looked at and left alone, with the count that decided it. Kept so the
#: judgement is visible rather than looking like an oversight.
KNOWN_SPLITS = {
    ("chapatti", "chapati"): "34 vs 14 — both ordinary transliterations, and "
                             "the name is printed on the menu; the client picks",
}

#: city -> {row to drop: the row it duplicates}. A rename that would collide is
#: never applied automatically; each of these was compared column by column
#: first and is the SAME dish written twice:
#:
#:   black_channa_pulao / black_chana_pulao  both rice, north_indian; the
#:       `channa` row is the bare stub the Booking import created and carries no
#:       sub_category, key_ingredient or colour, while the `chana` row is fully
#:       attributed.
#:   palak_kadi / palak_kadhi                both dal, leafy_dal, key palak.
#:   kadi_pakdoa / kadi_pakoda               both dal, leafy_dal, key kadi;
#:       `pakdoa` is a typo of `pakoda`.
#:   subz_nawabi_hundi / subz_nawabi_handi   both veg_gravy, north_indian; the
#:       `hundi` row is the bare stub the Booking import created (no
#:       sub_category, key_ingredient or colour), the `handi` row is complete.
#:
#: The dropped row's `client` tokens are merged into the survivor, so no client
#: silently loses a dish it makes.
DUPLICATES = {
    "bangalore": {"black_channa_pulao": "black_chana_pulao",
                  "subz_nawabi_hundi": "subz_nawabi_handi",
                  # both bread, north_indian; the `lacha` row is the Booking
                  # import's bare stub, the `laccha` row is `common` and
                  # fully attributed (layered_paratha, brown).
                  "lacha_paratha": "laccha_paratha"},
    "ncr": {"palak_kadi": "palak_kadhi",
            "kadi_pakdoa": "kadi_pakoda"},
}

#: >= this many clients make it -> the merged row becomes `common`
COMMON_AT = 6


def _rx(token: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9]){token}(?![a-z0-9])")


def canonical_name(name: str) -> str:
    out = str(name).strip().lower()
    for minority, house in CANONICAL.items():
        out = _rx(minority).sub(house, out)
    return out


def _merge_clients(df, keep_idx, drop_row):
    """Fold the dropped row's client tokens into the surviving row."""
    def toks(v):
        return [t.strip() for t in str(v or "").split(",") if t.strip()]

    kept = toks(df.at[keep_idx, "client"])
    if any(t.lower() == "common" for t in kept):
        return
    have = {t.lower() for t in kept}
    for t in toks(drop_row["client"]):
        if t.lower() == "common":
            df.at[keep_idx, "client"] = "common"
            return
        if t.lower() not in have:
            kept.append(t)
            have.add(t.lower())
    df.at[keep_idx, "client"] = ("common" if len(kept) >= COMMON_AT
                                 else ",".join(kept))


def apply(df: pd.DataFrame, city: str = ""):
    """Return (df, renamed, merged, collisions). Safe to call twice."""
    df = df.copy()
    city = city.strip().lower()

    # 1. Drop the adjudicated duplicates first, so the rename that would have
    #    collided with them can go ahead.
    merged = []
    dupes = DUPLICATES.get(city, {})
    if dupes:
        names = df["item"].astype(str).str.strip().str.lower()
        index_by_name = {n: i for i, n in names.items()}
        drop_idx = []
        for loser, winner in dupes.items():
            if loser not in index_by_name or winner not in index_by_name:
                continue
            _merge_clients(df, index_by_name[winner], df.loc[index_by_name[loser]])
            drop_idx.append(index_by_name[loser])
            merged.append((loser, winner))
        if drop_idx:
            df = df.drop(index=drop_idx).reset_index(drop=True)

    # 2. Rename the remaining minority spellings.
    names = df["item"].astype(str).str.strip().str.lower()
    taken = set(names)
    renamed, collisions = [], []
    for idx, old in names.items():
        new = canonical_name(old)
        if new == old:
            continue
        if new in taken:
            # Two rows would become one. Report; never merge without a verdict.
            collisions.append((old, new))
            continue
        df.at[idx, "item"] = new
        taken.discard(old)
        taken.add(new)
        renamed.append((old, new))
    return df, renamed, merged, collisions


def main(dry_run: bool = False):
    total = 0
    for city in CITIES:
        path = CITY_DIR / f"{city}.xlsx"
        if not path.exists():                            # pragma: no cover
            continue
        df = pd.read_excel(path)
        df.columns = [c.strip() for c in df.columns]
        out, renamed, merged, collisions = apply(df, city)
        for old, new in merged:
            print(f"[{city}] merged {old} into {new} (same dish, two spellings)")
        for old, new in renamed:
            print(f"[{city}] {old} -> {new}")
        for old, new in collisions:
            print(f"[{city}] ! {old} -> {new} would collide with an existing "
                  f"dish — left alone, adjudicate by hand")
        if not renamed and not merged:
            print(f"[{city}] nothing to do — {len(collisions)} collision(s)")
            continue
        total += len(renamed)
        if not dry_run:
            _atomic_to_excel(out, path, index=False)
            print(f"[{city}] wrote {path.name} "
                  f"({len(renamed)} renamed, {len(merged)} merged)")
    print(f"\n{total} dish name(s) canonicalised")
    for (a, b), why in KNOWN_SPLITS.items():
        print(f"left split on purpose: {a} / {b} — {why}")
    if dry_run:
        print("[dry-run] nothing written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(dry_run=ap.parse_args().dry_run)


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
