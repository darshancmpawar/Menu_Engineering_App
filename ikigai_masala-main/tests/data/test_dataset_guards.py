"""Standing guards on the five city workbooks, now that they ARE the source.

`data/raw/city_items/*.xlsx` used to be DERIVED: a normaliser rebuilt them from
the raw lists and a chain of correction scripts re-applied every hand fix on
top. The owner's cleaned workbooks replaced that — the chain is gone and these
five files are the input, not an artefact — so the tests that pinned the
scripts' behaviour went with them.

What must NOT go with them is the two checks the corrections existed to make
pass, because both of these fail SILENTLY and in the direction nobody notices:

  * **the vegetarian line.** A dish whose name declares an animal protein but
    whose row does not sits in the veg pools, because `_nonveg_mask` reads the
    row and not the name. Nothing raises and nothing logs; a vegetarian is
    served meat. This is the one error in the system whose consequence is
    outside the software.
  * **a non-veg dish with no form flag can never be served.** The daily
    composition asks for one dry plus one chicken gravy, so a `nonveg_main` row
    carrying neither is never chosen — it sits in the pool passing every
    diagnostic, and the hole only shows when something else forces the counter
    INFEASIBLE with nothing pointing at the cause.

Read the workbooks and `src.constants` only. Nothing here imports a script, so
nothing here can be deleted along with one.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from src.constants import NONVEG_PROTEINS
from src.ontology.paths import city_excel_path

CITIES = ("Bangalore", "Chennai", "Hyderabad", "NCR", "Pune")

#: Misspellings of an animal-protein word, recovered from the correction script
#: before it was removed. These are the ones that matter: a misspelled protein
#: makes a row invisible to every name-based audit AND lets a meat-named dish
#: pass as vegetarian. Whole snake_case tokens.
PROTEIN_TYPOS = (
    "chciken", "chcken", "chiceken", "chikcen", "chickem", "chivken",
    "chikken", "chikan", "muton", "mutten", "fsh", "prwan", "pran",
    "egss", "eeg",
)
PROTEIN_TYPO_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(sorted(PROTEIN_TYPOS)) + r")(?![a-z0-9])")

#: Every flag that makes a non-veg dish placeable by some composition.
STRUCTURAL_FLAGS = (
    "is_nonveg_dry", "is_nonveg_gravy", "is_north_chicken_gravy",
    "is_south_chicken_gravy", "is_nonveg_biryani", "is_chinese_chicken_gravy",
    "is_continental_chicken_gravy", "is_continental_chicken_dry",
    "is_semidry_nonveg_main", "is_tandoor_nonveg_dry",
    "is_deep_fried_nonveg_dry", "is_nonveg_starter",
)

#: Names that borrow a meat word for a meat-free version and say so in the same
#: name, so the name does not declare an animal protein after all.
VEG_QUALIFIERS = ("veg", "soya", "soyabean", "mushroom", "less", "paneer")

#: `(city, item)` looked up individually and found vegetarian despite a meat
#: word in the name — the verdict, one row at a time, because widening
#: `VEG_QUALIFIERS` instead would let a real meat dish through with it.
#:
#: Both are Pune `kheema` rows, and `kheema` is a veg word far more often than
#: not in this data. A Pune MEAT row looks like `chicken_kheema`:
#: `primary_protein: chicken`, `sub_category: chicken_north_masala`,
#: `is_nonveg_gravy: 1`, `course_type: nonveg_main`. Neither of these carries
#: any of that — `kheema_mutter_masala` is `sub_category: soya_curry` with
#: `key_ingredient: green_peas`, and `hyderabadi_kheema_pulao` is
#: `north_simple_veg_pulao`, the same sub_category as the `veg_kheema_pulao`
#: beside it.
ADJUDICATED_VEG = {
    ("Pune", "kheema_mutter_masala"),
    ("Pune", "hyderabadi_kheema_pulao"),
}


@pytest.fixture(scope="module")
def frames():
    return {c: pd.read_excel(city_excel_path(c)) for c in CITIES}


def _names(df):
    return df["item"].astype(str).str.strip().str.lower()


# --- the vegetarian line ---------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_no_meat_named_dish_sits_in_a_veg_pool(frames, city):
    """A dish whose NAME declares an animal protein must declare it on the ROW.

    `PoolBuilder._nonveg_mask` reads `primary_protein` and `is_egg_dish`, never
    the name — so a meat-named row with a blank protein is a veg-pool dish with
    a meat name on the printed menu.
    """
    df = frames[city]
    offenders = []
    for _, r in df.iterrows():
        name = str(r["item"]).strip().lower()
        toks = set(name.split("_"))
        if not toks & NONVEG_PROTEINS or toks & set(VEG_QUALIFIERS):
            continue
        if (city, name) in ADJUDICATED_VEG:
            continue
        protein = str(r.get("primary_protein") or "").strip().lower()
        if protein and protein != "nan":
            continue
        offenders.append((name, str(r["course_type"]).strip().lower()))
    assert not offenders, (
        f"{city}: meat-named dishes with no protein declared — they sit in the "
        f"veg pools: {sorted(offenders)}")


@pytest.mark.parametrize("city", CITIES)
def test_no_city_carries_a_misspelled_protein_word(frames, city):
    """A misspelled protein hides a row from every name-based audit, including
    the one above: `chciken` is not a token `NONVEG_PROTEINS` knows."""
    offenders = sorted(n for n in _names(frames[city])
                       if PROTEIN_TYPO_RE.search(n))
    assert not offenders, f"{city} carries meat-name typos: {offenders}"


def test_every_adjudicated_row_is_still_there(frames):
    """An exemption for a dish that no longer exists is a widened exemption
    nobody is watching."""
    for city, item in sorted(ADJUDICATED_VEG):
        assert item in set(_names(frames[city])), f"{city} no longer has {item}"


# --- a non-veg dish that can never be served -------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_every_nonveg_main_carries_a_form(frames, city):
    """`nonveg_main_daily_pair` composes the counter as one dry plus one
    chicken gravy, so a row with no form flag is never chosen — and never
    reported, because having no form is not an error any diagnostic looks
    for."""
    df = frames[city]
    cols = [c for c in STRUCTURAL_FLAGS if c in df.columns]
    assert cols, f"{city} carries none of the structural flag columns"
    rows = df[df["course_type"].astype(str).str.strip().str.lower()
              == "nonveg_main"]
    flagged = sum(
        (pd.to_numeric(rows[c], errors="coerce").fillna(0) == 1) for c in cols)
    unplaceable = sorted(_names(rows)[flagged == 0])
    assert not unplaceable, (
        f"{city}: nonveg_main rows no composition can place: {unplaceable}")


if __name__ == "__main__":  # a runnable check without pytest
    fr = {c: pd.read_excel(city_excel_path(c)) for c in CITIES}
    for city in CITIES:
        test_no_meat_named_dish_sits_in_a_veg_pool(fr, city)
        test_no_city_carries_a_misspelled_protein_word(fr, city)
        test_every_nonveg_main_carries_a_form(fr, city)
        print("ok", city)
    test_every_adjudicated_row_is_still_there(fr)
    print("ok adjudications")
