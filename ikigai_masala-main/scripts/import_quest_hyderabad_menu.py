#!/usr/bin/env python3
"""Quest (Hyderabad)'s four-month menu grid -> the Hyderabad city ontology.

**This is what makes Hyderabad a city of its own.** Until now `Hyderabad` was in
`AVAILABLE_CITIES` with no workbook, so `city_excel_path` fell back to
Bangalore's — every Hyderabad client planned from the Bangalore list, and any
dish a Hyderabad menu introduced would have had to be written INTO Bangalore's,
where five other cities read it.

The Bangalore list is a better default than it sounds: it already carries bagara
rice, mirchi ka salan, the pappu family, andhra kodi koora and double ka meetha
— it is pan-Indian, not narrowly Bangalorean. What it does not carry is most of
the Telugu vegetable and Telangana chicken vocabulary Quest actually cooks:
`pulihora`, `vankaya`/`dondakaya`/`beerakaya`/`munakkaya`/`dosakaya` curries,
`thotakura` and `menthikoora` pappu, `inti`/`telanagana`/`avakaya` kodi kura,
`kodi pulusu`. Those are the dishes this import adds.

So `hyderabad.xlsx` is SEEDED FROM BANGALORE and this import adds what Quest's
menu has that Bangalore lacks. Seeding rather than starting empty is the whole
point: Quest's grid names 191 distinct dishes, which across eleven slots is
about seventeen each — a `bread` row of ONE dish and a `starter` row of eleven.
Under the 20-day item cooldown a count-1 slot needs roughly one distinct dish per
working day in the window, so a standalone 191-dish city would starve in week
two. (The 25-day sweep watched five real clients fail exactly that way on pools
of five and six.) Bangalore's 6,159 rows plus Quest's 101 additions is a list
that can actually plan.

Two consequences of seeding, both of which had to be fixed rather than accepted:
the ~6,000 inherited rows carry BANGALORE client pool tokens, so Hyderabad must
be in `FULL_POOL_CITIES` or every client narrows to `common` alone; and they
double the corpus the all-cities correction scripts learn from without adding a
fact, which is why `complete_ontology` and `fill_item_colours` now weigh
evidence per DISH rather than per row.

THE SOURCE GRID is one sheet, columns = service days (41 dated, 31 Mar - 30 Jul
2026), rows = menu positions. Two layouts, and they are OFFSET from each other,
which is the thing to get right:

  * **Tue / Thu — the full menu**, rows 2-13: chapati, steamed rice, a flavoured
    rice, a dal, a starter, a veg gravy, then TWO non-veg rows, a yoghurt, a
    salad, a dessert and sometimes a fruit.
  * **Wed — the biryani day**, rows 5-13 and nothing above: chapati, a veg
    gravy, a veg biryani, a chicken biryani, salan, raita, a lachha onion salad,
    a dessert, a fruit.

A column is a biryani day exactly when row 2 is blank, which is what
`_is_biryani_column` tests. Reading every column on the Tue/Thu map would file
the Wednesday veg gravy as a dal and its biryani as a starter.

FOUR SOURCE-SPECIFIC READINGS, each of which would be a silent wrong import:

1. **The two non-veg rows are dry and gravy, in that order.** The upper row is
   kebabs and chilli chicken (`Chicken Kabab`, `Chilly Chicken`, `Tandoori
   Chicken`, `Chicken Manchurian`); the lower is curries (`Butter Chicken`,
   `Chicken Rogan Josh`, `Avakaya Kodi Kura`, `Chicken Chettinadu`). That is
   evidence a name heuristic cannot match, and it matters: a non-veg dish
   carrying neither `is_nonveg_dry` nor a chicken-gravy flag cannot be placed by
   `nonveg_main_daily_pair` at all — it sits in the pool and is never chosen
   (`scripts/nonveg_structural_flags.py`). `style_by_label` feeds the row's own
   label in.

2. **"Chef Choice Desserts" is a placeholder, not a dish.** It appears on 14 of
   the 41 days. A menu printing it tells the diner nothing and no colour,
   ingredient or variety rule can reason about it — the same argument
   `remove_generic_rows.py` makes for a row called "Sweet".

3. **The fruit row is not a slot.** `fruit` is not in `BASE_SLOT_NAMES` or
   `CONST_SLOTS`, and the values are counts ("Banana 2 nos", "Apple 1 nos")
   rather than dishes. Dropped.

4. **"Tossed Salad" is printed in the YOGHURT row** on one Tue/Thu column — a
   slip in the source. `_refile` sends anything whose name ends in `_salad` to
   `salad`, so it lands where it belongs instead of becoming a curd side.

Steamed rice, yoghurt and raita are skipped as const-slot staples every printed
menu repeats daily. `Salan` is imported as a `veg_gravy`: it is the mirchi ka
salan that accompanies a Hyderabadi biryani, it appears on all 14 biryani days,
and the biryani-day veg gravy row is separate from it.

Idempotent — a second run folds every dish onto the row it created and adds
nothing. `tests/cities/test_hyderabad_ontology.py`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.menu_import import (          # noqa: E402
    ImportSpec, refile_lentils, run_import, to_item,
)

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
HYDERABAD = CITY_DIR / "hyderabad.xlsx"
BANGALORE = CITY_DIR / "bangalore.xlsx"
SOURCE = (ROOT / "data" / "raw" / "source_workbooks"
          / "quest_hyderabad_menu_2026.xlsx")

#: Row -> label on a full Tue/Thu column.
REGULAR_ROWS: Dict[int, str] = {
    2: "bread", 3: "white_rice", 4: "rice", 5: "dal", 6: "starter",
    7: "veg_gravy", 8: "nonveg_dry", 9: "nonveg_gravy", 10: "curd_side",
    11: "salad", 12: "dessert", 13: "fruit",
}

#: Row -> label on a Wednesday biryani column. Offset by three and shorter.
BIRYANI_ROWS: Dict[int, str] = {
    5: "bread", 6: "veg_gravy", 7: "rice", 8: "nonveg_biryani", 9: "salan",
    10: "curd_side", 11: "salad", 12: "dessert", 13: "fruit",
}

#: '<block>||<label>' -> course_type. A label absent here is skipped, so this
#: doubles as the list of rows worth importing — which is why `fruit` and
#: `white_rice` are simply not present.
CATEGORY_MAP: Dict[str, str] = {
    "regular||bread": "bread",
    "regular||rice": "rice",
    "regular||dal": "dal",
    "regular||starter": "starter",
    "regular||veg_gravy": "veg_gravy",
    "regular||nonveg_dry": "nonveg_main",
    "regular||nonveg_gravy": "nonveg_main",
    "regular||curd_side": "curd_side",
    "regular||salad": "salad",
    "regular||dessert": "dessert",
    "biryani||bread": "bread",
    "biryani||veg_gravy": "veg_gravy",
    "biryani||rice": "rice",
    "biryani||nonveg_biryani": "nonveg_main",
    "biryani||salan": "veg_gravy",
    "biryani||curd_side": "curd_side",
    "biryani||salad": "salad",
    "biryani||dessert": "dessert",
}

#: The menu's own rows say which non-veg dishes are dry, which are gravies and
#: which are the day's biryani. The third is not redundant with the name: the
#: biryani row prints `Andra Chicken Palvo` and `Hyderabadi Dum Pulao`, and a
#: pulao is not a biryani by name — but a non-veg dish with no form flag cannot
#: be placed by `nonveg_main_daily_pair` at all (`nonveg_structural_flags.py`),
#: so the two would sit in the pool unchosen.
STYLE_BY_LABEL: Dict[str, str] = {
    "regular||nonveg_dry": "dry",
    "regular||nonveg_gravy": "gravy",
    "biryani||nonveg_biryani": "biryani",
}

#: Never import. The const-slot staples every printed menu repeats daily, and
#: the placeholder that is not a dish.
SKIP_ITEMS = {
    "steamed_rice", "steamrice", "steam_rice",
    "yoghurt", "yogurt", "curd", "raitha", "raita",
    "chef_choice_desserts", "chefs_choice_desserts",
}


#: Trailing serving counts. The source writes portions into the dish name —
#: "Coconut Rava Laddu 1 nos", "Banana 2 nos" — and a count is not part of what
#: the dish IS, so the same laddu written without it would become a second row.
_COUNT_TAIL = re.compile(r"[\s_]*\d+\s*nos?\.?\s*$", re.IGNORECASE)


def _clean(name: str) -> str:
    """`to_item`, plus the source's "(SI)" annotations and serving counts."""
    return to_item(_COUNT_TAIL.sub("", str(name).strip()),
                   drop_parentheticals=True)


