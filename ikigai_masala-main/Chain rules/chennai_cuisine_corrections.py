#!/usr/bin/env python3
"""Chennai's savoury dishes mislabelled `cuisine_family = continental`.

The same defect `ncr_cuisine_corrections.py` fixed for NCR, in Chennai. The
mapping pipeline tagged 32 plainly-Indian dishes in cuisine-main slots
`continental`, and `ThemeSlotFilterRule._exclude_offtheme_cuisines` drops a
continental dish on every day that is not a continental day. **No Chennai client
themes any day continental**, so all 32 were unservable: sitting in the pool,
passing every diagnostic, never chosen.

Found by rolling World Bank four weeks and watching a rule relax rather than
fail. Its stated lineup is "chicken gravys, chicken biryani, boiled egg and Bone
Salna daily"; by week three the counter served a chicken gravy on three days of
five and filled the gaps with an egg dosa. Chennai looks like it has 25 chicken
gravies — it had 13, because the other 12 were tagged continental.

Every row corrected **contradicts itself**, which is what makes this a data fix
rather than a judgement: a `chicken_north_masala` is not continental, and the
`sub_category` is the column that says so. The retag follows it:

  * `chicken_north_masala` / `chicken_north_creamy` / `chicken_tandoor`
        -> `north_indian`   (11 rows: butter_chicken, chicken_kurma, …)
  * `chicken_south_coastal`
        -> `south_indian`   (1 row: pepper_chicken_curry)
  * `pakora_/_bajji`
        -> `south_indian`   (17 rows: vada, bonda, masala_vada, the 65 family)
  * `mushroom_stir_in_pepper`
        -> `south_indian`   (1 row: mushroom_pepper_fry, a Chettinad pepper fry)

`pakora_/_bajji` is the one where the sub_category does not name a region, so the
dish names decide: vada, vadai, bonda, masala vada and the `65` family are Tamil
tiffin, and this is the Chennai list. It is also the more robust direction —
`starter` is NOT in chennai.json's `exempt_slots`, so the tag decides which
themed days can serve them, and Chennai's counters run more south days than
north.

**Left continental on purpose**, because they really are: the four pasta rows
(`penne_alfredo`, `red_sauce_pasta`, `veg_pasta`, `indian_style_pasta`) and
`veg_roll`, a cutlet — Bangalore files 12 of its 13 `cutlet_/_croquette` rows
continental and this follows the master. Salads, soups, desserts and bread are
untouched whatever their tag: they are not cuisine-main slots, so the
exclusivity filter never looks at them.

NOT FIXED HERE, and worth its own pass: **Bangalore has the same defect at a
larger scale** — 53 of its 87 `chicken_north_masala` rows and 52 of its 95
`pakora_/_bajji` rows are tagged continental. The blast radius there is
different, because Bangalore clients DO run continental days (Booking.com and
Stripe theme a Tuesday, Amadeus alternates), so correcting it moves dishes off
those menus as well as onto the others. That is a menu change to review, not a
dead-row cleanup. See docs/pending_config_changes.md.

Idempotent; re-run after any re-import. `tests/cities/test_chennai_cuisine.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY = ROOT / "data" / "raw" / "city_items" / "chennai.xlsx"

#: Only these slots are cuisine-filtered at all
#: (`theme_rules._CUISINE_MAIN_SLOTS`). A continental salad or soup is nobody's
#: problem — the filter never looks at those courses.
CUISINE_MAIN_SLOTS = {"rice", "veg_gravy", "veg_dry", "starter", "nonveg_main"}

#: `sub_category` -> the region it names. The row already carries the answer.
BY_SUB_CATEGORY: Dict[str, str] = {
    "chicken_north_masala": "north_indian",
    "chicken_north_creamy": "north_indian",
    "chicken_tandoor": "north_indian",
    "chicken_south_coastal": "south_indian",
    "mushroom_stir_in_pepper": "south_indian",
    # Does not name a region, so the dish names do: vada, vadai, bonda, masala
    # vada and the `65` family are Tamil tiffin, and this is the Chennai list.
    "pakora_/_bajji": "south_indian",
}

#: Rows that ARE continental and stay. Named individually so the list is a
#: decision rather than a gap in the mapping above.
KEEP_CONTINENTAL: List[str] = [
    "penne_alfredo", "red_sauce_pasta",     # rice slot, genuinely pasta
    "veg_pasta", "indian_style_pasta",      # veg_gravy, likewise
    "veg_roll",                             # a cutlet; the master files these continental
]


def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename: `to_excel` truncates the target before
    streaming into it, so an interrupted run leaves a 0-byte workbook."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)


def _norm(v) -> str:
    return str(v).strip().lower()


def corrections(df: pd.DataFrame):
    """[(item, sub_category, new cuisine)] this pass would apply."""
    keep = {_norm(x) for x in KEEP_CONTINENTAL}
    out = []
    for idx, row in df.iterrows():
        if _norm(row.get("cuisine_family")) != "continental":
            continue
        if _norm(row.get("course_type")) not in CUISINE_MAIN_SLOTS:
            continue
        if _norm(row.get("item")) in keep:
            continue
        want = BY_SUB_CATEGORY.get(_norm(row.get("sub_category")))
        if want:
            out.append((idx, str(row["item"]), _norm(row.get("sub_category")), want))
    return out


def apply(df: pd.DataFrame):
    fixed = corrections(df)
    for idx, _item, _sub, want in fixed:
        df.at[idx, "cuisine_family"] = want
    return [(i, s, w) for _idx, i, s, w in fixed]


def unresolved(df: pd.DataFrame) -> List[str]:
    """Continental rows in a cuisine-main slot this pass leaves alone.

    Everything here is either on `KEEP_CONTINENTAL` or carries a `sub_category`
    the mapping does not name — the second kind is what a re-import would add,
    and it is reported rather than guessed at.
    """
    keep = {_norm(x) for x in KEEP_CONTINENTAL}
    left = []
    for _idx, row in df.iterrows():
        if _norm(row.get("cuisine_family")) != "continental":
            continue
        if _norm(row.get("course_type")) not in CUISINE_MAIN_SLOTS:
            continue
        if _norm(row.get("item")) in keep:
            continue
        if _norm(row.get("sub_category")) not in BY_SUB_CATEGORY:
            left.append(f"{row['item']} ({row.get('sub_category')})")
    return left


def main(dry_run: bool = False) -> int:
    df = pd.read_excel(CITY)
    df.columns = [c.strip() for c in df.columns]
    fixed = apply(df)
    left = unresolved(df)

    if fixed:
        print(f"[chennai] retagged {len(fixed)} row(s) off continental:")
        for item, sub, want in fixed:
            print(f"    {item:<28} {sub:<24} -> {want}")
    else:
        print("[chennai] no continental mislabels in a cuisine-main slot")
    if left:
        print(f"    ! {len(left)} continental row(s) with an unmapped "
              f"sub_category, left alone: {left}")

    if not fixed:
        return 0
    if dry_run:
        print("[dry-run] nothing written")
        return 0
    _atomic_to_excel(df, CITY)
    print(f"[chennai] wrote {CITY.name}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
