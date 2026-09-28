#!/usr/bin/env python3
"""What the Chennai item list did not hold for its four new clients.

TCL, Gartner, World Bank and ICON Chn arrived with a stated rule set and a
sample week each (`data/raw/source_workbooks/chennai_client_structure.xlsx`).
Wiring them surfaced five holes in `chennai.xlsx` — four of them the kind that
fails *silently*, and one that does not fail silently at all: TCL went straight
to INFEASIBLE with `welcome_drink (0 distinct item(s) for 5 day-slot(s))`.

1. **Kootu is the dal, not the gravy.** Three of the four clients state, in the
   same words, "in dal need to give only Kootu item" — and Chennai's eight kootu
   rows were all `course_type = veg_gravy`, so the dal pool held *zero* kootu and
   the rule was unsatisfiable as written. Every one of the four sample weeks
   backs the clients up: the kootu is its own row, next to but never *as* the
   day's gravy (World Bank prints "Veg Gravy", "Kara kuzhambhu" and "Kootu" as
   three rows; ICON's is labelled "Kootu or Poriyal", pairing it with the dry).
   A kootu is a vegetable simmered with moong or toor dal, so `dal` is the
   position it actually occupies on a Tamil plate. `sub_category = kootu` is
   preserved, which is what `kootu_twice_weekly` selects on, so the city cap is
   unaffected. This is a deliberate divergence from Bangalore, which files 43
   kootus as `veg_gravy` (and two as `dal`); per-city ontologies are allowed to
   disagree and this one follows the clients who eat off it.
2. **The dal pool then needs to be a kootu pool.** Eight dishes cannot carry a
   daily slot through a 20-day cooldown, so eight more come from Bangalore —
   eight distinct vegetables Chennai's own kootus do not already cover, rather
   than eight variations on ash gourd.
3. **Chennai had no welcome drinks at all.** Not one row: `is_welcome_drink` was
   0 across the entire list, which is why `chennai.json` documents the drink
   rules as inert. Four of the new counters declare the slot and three clients
   state a buttermilk rule, so 28 come from Bangalore — the ten buttermilks
   (which include `sambaram` and `tadka_neer_mor`, the dishes TCL's own menu
   names as SAMBARAM and NEER MOORU) plus eighteen coolers, sherbets and lassis
   so the non-buttermilk days have somewhere to go.
4. **Two dishes the clients name daily did not exist.** World Bank serves a
   "Boiled Egg" and a "Bone Salna" every day and ICON's premium counter on three
   days. A pin naming a dish the ontology lacks is stamped verbatim post-solve,
   which prints the right menu but hides the dish from every other rule — so
   these are real rows instead, and the same pins now narrow a cell.
5. **Two pools a stated frequency outran.** TCL wants a biryani in its first
   rice slot *daily* (14 rows, against ~15 weekday services in a cooldown
   window) and three liquid sweets a week (9 rows). Eight biryanis and six
   payasams close both, the biryanis chosen Tamil-first — Ambur, Dindigul,
   Chettinad, Malabar — plus the single-vegetable ones the clients print.

Everything else in the four rule sets was expressible against the list as it
stood. Two of these fixes also need `chennai` in `FULL_POOL_CITIES`: 191 of the
621 rows sit in per-site pools while three of the four new clients have
`source_pools = []`, so World Bank could not see the 21 rows tagged "World
Bank", and TCL could reach only 4 of the 14 veg biryanis. That is the same
situation, and the same one-line fix, as Bangalore (note 15).

Idempotent (fixed sets, skip by name); re-run after any re-import.
`tests/data/test_chennai_client_pools.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import re

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"
CHENNAI = CITY_DIR / "chennai.xlsx"
BANGALORE = CITY_DIR / "bangalore.xlsx"
CATEGORIES = CITY_DIR / "ontology_categories.json"

#: The eight kootu rows, moved `veg_gravy` -> `dal`. Named rather than matched on
#: `sub_category` so the change is a reviewable list: a re-import that adds a
#: ninth kootu leaves it in veg_gravy and the test says so.
KOOTU_TO_DAL = [
    "cabbage_kootu",
    "keerai_chana_kootu",
    "keerai_kootu",
    "peerkangai_kootu",      # ridge gourd
    "poosanikai_kootu",      # ash gourd
    "vazhathandu_kootu",     # banana stem
    "veg_kootu",
    # Both words name a form, which is why it reads oddly. It is a kootu of
    # mixed vegetables — the poriyal in the name is the vegetable prep it is
    # built from, not the dish's own form — so it moves with the rest.
    "poriyal_kootu",
]

#: The twelve kuzhambu rows, moved `veg_gravy` -> `salad`. The client's own
#: categorisation: "kuzhambus are the dish which category should be in salad not
#: veg gravy". TCL states it as a rule ("in salad need to give only KUZHAMBU
#: item") and its sample week proves the two are DIFFERENT rows rather than one
#: mislabelled — Sunday's stated menu lists "veg gravy" and "salad" separately,
#: and the grid serves VEG KURMA beside KARA KUZHAMBU.
#:
#: Same shape and same reasoning as the kootu re-file above: a tamarind or
#: buttermilk kuzhambu is not a leaf salad by a Western reading, but `course_type`
#: is what picks the slot pool, and in a Tamil meal this is the dish that occupies
#: the row the client calls salad. Filing it as a `veg_gravy` made TCL's stated
#: rule unsatisfiable — the salad pool held none.
#:
#: Named rather than matched on the name pattern so the change stays a reviewable
#: list: a re-import that adds a thirteenth kuzhambu leaves it in `veg_gravy` and
#: `test_chennai_client_pools.py` says so. Deliberately NOT moved: the four
#: non-veg kuzhambus (chicken/fish), `kolambu_sadam` and `vatha_kuzhambu_rice`
#: (rice dishes) and `mor_kolambu_vada` (a starter) — the word names the gravy
#: they are built from, not the dish's own course. Chennai only; Bangalore's
#: clients serve theirs as gravies.
KUZHAMBU_TO_SALAD = [
    "bhindi_more_kuzhambu",
    "coconut_veg_kuzhambu",
    "kara_kuzhambu",
    "mochai_kuzhambu",
    "more_kuzhambu_with_bonda",
    "poondu_puli_kuzhambu",
    "sunda_vatha_kuzhambu",
    "sundakkai_vathal_kuzhambu",
    "urandai_kuzhambu",
    "vatha_kuzhambu",
    "vathal_mochai_kuzhambu",
    "vendakkai_puli_kuzhambu",
]

#: Eight more kootus, cloned from Bangalore and re-coursed to `dal`. Chosen for
#: eight vegetables Chennai's existing kootus do not cover: it already has three
#: ash-gourd kootus, so more of those would not deepen anything.
KOOTU_FROM_BANGALORE = [
    "bottle_gourd_kootu",       # sorakkai
    "chow_chow_kootu",          # chayote
    "snake_gourd_kootu",        # pudalangai
    "beetroot_kootu",
    "bhindi_kootu",             # okra
    "karamani_brinjal_kootu",
    "chow_peas_kootu",
    "moong_kootu",
]

#: The ten rows that carry `is_buttermilk`, plus eighteen other drinks. Named in
#: Bangalore's spelling as `canonical_dish_spellings.py` leaves it — that script
#: is step 3 of the correction chain and this is step 5, so the plain drink is
#: `buttermilk` by the time these are copied, not `butter_milk`.
WELCOME_DRINKS = [
    # -- the buttermilk family (TCL's SAMBARAM / INJI MOORU / NEER MOORU, and
    #    the daily buttermilk World Bank, ICON and TCL all ask for)
    "buttermilk",
    "sambaram",
    "tadka_neer_mor",
    "ginger_buttermilk",
    "jeera_buttermilk",
    "masala_buttermilk",
    "pudina_chaas",
    "ragi_buttermilk",
    "spiced_buttermilk",
    "tempered_buttermilk",
    # -- everything else, so a counter capping buttermilk at twice a week has
    #    eighteen dishes for the other days rather than four
    "nanari_sharbath",          # nannari — the Tamil sarsaparilla sherbet
    "panakam",                  # jaggery, lemon and cardamom
    "rose_milk",                # a Chennai canteen fixture
    "badam_milk",
    "aam_panna",
    "rooh_afza_sherbat",
    "jaljeera",
    "lemonade",
    "mint_lemonade",
    "cucumber_lemonade",
    "lemon_mint",
    "ginger_lemon",
    "cucumber_mint_refresher",
    "watermelon_lime_splash",
    "coconut_mint_cooler",
    "pineapple_coconut",
    "sweet_lassi",
    "rose_lassi",
]

#: Veg biryanis for TCL's daily first rice. Tamil Nadu regional styles first
#: (Ambur, Dindigul, Chettinad, Malabar are all TN biryanis), then the
#: single-vegetable ones the clients' own grids print — ICON serves "Aloo
#: Biryani" and TCL "Soya Chunk Biryani" and "Corn & Peas Biryani".
VEG_BIRYANIS = [
    "ambur_veg_biryani",
    "dindigul_veg_biryani",
    "chettinad_veg_biryani",
    "malabar_veg_biryani",
    "aloo_biryani",
    "soya_chunks_biryani",
    "peas_biryani",
    "gobi_biryani",
]

#: Liquid sweets for TCL's "liquid based sweet 3 a week". The names come off the
#: two grids: TCL prints ARISI PAYASAM and PARRUPU PAYASAM, ICON DAL PAYASAM.
LIQUID_SWEETS = [
    "paruppu_payasam",
    "rice_payasam",
    "pal_payasam",
    "dal_payasam",
    "phirni",
    "sago_jaggery_payasam",
]

#: (target course, [dish], source course) — a copy that CHANGES course, which is
#: how a Bangalore kootu becomes a Chennai dal. `None` keeps the source's.
COPIES: List[Tuple[str, List[str], str]] = [
    ("dal", KOOTU_FROM_BANGALORE, "veg_gravy"),
    ("welcome_drink", WELCOME_DRINKS, "welcome_drink"),
    ("rice", VEG_BIRYANIS, "rice"),
    ("dessert", LIQUID_SWEETS, "dessert"),
]

#: The two dishes named daily by a client and absent from every city list.
#: Built from a Chennai template so the 134-column skeleton and the city's own
#: conventions come free, with every `is_*` zeroed first.
NEW_DISHES: List[Dict[str, Any]] = [
    {
        "template": "egg_masala",
        "fields": {
            "item": "boiled_egg",
            "course_type": "nonveg_main",
            # A boiled egg arrives unsauced, so it is a `dry` non-veg for the
            # composition rules — the same reading `nonveg_structural_flags.py`
            # applies to a kebab or a roast.
            "sub_category": "egg_boiled",
            "key_ingredient": "egg",
            "primary_protein": "egg",
            "cuisine_family": "south_indian",
            "item_color": "white",
        },
        "flags": {"is_egg_dish": 1, "is_nonveg_dry": 1},
    },
    {
        "template": "chicken_kuzhambu",
        "fields": {
            "item": "bone_salna",
            "course_type": "nonveg_main",
            "sub_category": "chicken_south_coastal",
            "key_ingredient": "chicken",
            "primary_protein": "chicken",
            "cuisine_family": "south_indian",
            "item_color": "brown",
        },
        # `is_nonveg_gravy` but deliberately NOT a regional chicken-gravy flag:
        # a salna is a thin bone broth poured over biryani, and flagging it
        # `is_south_chicken_gravy` would let it satisfy every "and a chicken
        # gravy" component that exists to put a second, different dish on the
        # plate. Same call `nonveg_structural_flags.py` made for `mutton_curry`.
        "flags": {"is_nonveg_gravy": 1},
    },
]


def _atomic_to_excel(frame, path, **kw):
    """Write via a temp file + rename: `to_excel` truncates the target before
    streaming into it, so an interrupted run leaves a 0-byte workbook."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    kw.setdefault("index", False)
    frame.to_excel(tmp, **kw)
    tmp.replace(p)