def _refile(item: str, course: str) -> str:
    """The lentil re-filing, plus the yoghurt-row slip.

    One Tue/Thu column prints "Tossed Salad" in the yoghurt row. Filed as a
    `curd_side` it would become a yogurt option that is not yogurt, so a dish
    whose own name ends in `_salad` goes to `salad` whatever row printed it.
    """
    if course == "curd_side" and item.endswith("_salad"):
        return "salad"
    return refile_lentils(item, course)


def _is_biryani_column(df: pd.DataFrame, col: int) -> bool:
    """Wednesday columns start three rows lower and leave row 2 blank."""
    return str(df.iat[2, col]).strip() in ("", "nan")


def parse() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = defaultdict(list)
    df = pd.read_excel(SOURCE, sheet_name=0, header=None)
    for col in range(df.shape[1]):
        when = df.iat[1, col]
        if not isinstance(when, (pd.Timestamp, dt.datetime)):
            continue                      # spacer column between month blocks
        biryani = _is_biryani_column(df, col)
        block = "biryani" if biryani else "regular"
        rows = BIRYANI_ROWS if biryani else REGULAR_ROWS
        for row, label in rows.items():
            value = str(df.iat[row, col]).strip()
            if value in ("", "nan"):
                continue
            out[f"{block}||{label}"].append(value)
    return dict(out)


