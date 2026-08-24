"""What the Chennai item list did not hold for its four new clients.

`scripts/chennai_client_pools.py` closes five holes. Four of them fail silently
— a rule relaxes, a pin stamps text instead of narrowing a cell — and one does
not: an empty `welcome_drink` pool took TCL straight to INFEASIBLE. These tests
pin the shape of each fix rather than its exact counts, except where a count IS
the fix (a daily slot needs enough distinct dishes to outlast the cooldown).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.chennai_client_pools import (
    KOOTU_FROM_BANGALORE, KOOTU_TO_DAL, LIQUID_SWEETS, NEW_DISHES,
    VEG_BIRYANIS, WELCOME_DRINKS, main,
)
from src.ontology.paths import CITY_ITEMS_DIR


@pytest.fixture(scope="module")
def chn():
    df = pd.read_excel(CITY_ITEMS_DIR / "chennai.xlsx")
    df.columns = [c.strip() for c in df.columns]
    return df


def _names(df):
    return set(df["item"].astype(str).str.strip().str.lower())


def _course(df, course):
    return df[df["course_type"].astype(str).str.strip().str.lower() == course]


def _flag(frame, col):
    return pd.to_numeric(frame[col], errors="coerce").fillna(0).eq(1)


class TestKootuIsTheDal:
    def test_every_kootu_is_filed_as_a_dal(self, chn):
        """Three clients state 'in dal need to give only Kootu item'. Filed as
        `veg_gravy` the rule was unsatisfiable — the dal pool held zero."""
        kootu = chn[chn["sub_category"].astype(str).str.strip().str.lower()
                    == "kootu"]
        assert len(kootu) >= 16
        assert set(kootu["course_type"].astype(str).str.lower()) == {"dal"}

    def test_the_named_rows_moved_and_the_imports_arrived(self, chn):
        have = _names(chn)
        for dish in KOOTU_TO_DAL + KOOTU_FROM_BANGALORE:
            assert dish in have, dish

    def test_the_sub_category_survives_the_move(self, chn):
        """`kootu_twice_weekly` selects on `sub_category`, so the city cap has to
        keep working after the re-file — it is the rule TCL and World Bank
        deliberately disable, and ICON deliberately keeps."""
        for dish in KOOTU_TO_DAL:
            row = chn[chn["item"].astype(str).str.lower() == dish].iloc[0]
            assert str(row["sub_category"]).strip().lower() == "kootu"

    def test_the_pool_is_deep_enough_for_a_daily_kootu(self, chn):
        """TCL and World Bank serve one every day. The 20-day cooldown wants
        roughly one distinct dish per service day, and `repeatable_items` with
        `scope: cooldown` is NOT declared for the dal — so the pool has to carry
        it, or week three starves."""
        kootu = chn[chn["sub_category"].astype(str).str.strip().str.lower()
                    == "kootu"]
        assert len(_names(kootu)) >= 15

    def test_the_kootus_are_not_all_the_same_vegetable(self, chn):
        """Depth that is eight more ash-gourd kootus is not depth — the same
        argument `test_deepen_thin_pools` makes about Pune's fenugreek."""
        kootu = chn[chn["sub_category"].astype(str).str.strip().str.lower()
                    == "kootu"]
        ingredients = {str(v).strip().lower()
                       for v in kootu["key_ingredient"].dropna()}
        assert len(ingredients) >= 6, sorted(ingredients)

    def test_the_veg_gravy_pool_survived_losing_them(self, chn):
        assert len(_course(chn, "veg_gravy")) >= 45


class TestWelcomeDrinks:
    def test_chennai_now_has_a_drink_pool(self, chn):
        drinks = _course(chn, "welcome_drink")
        assert len(drinks) == len(WELCOME_DRINKS)
        assert _flag(drinks, "is_welcome_drink").all()

    def test_the_buttermilk_family_can_carry_a_daily_slot(self, chn):
        """World Bank and ICON both serve one every day. Ten dishes is fewer
        than a 20-day window needs, which is why both configs also declare
        `repeatable_items` with `scope: cooldown` — but ten is what makes the
        WITHIN-plan distinctness possible at all."""
        drinks = _course(chn, "welcome_drink")
        assert int(_flag(drinks, "is_buttermilk").sum()) >= 10

    def test_there_are_enough_non_buttermilk_drinks(self, chn):
        """TCL caps buttermilk at twice a week, so the other days need
        somewhere to go — a pool of ten buttermilks and nothing else would make
        that cap unsatisfiable rather than merely tight."""
        drinks = _course(chn, "welcome_drink")
        assert int((~_flag(drinks, "is_buttermilk")).sum()) >= 15

    def test_the_dishes_tcls_own_menu_names_are_there(self, chn):
        """SAMBARAM, INJI MOORU and NEER MOORU off the client's grid."""
        have = _names(chn)
        for dish in ("sambaram", "ginger_buttermilk", "tadka_neer_mor",
                     "buttermilk"):
            assert dish in have, dish

    def test_the_category_is_declared(self):
        """`build_pools(required_slots=…)` raises on an empty DECLARED slot, so
        declaring it turns a future regression into a build-time error naming
        the slot instead of an INFEASIBLE solve that names nothing."""
        declared = json.loads(
            (CITY_ITEMS_DIR / "ontology_categories.json").read_text())
        assert "welcome_drink" in declared["chennai"]