def _norm(s) -> str:
    return str(s).strip().lower()


def _names(df) -> set:
    return set(df["item"].map(_norm))


def _next_id(df) -> int:
    """One past the highest id in the file.

    `item_id` is `MENU######`, so `pd.to_numeric` coerces every one of them to
    NaN and the max of an all-NaN series is nothing — which is how this returned
    1 and stamped bare integers `1, 2, 3...` onto rows in a column whose format
    is a prefixed string. The numeric part has to be parsed out, the way
    `expand_side_pools._next_id` already does it.
    """
    nums = [int(m.group(1)) for s in df["item_id"].dropna().astype(str)
            for m in [re.search(r"(\d+)", s)] if m]
    return (max(nums) + 1) if nums else 1


def _mk_id(n: int) -> str:
    """The schema's key format. A bare int is not it."""
    return f"MENU{n:06d}"


def refile_kootu(df: pd.DataFrame) -> List[str]:
    """Move the named kootus into `dal`. Returns what moved."""
    moved = []
    names = df["item"].map(_norm)
    for dish in KOOTU_TO_DAL:
        hit = names.eq(dish)
        if not hit.any():
            print(f"    ! {dish} is not in the Chennai list — skipped")
            continue
        idx = df.index[hit]
        if (df.loc[idx, "course_type"].map(_norm) == "dal").all():
            continue
        df.loc[idx, "course_type"] = "dal"
        moved.append(dish)
    return moved