SPEC = ImportSpec(
    client_token="quest",
    city_path=HYDERABAD,
    parse=parse,
    category_map=CATEGORY_MAP,
    style_by_label=STYLE_BY_LABEL,
    skip_items=SKIP_ITEMS,
    clean_name=_clean,
    refile=_refile,
    # `MENU` is the schema's one key format, and the default every other
    # importer takes. An `HYD` prefix looked tidier — a seeded city's own rows
    # kept out of the master's number space — but that guarantee does not exist
    # anyway: `item_id` is unique only WITHIN a city, and Chennai, NCR and Pune
    # already overlap Bangalore's range. A second convention is just a second
    # thing to know. See `scripts/normalize_item_ids.py`.
    id_prefix="MENU",
)


def seed_from_bangalore(dry_run: bool = False) -> bool:
    """Create `hyderabad.xlsx` from Bangalore's list if it does not exist.

    Not a merge: the file is Hyderabad's own from here on, and re-running this
    importer must not re-seed over the dishes it added. Returns True if it
    seeded.
    """
    if HYDERABAD.exists():
        return False
    if dry_run:
        print(f"[dry-run] would seed {HYDERABAD.name} from {BANGALORE.name}")
        return True
    shutil.copyfile(BANGALORE, HYDERABAD)
    print(f"[hyderabad] seeded {HYDERABAD.name} from {BANGALORE.name} "
          f"({len(pd.read_excel(HYDERABAD))} rows)")
    return True


def main(dry_run: bool = False) -> int:
    if not SOURCE.exists():
        print(f"missing source workbook: {SOURCE}")
        return 1
    seed_from_bangalore(dry_run)
    if dry_run and not HYDERABAD.exists():
        print("[dry-run] cannot import before the seed exists")
        return 0
    run_import(SPEC, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
