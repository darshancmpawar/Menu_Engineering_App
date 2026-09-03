#!/usr/bin/env python3
"""Flags that must mean the same thing in both directions, derived from the name.

A flag that is only ever *set* drifts. `seafood_taxonomy.py` made that argument
for `is_fish_dish` (a prawn had been cloned from a fish template, putting a prawn
inside every rule about fish) and `bread_form_flags.py` made it again for
`is_plain_phulka_chapathi` (set on twelve dishes that are not chapatis, absent
from every dish spelled `chapati`). Both fixed one column definitionally — set it
where the definition holds, clear it where it does not — because a client rule
selecting on that column is only as good as the column.

Two more columns need the same treatment, and both are load-bearing for a rule
that is already shipped:

* **`is_liquid_dessert`** — Corning Chakan's `no_liquid_sweets` bans it outright
  and TCL asks for three a week. NCR carried it on **55 rows that are not
  liquid**: petha, barfi, laddu, cake, brownie, gulab jamun, a pastry. The token
  vote in `complete_ontology.py` learned it from a dessert list where most rows
  were payasams, so "sweet" came to imply "liquid". Two more sat outside the
  dessert course entirely — `kheera_raita` and `kheera_raita_lemon_water`, where
  the vote read "kheera" as "kheer", so a client banning liquid sweets would
  have lost their cucumber raita. Meanwhile six genuinely liquid NCR rows
  (`suji_kheer`, `rose_kheer`, three custards) were unflagged, as were two in
  Chennai and one each in Bangalore and Pune.
* **`is_buttermilk`** — Citrix serves it every day, World Bank and ICON Chn ask
  for it daily and TCL twice a week. Bangalore flagged ten rows and left six
  more unflagged, including the plainest one of all (`butter_milk`); Chennai's
  copies arrived unflagged with it.

A third and fourth are an INGREDIENT inside a course rather than a name family,
so they are declared separately in `COURSE_INGREDIENT_FLAGS`:

* **`is_paneer_fry`** — **zero rows in every city**, and Zscaler's
  `zscaler_paneer_fry_1` ("exactly one paneer fry a week") selects on it. The
  rule has therefore never constrained anything: `min` caps itself to what the
  pool can place, which for an empty selector is nothing, so it has been
  silently inert since it was written. It is the only one of the 112 flag
  columns that is empty everywhere AND read by a shipped config. The other two
  are unreferenced, and were adjudicated separately: **`is_bakery_dessert`** is
  a real gap — 61 cakes, brownies and muffins sat in the ontology while the
  column that names them was zero — so it is derived here too.
  **`is_nonveg_starter`** is a FACT, not a gap: this ontology files every
  non-veg starter (kebabs, chicken 65) under `nonveg_main`, so the `starter`
  course contains no non-veg row in any city. It is left empty deliberately.
* **`is_paneer_gravy`** — the working twin, and the column that says what the
  empty one should mean: it agrees with "a paneer dish in `veg_gravy`" on 165 of
  167 Bangalore rows and 7 of 7 in Chennai. In **NCR** it is wrong in both
  directions, from the same mapping pipeline that produced `ncr_bread_misfiles`:
  twelve rows carry it that are not paneer at all — `chilli_chiken` and
  `tandoori_chcien` (chicken), `lemon_water`, `sauce`, `crisp`, `pao_bhaji`, a
  `lemon_mint_mojito` filed as a welcome drink — while fourteen real ones
  (`butter_paneer_masala`, `matar_paneer`, `paneer_jaipuri`, `malai_kofta_curry`)
  are unflagged. So an NCR site asking for a paneer gravy could be served a
  chicken dish or a glass of lemon water, and could not be served a matar
  paneer. Same shape as `egg_kurma` carrying `is_south_chicken_gravy`.

The ingredient definition reads the NAME as well as the two ingredient columns,
and the name is what keeps it honest in both directions. Pune's `paneer_pasanda`
carries `key_ingredient: carrot`, so an ingredient-only rule would have cleared
a correct flag; none of NCR's twelve false positives has `paneer` in its name,
so the name never rescues one of those. Same argument `bread_form_flags.py` and
`nonveg_structural_flags.py` make for reading the dish name.

The definition is the dish NAME inside a COURSE. Scoping by course is what keeps
`majjige_huli` and `mor_kuzhambu` out of the buttermilk family — a buttermilk
*curry* is a `veg_gravy` and belongs there, which is why `audit_course_types.py`
also keeps `majjige` out of its drink signals. Three rows failed that test the
other way: `masala_chaas` in Bangalore and NCR, and NCR's `butter_milk`, were
filed `veg_gravy`, so a Delhi counter could serve "Butter Milk" as the day's
gravy. Those are re-filed to `welcome_drink` here, since the flag and the course
are one decision.

`complete_ontology.py` lists both flags in `OWNED_ELSEWHERE`, so its token vote
no longer proposes them and the correction chain converges whichever order the
two scripts run in.

Idempotent; re-run after any re-import. `tests/data/test_definitional_flags.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling scripts
from city_list import CITIES  # noqa: E402

#: Words that name a liquid sweet. `sheer` is milk (sheer korma, sheer
#: surkumba), `pradhaman` and `paramannam` are the Kerala and Telugu names for a
#: payasam, and `muzaffar` is the sweet vermicelli cooked down in milk.
LIQUID_DESSERT_WORDS = {
    "payasam", "payasa", "payasham", "kheer", "ricekheer", "phirni", "pudding",
    "custard", "basundi", "rabri", "rabdi", "pradhaman", "paramannam", "sheer",
    "muzaffar", "falooda", "thandai",
}

#: Words that name a buttermilk drink. `mor`/`moru` only counts beside `neer` or
#: `tadka` — on its own it is the first word of `mor_kuzhambu`, a gravy — and the
#: course scope below is what actually enforces that.
BUTTERMILK_WORDS = {
    "buttermilk", "chaas", "chhaas", "chaach", "sambaram", "majjige",
}

#: Names that ARE the family but whose tokens do not say so, because the name
#: splits into two ordinary words. Matched whole, not by token. The
#: `butter_milk` spellings are folded to `buttermilk` by
#: `canonical_dish_spellings.py`, which runs first — they stay here because a
#: raw re-import brings them back and this script must not depend on the order.
BUTTERMILK_NAMES = {
    "butter_milk", "masala_butter_milk", "tadka_butter_milk",
    "boondi_butter_milk", "tadka_neer_mor", "neer_mor", "neer_moru",
}

#: Words that name a WESTERN BAKED sweet. `is_bakery_dessert` was the only flag
#: in the schema that was zero in every city while the dishes plainly existed —
#: 61 of them, cakes and brownies and muffins — so a rule could name the family
#: and match nothing, silently, which is the failure mode `is_paneer_fry` had.
BAKERY_DESSERT_WORDS = {
    "cake", "brownie", "pastry", "pastries", "muffin", "cookie", "cookies",
    "cupcake", "cheesecake", "donut", "doughnut", "tart", "waffle",
    "croissant", "eclair", "pie",
}

#: The mawa sweets whose names carry a bakery word and are not baked at all.
#: The same two `dessert_cuisine_corrections.py` excludes from its western
#: retag, for the same reason and with the same verdict: a milk cake is a
#: reduced-milk Indian sweet, not a bakery item.
BAKERY_DESSERT_EXCLUDED = {
    "milk_cake", "ajmeri_milk_cake",
}

#: (flag, course, tokens, whole names, excluded names) — the definition, in both
#: directions. `excluded` is checked first and wins: it is how a name that
#: carries a family's word without belonging to the family is kept out, without
#: weakening the token list for the dishes that do.
DEFINITIONS: List[Tuple[str, str, Set[str], Set[str], Set[str]]] = [
    ("is_liquid_dessert", "dessert", LIQUID_DESSERT_WORDS, set(), set()),
    ("is_buttermilk", "welcome_drink", BUTTERMILK_WORDS, BUTTERMILK_NAMES,
     set()),
    ("is_bakery_dessert", "dessert", BAKERY_DESSERT_WORDS, set(),
     BAKERY_DESSERT_EXCLUDED),
]

#: (flag, course, primary_protein values, name phrases) — "this ingredient,
#: cooked this way". Two signals, either of which is enough, inside the course.
#:
#: **`key_ingredient` is deliberately NOT read**, though it is the column the
#: existing flag was derived from. In this ontology `key_ingredient = paneer` is
#: the de-facto default for a CHINESE dish, exactly as `baby_corn` is for a mixed
#: salad (CLAUDE.md §4.2, `name_contains`). Every Bangalore `veg_gravy` row it
#: claims beyond protein-or-name is Chinese and none is paneer —
#: `thai_green_curry`, `thai_veg_curry`, `veg_in_hot_garlic_sauce`,
#: `veg_in_mongolian_sauce`, `vegetable_hoisin_sauce` — and in `veg_dry` it adds
#: `bok_choy`, `fried_momos`, `spring_roll`, `steamed_momos`, `chilli_gobi` and
#: `gobi_salt_and_pepper`. So the column that populated `is_paneer_gravy` is
#: why a Zscaler "paneer gravy once a week" can be served a Thai green curry.
#:
#: `primary_protein` is the column that means it, and the NAME covers the rows
#: whose protein cell is blank. Together they lose exactly one real row across
#: four cities (`malai_kofta_curry`, NCR, which is unflagged today either way),
#: against the twenty they stop being wrong about. `cottage_cheese` is in the
#: name list because six dishes spell paneer that way.
COURSE_INGREDIENT_FLAGS: List[Tuple[str, str, Set[str], Set[str]]] = [
    ("is_paneer_gravy", "veg_gravy", {"paneer"}, {"paneer", "cottage_cheese"}),
    ("is_paneer_fry", "veg_dry", {"paneer"}, {"paneer", "cottage_cheese"}),
]

#: Buttermilk DRINKS filed as something else. A buttermilk curry (`majjige_huli`,
#: `mor_kuzhambu`) is correctly a `veg_gravy` and is deliberately absent here;
#: these three are the drink, and `audit_course_types.py` missed them because
#: `butter_milk` tokenises to `butter` + `milk`, neither of which is a drink word.
REFILE_TO_WELCOME_DRINK: Dict[str, List[str]] = {
    "bangalore": ["masala_chaas"],
    # `buttermilk` here, not `butter_milk`: the spelling fold is step 3
    # of the correction chain and this is step 13.
    "ncr": ["buttermilk", "masala_chaas"],
}


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


def matches(item: str, tokens: Set[str], names: Set[str],
            excluded: Set[str] = frozenset()) -> bool:
    """Does this dish name belong to the family?

    *excluded* is checked first and wins. It exists so a token list can stay
    broad enough to catch the family while a name that merely borrows one of its
    words stays out — `milk_cake` is a mawa sweet, not a bakery item, and
    dropping `cake` from the token list to keep it out would lose the other
    fifty-nine.
    """
    key = _norm(item)
    if key in excluded:
        return False
    if key in names:
        return True
    return bool(set(t for t in key.split("_") if t) & tokens)


def has_ingredient(row, proteins: Set[str], name_phrases: Set[str]) -> bool:
    """Is this dish made of one of *proteins*, by the protein column or by name?

    Phrases, not tokens, for the name: `cottage_cheese` is two words and would
    never match a token scan. A bare token is a one-word phrase, so `paneer`
    still matches `paneer_butter_masala` and — correctly — `chilli_paneer_dry`.
    """
    if _norm(row.get("primary_protein")) in proteins:
        return True
    name = _norm(row.get("item"))
    return any(p in name for p in name_phrases)


def enforce_ingredient(df: pd.DataFrame, flag: str, course: str,
                       proteins: Set[str], name_phrases: Set[str]):
    """`enforce()` for an ingredient-in-a-course flag. Same both-directions
    contract, same course scope."""
    if flag not in df.columns:                              # pragma: no cover
        return [], []
    in_course = df["course_type"].map(_norm).eq(course)
    current = pd.to_numeric(df[flag], errors="coerce").fillna(0).eq(1)
    should = df.apply(
        lambda r: has_ingredient(r, proteins, name_phrases), axis=1) & in_course

    to_set = df.index[should & ~current]
    to_clear = df.index[current & ~should]
    df.loc[to_set, flag] = 1
    df.loc[to_clear, flag] = 0
    return (list(df.loc[to_set, "item"]), list(df.loc[to_clear, "item"]))


def refile(df: pd.DataFrame, wanted: List[str]) -> List[str]:
    names = df["item"].map(_norm)
    moved = []
    for dish in wanted:
        hit = names.eq(_norm(dish))
        if not hit.any():
            print(f"    ! {dish} is not in this city's list — skipped")
            continue
        idx = df.index[hit]
        if (df.loc[idx, "course_type"].map(_norm) == "welcome_drink").all():
            continue
        df.loc[idx, "course_type"] = "welcome_drink"
        if "is_welcome_drink" in df.columns:
            df.loc[idx, "is_welcome_drink"] = 1
        if "is_veg_gravy" in df.columns:
            df.loc[idx, "is_veg_gravy"] = 0
        moved.append(dish)
    return moved


def enforce(df: pd.DataFrame, flag: str, course: str,
            tokens: Set[str], names: Set[str],
            excluded: Set[str] = frozenset()):
    """Set *flag* on every row of *course* the definition holds for and clear it
    everywhere else. Returns (set, cleared) dish names.

    The clear reaches OUTSIDE the course too, which is the half that catches the
    subtler false positives: NCR's `kheera_raita` carried `is_liquid_dessert`
    because the token vote read "kheera" as "kheer", and a cucumber raita is not
    a course misfile — it is correctly a `curd_side` with a wrong flag on it. A
    client banning liquid sweets would have lost their raita.

    So the scope IS the course, in both directions: a dish outside it cannot
    belong to the family whatever its name says.
    """
    if flag not in df.columns:                              # pragma: no cover
        return [], []
    in_course = df["course_type"].map(_norm).eq(course)
    current = pd.to_numeric(df[flag], errors="coerce").fillna(0).eq(1)
    should = df["item"].map(
        lambda i: matches(i, tokens, names, excluded)) & in_course

    to_set = df.index[should & ~current]
    to_clear = df.index[current & ~should]
    df.loc[to_set, flag] = 1
    df.loc[to_clear, flag] = 0
    return (list(df.loc[to_set, "item"]), list(df.loc[to_clear, "item"]))


def main(dry_run: bool = False) -> int:
    touched: Set[str] = set()
    frames: Dict[str, pd.DataFrame] = {}
    for city in CITIES:
        df = pd.read_excel(CITY_DIR / f"{city}.xlsx")
        df.columns = [c.strip() for c in df.columns]
        frames[city] = df

        moved = refile(df, REFILE_TO_WELCOME_DRINK.get(city, []))
        if moved:
            touched.add(city)
            print(f"[{city}] -> welcome_drink: {', '.join(moved)}")

        passes = (
            [(f, lambda d, f=f, c=c, t=t, n=n, x=x: enforce(d, f, c, t, n, x))
             for f, c, t, n, x in DEFINITIONS]
            + [(f, lambda d, f=f, c=c, p=p, nm=nm:
                enforce_ingredient(d, f, c, p, nm))
               for f, c, p, nm in COURSE_INGREDIENT_FLAGS]
        )
        for flag, run in passes:
            was_set, cleared = run(df)
            if was_set or cleared:
                touched.add(city)
                print(f"[{city}] {flag}: +{len(was_set)} set, "
                      f"-{len(cleared)} cleared")
                if was_set:
                    print(f"    set:     {', '.join(sorted(was_set)[:8])}"
                          f"{' …' if len(was_set) > 8 else ''}")
                if cleared:
                    print(f"    cleared: {', '.join(sorted(cleared)[:8])}"
                          f"{' …' if len(cleared) > 8 else ''}")
            else:
                print(f"[{city}] {flag}: already definitional")

    if not touched:
        print("\nnothing to do — every flag already means one thing")
        return 0
    if dry_run:
        print("[dry-run] nothing written")
        return 0
    for city in sorted(touched):
        _atomic_to_excel(frames[city], CITY_DIR / f"{city}.xlsx")
        print(f"[{city}] wrote {city}.xlsx")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