class TestTheTwoDishesAClientNamesDaily:
    def test_both_exist_as_real_rows(self, chn):
        """A pin naming a dish the ontology lacks is stamped verbatim, which
        prints the right menu but hides the dish from every other rule."""
        have = _names(chn)
        for spec in NEW_DISHES:
            assert spec["fields"]["item"] in have

    def test_a_boiled_egg_is_a_dry_egg_dish(self, chn):
        row = chn[chn["item"].astype(str).str.lower() == "boiled_egg"].iloc[0]
        assert str(row["course_type"]) == "nonveg_main"
        assert int(row["is_egg_dish"]) == 1
        assert int(row["is_nonveg_dry"]) == 1
        assert int(row["is_nonveg_gravy"]) == 0

    def test_bone_salna_is_a_gravy_but_not_a_chicken_gravy(self, chn):
        """Deliberate: flagging it `is_south_chicken_gravy` would let it satisfy
        every 'and a chicken gravy' component that exists to put a SECOND dish
        on the plate — World Bank's fourth non-veg cell is exactly that."""
        row = chn[chn["item"].astype(str).str.lower() == "bone_salna"].iloc[0]
        assert int(row["is_nonveg_gravy"]) == 1
        assert int(row["is_south_chicken_gravy"]) == 0
        assert int(row["is_north_chicken_gravy"]) == 0

    def test_neither_inherited_its_templates_flags(self, chn):
        """A clone starts from a real row, so every `is_*` is zeroed first and
        only the declared ones set — otherwise `egg_masala`'s gravy flag would
        follow a boiled egg onto the plate. `is_rule_ready` is exempt: it is
        derived at the end of `complete_ontology.py` from what the row holds,
        not learned, so a complete row legitimately carries it."""
        derived = {"is_rule_ready"}
        for spec in NEW_DISHES:
            row = chn[chn["item"].astype(str).str.lower()
                      == spec["fields"]["item"]].iloc[0]
            on = {c for c in chn.columns
                  if str(c).startswith("is_")
                  and pd.to_numeric([row[c]], errors="coerce")[0] == 1}
            extra = on - set(spec["flags"]) - derived
            assert not extra, extra


class TestThePoolsAStatedFrequencyOutran:
    def test_a_daily_biryani_outlasts_the_cooldown(self, chn):
        """TCL serves one in its first rice slot every weekday. Fourteen rows
        against ~15 weekday services in a 20-day window left nothing spare."""
        rice = _course(chn, "rice")
        assert int(_flag(rice, "is_biryani_item").sum()) >= 20
        have = _names(chn)
        for dish in VEG_BIRYANIS:
            assert dish in have, dish

    def test_three_liquid_sweets_a_week_has_a_pool(self, chn):
        dessert = _course(chn, "dessert")
        assert int(_flag(dessert, "is_liquid_dessert").sum()) >= 15
        have = _names(chn)
        for dish in LIQUID_SWEETS:
            assert dish in have, dish


class TestTheWorkbookItself:
    def test_every_import_is_in_the_common_pool(self, chn):
        """Chennai is in FULL_POOL_CITIES now, but a per-site token would still
        be the wrong tag for a dish every client draws on."""
        added = set(WELCOME_DRINKS) | set(VEG_BIRYANIS) | set(LIQUID_SWEETS)
        added |= set(KOOTU_FROM_BANGALORE)
        added |= {s["fields"]["item"] for s in NEW_DISHES}
        rows = chn[chn["item"].astype(str).str.lower().isin(added)]
        assert len(rows) == len(added)
        assert set(rows["client"].astype(str).str.strip()) == {"common"}

    def test_ids_and_names_are_unique(self, chn):
        assert chn["item_id"].is_unique
        assert chn["item"].astype(str).str.strip().str.lower().is_unique

    def test_the_schema_is_unchanged(self, chn):
        blr = pd.read_excel(CITY_ITEMS_DIR / "bangalore.xlsx", nrows=1)
        assert list(chn.columns) == [c.strip() for c in blr.columns]

    def test_a_second_run_changes_nothing(self, capsys):
        assert main(dry_run=True) == 0
        assert "nothing to do" in capsys.readouterr().out