def refile_kuzhambu(df: pd.DataFrame) -> List[str]:
    """Move the named kuzhambus into `salad`. Returns what moved.

    Mirrors `refile_kootu`, including the course mirrors: `course_type` decides
    the slot pool, and the `is_*` flags that restate the course have to follow or
    a flag-driven rule still reads the dish as a gravy.
    """
    moved = []
    names = df["item"].map(_norm)
    for dish in KUZHAMBU_TO_SALAD:
        hit = names.eq(dish)
        if not hit.any():
            print(f"    ! {dish} is not in the Chennai list — skipped")
            continue
        idx = df.index[hit]
        if (df.loc[idx, "course_type"].map(_norm) == "salad").all():
            continue
        df.loc[idx, "course_type"] = "salad"
        for col, want in (("is_salad", 1), ("is_veg_gravy", 0)):
            if col in df.columns:
                df.loc[idx, col] = want
        moved.append(dish)
    return moved


def align_kootu_flags(df: pd.DataFrame) -> int:
    """Make the course-mirror flags follow the course, for every kootu in `dal`.

    Separate from the re-file because it has to reach the IMPORTED kootus too: a
    copied row keeps the source course's flags, so eight Bangalore veg gravies
    arrived in Chennai's dal pool carrying `is_veg_gravy` and not `is_dal` — and
    `is_dal` is a course mirror `complete_ontology.py` measures at 99.8%, so the
    silent cost was that mirror dropping to 98.6%. Runs unconditionally, which is
    also what makes a re-run repair a workbook someone half-corrected.
    """
    kootu = (df["sub_category"].map(_norm).eq("kootu")
             & df["course_type"].map(_norm).eq("dal"))
    if not kootu.any():
        return 0
    changed = 0
    for col, want in (("is_dal", 1), ("is_veg_gravy", 0)):
        if col not in df.columns:
            continue
        wrong = kootu & pd.to_numeric(df[col], errors="coerce").fillna(0).ne(want)
        changed += int(wrong.sum())
        df.loc[wrong, col] = want
    return changed


