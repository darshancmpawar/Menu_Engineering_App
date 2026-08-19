#!/usr/bin/env python3
"""**NCR only.** Give NCR a real South Indian bread pool.

NCR is a North Indian list, but a counter may theme a weekday `south` (Junglee
Games runs south on Thursday). The bread cuisine lock then narrows `bread` to
``cuisine_family == south_indian``, and NCR carried exactly **three** such rows:

    idli, idly, malabar_paratha        (and idli/idly are one dish, spelled twice)

`idli` and `idly` are both ``is_rice_bread``, so once week 1 serves
`malabar_paratha` the 20-day cooldown leaves the south day nothing but a
rice-bread. Coupling rule 38 says rice-bread ⇒ liquid rice, and the same cuisine
lock leaves the south day 16 rices of which **none** is liquid (every khichdi is
north Indian). The two demands cannot both hold, so Junglee Games went
INFEASIBLE in week 2 — with no starved slot to point at, because each pool on
its own looked healthy.

Three parts, one concern — make the south day servable:

1. **Retag** the idli/vada rows the mapping pipeline left with no
   ``cuisine_family`` (they carry the same fingerprint as the misfiles
   `ncr_bread_misfiles.py` fixed: blank cuisine, ``key_ingredient`` copied from
   the first word of the name). An idli is not a North Indian bread; today they
   are reachable only on north days, which is backwards. `mini_idli`'s
   ``sub_category`` of `tandoor` is corrected too.
2. **Remove** the duplicate spellings — `idly` is `idli`, and `idly_vada` /
   `idli_medu_vada` / `medu_vada_and_idli` are all `idli_vada`. Four names for
   one dish would make a 15-dish south pool read as idli-vada four ways.
3. **Import** 12 South Indian breads from the Bangalore master — six that are
   NOT rice-bread (so the slot is never *forced* into the coupling chain) and
   six of the dosa/idiyappam family for variety. All are dishes a Delhi kitchen
   makes for a South Indian day.

Rows are copied verbatim (same 135-column schema) with only ``item_id``
reassigned past NCR's max and ``client`` blanked so the row is reachable through
NCR's full-list fallback — exactly what `add_ncr_sambar.py` /
`add_ncr_north_rice.py` do.

Idempotent; re-run after any NCR re-import.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
NCR = CITY_DIR / "ncr.xlsx"
MASTER = CITY_DIR / "bangalore.xlsx"

# 1. Rows already in NCR that are South Indian but carry no cuisine_family.
#    Value = the sub_category to force (None = leave it alone).
RETAG = {
    "idli_vada": "idli_/_steamed",
    "fried_idli": "idli_/_steamed",
    "mini_idli": "idli_/_steamed",   # was `tandoor`, which an idli is not
}

# 2. Duplicate spellings of a dish NCR already carries under another name.
DROP_DUPLICATES = {
    "idly": "idli",
    "idly_vada": "idli_vada",
    "idli_medu_vada": "idli_vada",
    "medu_vada_and_idli": "idli_vada",
}

# 3a. South breads that are NOT is_rice_bread. These are the ones that matter:
#     with any of them available the bread slot is never *forced* onto a
#     rice-bread, so the coupling chain stays a choice rather than a mandate.
SOUTH_BREAD_NON_RICE = [
    "kerala_parotta",
    "ragi_dosa",
    "wheat_dosa",
    "pesarattu",
    "adai",
    "onion_tomato_dosa",
]

# 3b. The dosa/idiyappam family — rice-bread, imported for variety so a south
#     day once a week still has fresh dishes across a 20-day cooldown window.
SOUTH_BREAD_RICE = [
    "plain_dosa",
    "masala_dosa",
    "rava_dosa",
    "uttapam",
    "set_dosa",
    "idiyappam",
]

IMPORT = SOUTH_BREAD_NON_RICE + SOUTH_BREAD_RICE
SOUTH = "south_indian"


def _norm(s) -> str:
    return str(s).strip().lower() if s is not None else ""


def _next_id(df) -> int:
    nums = [int(m.group(1)) for s in df["item_id"].dropna().astype(str)
            for m in [re.search(r"(\d+)", s)] if m]
    return (max(nums) + 1) if nums else 1


def retag(ncr: pd.DataFrame) -> int:
    names = ncr["item"].map(_norm)
    n = 0
    for item, sub in RETAG.items():
        mask = names == item
        if not mask.any():
            continue
        if _norm(ncr.loc[mask, "cuisine_family"].iloc[0]) != SOUTH:
            ncr.loc[mask, "cuisine_family"] = SOUTH
            n += 1
        if sub:
            ncr.loc[mask, "sub_category"] = sub
        # Every idli is a rice bread; two of these rows had the flag at 0.
        ncr.loc[mask, "is_rice_bread"] = 1
    return n


def drop_duplicates(ncr: pd.DataFrame) -> pd.DataFrame:
    names = ncr["item"].map(_norm)
    kept = set(names)
    drop = {d for d, keep in DROP_DUPLICATES.items()
            if d in kept and keep in kept}
    if not drop:
        return ncr
    for d in sorted(drop):
        print(f"  - removing {d} (duplicate of {DROP_DUPLICATES[d]})")
    return ncr[~names.isin(drop)].copy()


def import_breads(master: pd.DataFrame, ncr: pd.DataFrame) -> pd.DataFrame:
    have = set(ncr["item"].map(_norm))
    wanted = [n for n in IMPORT if n not in have]
    if not wanted:
        return ncr
    m_names = master["item"].map(_norm)
    nid = _next_id(ncr)
    rows = []
    for name in wanted:
        src = master[m_names == name]
        if src.empty:
            print(f"  ! {name}: not in the master list, skipped")
            continue
        r = src.iloc[0].copy()
        r["item_id"] = f"MENU{nid:06d}"
        nid += 1
        if "client" in r.index:
            r["client"] = ""          # NCR has no `common`; blank = full-list
        rows.append(r)
        print(f"  + {name}")
    if not rows:
        return ncr
    return pd.concat([ncr, pd.DataFrame(rows)], ignore_index=True)


def _south_bread_report(df: pd.DataFrame) -> str:
    ct = df["course_type"].map(_norm)
    cf = df["cuisine_family"].map(_norm)
    b = df[ct.eq("bread") & cf.eq(SOUTH)]
    rb = pd.to_numeric(b.get("is_rice_bread"), errors="coerce").fillna(0)
    return (f"{len(b)} south bread(s), {int((rb != 1).sum())} of them not "
            f"rice-bread")


def main(dry_run=False):
    master = pd.read_excel(MASTER)
    master.columns = [c.strip() for c in master.columns]
    ncr = pd.read_excel(NCR)
    ncr.columns = [c.strip() for c in ncr.columns]

    print(f"before: {_south_bread_report(ncr)}")
    before_rows = len(ncr)
    n_retag = retag(ncr)
    if n_retag:
        print(f"  ~ retagged {n_retag} idli/vada row(s) to {SOUTH}")
    ncr = drop_duplicates(ncr)
    out = import_breads(master, ncr)
    print(f"after:  {_south_bread_report(out)}  "
          f"({before_rows} -> {len(out)} rows)")

    if dry_run:
        print("[dry-run] nothing written")
        return out
    _atomic_to_excel(out, NCR, index=False)
    print(f"wrote {NCR.name}")
    return out


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
