#!/usr/bin/env python3
"""**NCR only.** Give the north rice slot enough dishes to run without repeating.

Every NCR counter is themed `north` most or all of the week, so `rice` is filtered
to NCR's 23 north-Indian rices. **18 of those 23 are mixed-veg pulao/biryani**,
which `mixedveg_pulao_biryani_weekly` caps at one day a week — so only **5** are
usable for the other four days:

    masala_pulao, navratan_pulao, sabudana_khichdi, tawa_pulao, veg_khichdi

Week 1 spends all five. From week 2 the 20-day cooldown has banned them and the
only rices left belong to the capped family, so the counter has nothing legal to
serve and the solve dies. That is what broke Carelon, Corning, Junglee Games,
SAEL, Siemens and Stryker NCR in week 2, and Airtel Noida in week 3.

A daily slot needs about one distinct dish per working day inside the cooldown
window plus the week being planned (floor(20*5/7) + 5 = 19). This copies 16
vegetarian North-Indian rices from the Bangalore master — pulaos and khichdis a
Delhi kitchen makes — none of them in the capped family, taking the usable count
from 5 to 21.

Rows are copied verbatim (same 135-column schema), with only `item_id`
reassigned past NCR's max and `client` blanked so the row is reachable through
NCR's full-list fallback — exactly what `add_ncr_sambar.py` does.

Idempotent (skips by name); re-run after any NCR re-import.
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

# Sixteen veg North-Indian rices, none in the mixed-veg pulao/biryani family.
# Chosen for spread — rich pulaos, everyday jeera/palak pulaos, and the khichdi
# family — so the slot reads as variety rather than sixteen versions of one dish.
NORTH_RICE = [
    "kaju_pulao",
    "shahi_pulao",
    "shahi_jeera_pulao",
    "kashmiri_pulao_with_fruits",
    "mughlai_pulao",
    "palak_pulao",
    "methi_dum_pulao",
    "aloo_dum_pulao",
    "veg_dum_pulao",
    "pudina_dum_pulao",
    "dal_khichdi",
    "moong_dal_khichdi",
    "masala_khichdi",
    "palak_khichdi",
    "gujarati_khichdi",
    "ghee_khichdi",
]

# Never import these even though they are north rice: `white_rice` and the
# steamed variants belong to the CONST_SLOTS `white_rice` slot, not the flavoured
# rice pool (src.constants.RICE_EXCLUDE_ITEMS exists for exactly that reason).
NEVER = {"white_rice", "basil_steamed_rice", "steamed_rice"}


def _norm(s) -> str:
    return str(s).strip().lower() if s is not None else ""


def _next_id(df) -> int:
    nums = [int(m.group(1)) for s in df["item_id"].dropna().astype(str)
            for m in [re.search(r"(\d+)", s)] if m]
    return (max(nums) + 1) if nums else 1


def add_rice(master: pd.DataFrame, ncr: pd.DataFrame) -> pd.DataFrame:
    have = set(ncr["item"].map(_norm))
    wanted = [n for n in NORTH_RICE if n not in have and n not in NEVER]
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
    if not rows:
        return ncr
    return pd.concat([ncr, pd.DataFrame(rows)], ignore_index=True)


def main(dry_run=False):
    master = pd.read_excel(MASTER)
    master.columns = [c.strip() for c in master.columns]
    ncr = pd.read_excel(NCR)
    ncr.columns = [c.strip() for c in ncr.columns]

    before = (ncr["course_type"].map(_norm) == "rice").sum()
    out = add_rice(master, ncr)
    after = (out["course_type"].map(_norm) == "rice").sum()
    added = sorted(set(out["item"].map(_norm)) - set(ncr["item"].map(_norm)))
    print(f"NCR rice: {before} -> {after}")
    print(f"  added {len(added)}: {', '.join(added) if added else '(none)'}")
    if dry_run:
        print("[dry-run] nothing written")
        return out
    if added:
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