def copy_rows(target: pd.DataFrame, source: pd.DataFrame, wanted: List[str],
              src_course: str, dst_course: str):
    """Clone *wanted* rows out of *source*, re-coursed to *dst_course*."""
    have = _names(target)
    src_names = source["item"].map(_norm)
    src_courses = source["course_type"].map(_norm)
    added, rows = [], []
    nid = _next_id(target)
    for dish in wanted:
        key = _norm(dish)
        if key in have:
            continue
        hit = source[src_names.eq(key) & src_courses.eq(src_course)]
        if hit.empty:
            print(f"    ! {dish} is not a {src_course} in bangalore.xlsx — skipped")
            continue
        row = hit.iloc[0].copy()
        row["item_id"] = _mk_id(nid)
        nid += 1
        row["course_type"] = dst_course
        # Chennai tags shared dishes `common`; a per-site token would make the
        # row invisible to every client that does not name that site.
        if "client" in row.index:
            row["client"] = "common"
        rows.append(row)
        added.append(dish)
        have.add(key)
    if not rows:
        return target, added
    out = pd.concat([target, pd.DataFrame(rows)], ignore_index=True)
    return out[target.columns], added


def add_new(target: pd.DataFrame, specs: List[Dict[str, Any]]):
    have = _names(target)
    names = target["item"].map(_norm)
    added, rows = [], []
    nid = _next_id(target)
    for spec in specs:
        if _norm(spec["fields"]["item"]) in have:
            continue
        tmpl = target[names.eq(_norm(spec["template"]))]
        if tmpl.empty:                                       # pragma: no cover
            print(f"    ! template {spec['template']} is missing — skipped")
            continue
        row = tmpl.iloc[0].copy()
        for col in row.index:
            if str(col).startswith("is_"):
                row[col] = 0
        row["item_id"] = _mk_id(nid)
        nid += 1
        for field, value in spec["fields"].items():
            row[field] = value
        for flag, value in (spec.get("flags") or {}).items():
            if flag in row.index:
                row[flag] = value
        if "client" in row.index:
            row["client"] = "common"
        rows.append(row)
        added.append(spec["fields"]["item"])
        have.add(_norm(spec["fields"]["item"]))
    if not rows:
        return target, added
    out = pd.concat([target, pd.DataFrame(rows)], ignore_index=True)
    return out[target.columns], added


