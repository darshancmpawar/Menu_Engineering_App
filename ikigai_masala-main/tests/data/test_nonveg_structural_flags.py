"""Non-veg dishes with no form flag are unservable
(`scripts/nonveg_structural_flags.py`).

`slot_composition`'s `nonveg_main_daily_pair` composes a 2-to-4 slot non-veg
counter as one `is_nonveg_dry` + one north/south chicken gravy every day, so
both cells of a 2-slot counter are spoken for. A dish carrying none of those
flags therefore cannot be placed at all — it sits in the pool, passes every
diagnostic, and is simply never chosen.

Nothing surfaced that until Stripe's `min: 1` fish rule forced the issue: with
`fish_finger` and `tawa_fish_fry` carrying no form flag, requiring one per week
left the composition a single cell for two components and the counter went
INFEASIBLE, reported only as "the rules cannot all be satisfied".

Pinned here: the flags stay filled, the derivation reads the name the way a
person would, soups are left out of it, and — the part worth protecting — a
dish the name cannot classify is left alone rather than guessed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from menu_import import nonveg_structural_flags          # noqa: E402
from nonveg_structural_flags import (                    # noqa: E402
    COMPOSED_COURSE,
    STRUCTURAL_FLAGS,
    STYLE_OVERRIDES,
    apply,
)
from src.ontology.paths import city_excel_path           # noqa: E402

CITIES = ("bangalore", "pune", "chennai", "ncr")


def _frame(city):
    df = pd.read_excel(city_excel_path(city))
    df.columns = [c.strip() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def frames():
    return {c: _frame(c) for c in CITIES}


def _flagged(df, idx, cols):
    return any(int(pd.to_numeric([df.at[idx, c]], errors="coerce")[0] or 0) == 1
               for c in cols)


# --------------------------------------------------------------------------
# The derivation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item,protein,cuisine,expected", [
    ("banjara_murgh_dry", "chicken", "north_indian", {"is_nonveg_dry"}),
    ("tawa_fish_fry", "fish", "north_indian", {"is_nonveg_dry"}),
    ("fish_finger", "fish", "north_indian", {"is_nonveg_dry"}),
    ("railway_chicken_curry", "chicken", "north_indian",
     {"is_nonveg_gravy", "is_north_chicken_gravy"}),
    ("andhra_kodi_curry", "chicken", "south_indian",
     {"is_nonveg_gravy", "is_south_chicken_gravy"}),
    # not chicken -> a gravy, but not a CHICKEN gravy
    ("mutton_curry", "mutton", "north_indian", {"is_nonveg_gravy"}),
    # biryani wins over everything, whatever row it was printed on
    ("muradabadi_chicken_biryani", "chicken", "north_indian",
     {"is_nonveg_biryani", "is_biryani_item"}),
    # both words present: gravy is the dish's form
    ("chicken_tikka_masala", "chicken", "north_indian",
     {"is_nonveg_gravy", "is_north_chicken_gravy"}),
    # a place plus a protein says nothing about form
    ("afghani_chicken", "chicken", "north_indian", set()),
    ("kolhapuri_chicken", "chicken", "north_indian", set()),
])
def test_the_name_decides(item, protein, cuisine, expected):
    assert nonveg_structural_flags(item, protein, cuisine) == expected


def test_a_printed_row_overrides_a_silent_name():
    """`dijon_chicken` says nothing; Stripe's menu prints it under Semi Dry."""
    assert nonveg_structural_flags("dijon_chicken", "chicken", "north_indian") \
        == set()
    assert nonveg_structural_flags("dijon_chicken", "chicken", "north_indian",
                                   "dry") == {"is_nonveg_dry"}
    assert nonveg_structural_flags("laal_murgh", "chicken", "north_indian",
                                   "gravy") == {"is_nonveg_gravy",
                                                "is_north_chicken_gravy"}


def test_a_shorba_is_a_soup_not_a_gravy():
    """Five Bangalore shorbas would have been stamped `is_nonveg_gravy`."""
    assert nonveg_structural_flags("chicken_shorba", "chicken",
                                   "north_indian") == set()


# --------------------------------------------------------------------------
# What is in the workbooks now
# --------------------------------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_every_name_classifiable_dish_carries_a_form(frames, city):
    """The hole is closed wherever the name can close it."""
    df = frames[city]
    cols = [c for c in STRUCTURAL_FLAGS if c in df.columns]
    course = df["course_type"].astype(str).str.strip().str.lower()
    missing = []
    for idx in df.index[course.eq(COMPOSED_COURSE)]:
        if _flagged(df, idx, cols):
            continue
        item = str(df.at[idx, "item"]).strip().lower()
        want = nonveg_structural_flags(
            item,
            str(df.at[idx, "primary_protein"] or "").strip().lower(),
            str(df.at[idx, "cuisine_family"] or "").strip().lower(),
            STYLE_OVERRIDES.get(item, ""))
        if want:
            missing.append(item)
    assert not missing, f"{city}: unplaceable but classifiable: {sorted(missing)}"


def test_stripes_fish_can_actually_be_placed(frames):
    """The dish the whole investigation started from."""
    df = frames["bangalore"]
    fish = df[df["item"].astype(str).str.strip().str.lower()
              .isin({"fish_finger", "tawa_fish_fry"})]
    assert len(fish) == 2
    assert (fish["is_nonveg_dry"].astype(int) == 1).all()


def test_soups_were_left_alone(frames):
    """`nonveg_soup` is not composed, and a shorba is not a gravy."""
    df = frames["bangalore"]
    soups = df[df["course_type"].astype(str).str.strip().str.lower()
               == "nonveg_soup"]
    assert not soups.empty
    named = soups[soups["item"].astype(str).str.contains("shorba", na=False)]
    assert not named.empty
    assert (named["is_nonveg_gravy"].astype(int) == 0).all()


@pytest.mark.parametrize("city", CITIES)
def test_rerunning_is_a_no_op(frames, city):
    _out, filled, _unresolved = apply(frames[city])
    assert filled == []


def test_the_unclassifiable_ones_are_reported_not_guessed(frames):
    """They are a real gap in the client's menu data, and stay visible as one."""
    df = frames["bangalore"]
    _out, _filled, unresolved = apply(df)
    assert unresolved, "expected some dishes the name cannot classify"
    assert "afghani_chicken" in unresolved
