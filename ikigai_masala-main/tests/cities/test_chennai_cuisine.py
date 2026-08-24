"""Chennai's Indian dishes are not continental.

`ThemeSlotFilterRule._exclude_offtheme_cuisines` drops a continental dish on
every day that is not a continental day, and **no Chennai client themes any day
continental** — so a mislabelled row is not merely mis-described, it is
unservable. It sits in the pool, passes every diagnostic, and is never chosen.

That is why this was found by a rule *relaxing* rather than failing: World Bank
asks for a chicken gravy every day, and by week three of a saved run it served
one on three days of five, filling the gaps with an egg dosa. Chennai looked
like it had 25 chicken gravies. It had 13.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.chennai_cuisine_corrections import (
    BY_SUB_CATEGORY, CUISINE_MAIN_SLOTS, KEEP_CONTINENTAL, apply,
    corrections, main, unresolved,
)
from src.ontology.paths import CITY_ITEMS_DIR


@pytest.fixture(scope="module")
def chn():
    df = pd.read_excel(CITY_ITEMS_DIR / "chennai.xlsx")
    df.columns = [c.strip() for c in df.columns]
    return df


def _cuisine(df):
    return df["cuisine_family"].astype(str).str.strip().str.lower()


def _course(df):
    return df["course_type"].astype(str).str.strip().str.lower()


class TestNothingIndianIsFiledContinental:
    def test_no_chicken_curry_is_continental(self, chn):
        """Every one of these contradicted itself: `cuisine_family =
        continental` on a row whose `sub_category` is `chicken_north_masala`.
        The sub_category is the column that knows."""
        nv = chn[_course(chn) == "nonveg_main"]
        wrong = nv[_cuisine(nv) == "continental"]
        assert list(wrong["item"]) == [], list(wrong["item"])

    def test_no_pakora_or_vada_is_continental(self, chn):
        """`vada`, `bonda`, `masala_vada` and the `65` family are Tamil tiffin.
        Seventeen of them were continental, so Chennai's starter slot lost most
        of its pool on every day."""
        st = chn[_course(chn) == "starter"]
        wrong = st[(_cuisine(st) == "continental")
                   & (st["sub_category"].astype(str).str.strip().str.lower()
                      == "pakora_/_bajji")]
        assert list(wrong["item"]) == [], list(wrong["item"])

    def test_the_named_rows_landed_where_the_sub_category_says(self, chn):
        by_item = chn.set_index(chn["item"].astype(str).str.strip().str.lower())
        for dish, want in (("butter_chicken", "north_indian"),
                           ("chicken_kurma", "north_indian"),
                           ("bbq_chicken", "north_indian"),
                           ("pepper_chicken_curry", "south_indian"),
                           ("masala_vada", "south_indian"),
                           ("mushroom_pepper_fry", "south_indian")):
            got = str(by_item.at[dish, "cuisine_family"]).strip().lower()
            assert got == want, (dish, got)


class TestWhatStaysContinental:
    def test_the_pasta_and_the_cutlet_are_left_alone(self, chn):
        """The counter-case that keeps the fix honest: a penne alfredo IS
        continental, and correcting it would be as wrong as leaving a butter
        chicken mislabelled."""
        by_item = chn.set_index(chn["item"].astype(str).str.strip().str.lower())
        for dish in KEEP_CONTINENTAL:
            assert str(by_item.at[dish, "cuisine_family"]).strip().lower() \
                == "continental", dish

    def test_salads_and_soups_are_not_touched(self, chn):
        """They are not cuisine-main slots, so the exclusivity filter never
        looks at them — a continental salad costs nothing and retagging one
        would be a change with no reason behind it."""
        side = chn[~_course(chn).isin(CUISINE_MAIN_SLOTS)]
        assert int((_cuisine(side) == "continental").sum()) >= 30


class TestTheEffect:
    def test_the_chicken_gravy_pool_is_deep_enough_for_a_daily_slot(self, chn):
        """World Bank serves one every day. A 20-day cooldown wants roughly one
        distinct dish per service day, and 13 was not enough — week three of a
        saved run ran out."""
        nv = chn[_course(chn) == "nonveg_main"]
        gravy = (pd.to_numeric(nv["is_north_chicken_gravy"], errors="coerce").fillna(0).eq(1)
                 | pd.to_numeric(nv["is_south_chicken_gravy"], errors="coerce").fillna(0).eq(1))
        servable = gravy & (_cuisine(nv) != "continental")
        assert int(servable.sum()) >= 20, int(servable.sum())

    def test_the_starter_pool_survived_being_unblocked(self, chn):
        st = chn[_course(chn) == "starter"]
        assert int((_cuisine(st) != "continental").sum()) >= 55


class TestTheScriptItself:
    def test_it_refuses_to_guess_an_unmapped_sub_category(self):
        """A re-import can add a continental row whose sub_category names no
        region. It is reported, not assigned — the same contract
        `nonveg_structural_flags.py` keeps for a dish whose form its name does
        not say."""
        df = pd.DataFrame([{
            "item": "mystery_dish", "course_type": "nonveg_main",
            "cuisine_family": "continental", "sub_category": "something_new",
        }])
        assert corrections(df) == []
        assert unresolved(df) == ["mystery_dish (something_new)"]

    def test_it_corrects_a_planted_mislabel(self):
        df = pd.DataFrame([{
            "item": "planted_chicken", "course_type": "nonveg_main",
            "cuisine_family": "continental",
            "sub_category": "chicken_north_masala",
        }])
        assert apply(df) == [("planted_chicken", "chicken_north_masala",
                              "north_indian")]
        assert df.at[0, "cuisine_family"] == "north_indian"

    def test_every_mapped_sub_category_names_a_real_region(self):
        assert set(BY_SUB_CATEGORY.values()) == {"north_indian", "south_indian"}

    def test_a_second_run_changes_nothing(self, capsys):
        assert main(dry_run=True) == 0
        assert "no continental mislabels" in capsys.readouterr().out