def declare_welcome_drink(dry_run: bool = False) -> bool:
    """Add `welcome_drink` to Chennai's declared categories.

    `PoolBuilder.build_pools(required_slots=…)` raises on an empty *declared*
    slot, so declaring it is what turns "Chennai lost its drinks again" from an
    INFEASIBLE solve into a build-time error naming the slot.
    """
    data = json.loads(CATEGORIES.read_text())
    cats = data.get("chennai") or []
    if "welcome_drink" in cats:
        return False
    if not dry_run:
        data["chennai"] = ["welcome_drink"] + list(cats)
        CATEGORIES.write_text(json.dumps(data, indent=2) + "\n")
    return True


def main(dry_run: bool = False) -> int:
    chn = pd.read_excel(CHENNAI)
    chn.columns = [c.strip() for c in chn.columns]
    blr = pd.read_excel(BANGALORE)
    blr.columns = [c.strip() for c in blr.columns]
    before = len(chn)
    changed = False

    moved = refile_kootu(chn)
    if moved:
        changed = True
        print(f"[chennai] kootu -> dal: {len(moved)} row(s) ({', '.join(moved)})")
    else:
        print("[chennai] kootu -> dal: already filed as dal")

    moved = refile_kuzhambu(chn)
    if moved:
        changed = True
        print(f"[chennai] kuzhambu -> salad: {len(moved)} row(s) "
              f"({', '.join(moved)})")
    else:
        print("[chennai] kuzhambu -> salad: already filed as salad")

    for dst_course, wanted, src_course in COPIES:
        chn, added = copy_rows(chn, blr, wanted, src_course, dst_course)
        n_now = int(chn["course_type"].map(_norm).eq(dst_course).sum())
        if added:
            changed = True
            print(f"[chennai] {dst_course}: +{len(added)} from bangalore "
                  f"-> {n_now} rows")
        else:
            print(f"[chennai] {dst_course}: already present ({n_now} rows)")

    aligned = align_kootu_flags(chn)
    if aligned:
        changed = True
        print(f"[chennai] kootu flags: {aligned} corrected to follow the course")

    chn, added = add_new(chn, NEW_DISHES)
    if added:
        changed = True
        print(f"[chennai] nonveg_main: +{len(added)} new ({', '.join(added)})")
    else:
        print("[chennai] nonveg_main: boiled_egg / bone_salna already present")

    if declare_welcome_drink(dry_run=dry_run):
        changed = True
        print("[chennai] declared welcome_drink in ontology_categories.json")
    else:
        print("[chennai] welcome_drink already declared")

    if not changed:
        print("\nnothing to do — the Chennai list already holds all of it")
        return 0
    if dry_run:
        print("[dry-run] nothing written")
        return 0
    _atomic_to_excel(chn, CHENNAI)
    print(f"[chennai] wrote chennai.xlsx ({before} -> {len(chn)} rows)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(dry_run=ap.parse_args().dry_run))
