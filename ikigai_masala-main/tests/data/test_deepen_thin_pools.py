"""The three pools a client rule asked more of than the city list held.

Each was found by a rule *relaxing* rather than failing — `min`/`exact` caps
itself to what the pool can supply, so the menu was thinner than the client asked
for and nothing went red. These tests pin the depth, so a re-import that drops
the additions fails instead of quietly going thin again.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.deepen_thin_pools import COPIES, NEW_DISHES, main
from src.ontology.paths import CITY_ITEMS_DIR

CITIES = ("bangalore", "pune", "chennai", "ncr")


@pytest.fixture(scope="module")
def frames():
    return {c: pd.read_excel(CITY_ITEMS_DIR / f"{c}.xlsx") for c in CITIES}


def _course(df, course):
    return df[df["course_type"].astype(str).str.strip().str.lower() == course]


def _on(df, flag):
    return df[pd.to_numeric(df[flag], errors="coerce").fillna(0) == 1]


def _names(df):
    return set(df["item"].astype(str).str.strip().str.lower())


# --------------------------------------------------------------------------
# 1. Chennai's Chinese veg gravies
# --------------------------------------------------------------------------

class TestChennaiChineseGravies:
    def test_the_four_copies_are_present_and_chinese(self, frames):
        df = frames["chennai"]
        for name in COPIES[0][3]:
            row = df[df["item"].astype(str).str.strip() == name]
            assert not row.empty, name
            assert str(row.iloc[0]["course_type"]).lower() == "veg_gravy", name
            assert pd.to_numeric(
                row.iloc[0]["is_chinese_veg_gravy"], errors="coerce") == 1, name

    def test_the_pool_can_now_cover_more_than_one_chinese_day(self, frames):
        """One dish covered one Tuesday per 20-day cooldown window and none of
        the others; four cover a month of them."""
        pool = _on(_course(frames["chennai"], "veg_gravy"), "is_chinese_veg_gravy")
        assert len(pool) >= 4, sorted(pool["item"])

    def test_they_are_vegetarian(self, frames):
        df = frames["chennai"]
        for name in COPIES[0][3]:
            row = df[df["item"].astype(str).str.strip() == name].iloc[0]
            assert str(row["primary_protein"]).lower() in (
                "", "nan", "paneer", "soy", "tofu"), (name, row["primary_protein"])


# --------------------------------------------------------------------------
# 2. Pune's chaat starters
# --------------------------------------------------------------------------

class TestPuneChaatStarters:
    def test_the_four_copies_are_starters(self, frames):
        df = frames["pune"]
        for name in COPIES[1][3]:
            row = df[df["item"].astype(str).str.strip() == name]
            assert not row.empty, name
            assert str(row.iloc[0]["course_type"]).lower() == "starter", name

    def test_a_thursday_chaat_now_outlasts_the_cooldown(self, frames):
        """Corning Chakan serves a chaat starter every Thursday. Four dishes was
        exactly four Thursdays inside the window with nothing spare; the rule can
        now miss a week without running out."""
        starters = _course(frames["pune"], "starter")
        chaats = starters[starters["item"].astype(str).str.lower()
                          .str.contains("chaat|chat", regex=True)]
        assert len(chaats) >= 6, sorted(chaats["item"])

    def test_the_additions_did_not_duplicate_pune_s_own_papdi_chaat(self, frames):
        """`papadi_chaat` (Pune) and `papdi_chaat` (Bangalore) are the same dish
        spelled two ways, so only the curd version was taken — copying the plain
        one would have put the same chaat in the pool twice under `unique_items`.
        """
        names = _names(frames["pune"])
        assert "dahi_papdi_chaat" in names
        assert "papdi_chaat" not in names

    def test_pune_stays_all_vegetarian(self, frames):
        proteins = set(frames["pune"]["primary_protein"].fillna("")
                       .astype(str).str.strip().str.lower())
        for meat in ("chicken", "mutton", "lamb", "fish", "prawn", "egg"):
            assert meat not in proteins, meat


# --------------------------------------------------------------------------
# 3. Pune's leafy veg dries
# --------------------------------------------------------------------------

class TestPuneLeafyVegDry:
    _SPEC = NEW_DISHES[0]

    def test_the_four_new_dishes_are_leafy_veg_dries(self, frames):
        df = frames["pune"]
        for dish in self._SPEC["dishes"]:
            row = df[df["item"].astype(str).str.strip() == dish["item"]]
            assert not row.empty, dish["item"]
            r = row.iloc[0]
            assert str(r["course_type"]).lower() == "veg_dry", dish["item"]
            assert pd.to_numeric(
                r["is_leafy_based_dish"], errors="coerce") == 1, dish["item"]
            assert str(r["item_color"]).lower() == "green", dish["item"]

    def test_twice_a_week_is_now_servable_across_the_cooldown(self, frames):
        """Corning Chakan wants a leafy dry TWICE a week, which needs about eight
        distinct dishes inside the 20-day window. Pune had five, three of them
        fenugreek."""
        leafy = _on(_course(frames["pune"], "veg_dry"), "is_leafy_based_dish")
        assert len(leafy) >= 8, sorted(leafy["item"])

    def test_the_greens_are_actually_different_greens(self, frames):
        """Depth that is three more fenugreek dishes is not depth: the point is
        distinct ingredients, which is also what `attribute_grouping` reads."""
        leafy = _on(_course(frames["pune"], "veg_dry"), "is_leafy_based_dish")
        kinds = set(leafy["key_ingredient"].fillna("").astype(str).str.lower())
        kinds.discard("")
        assert len(kinds) >= 4, kinds

    def test_every_key_ingredient_is_one_the_ontology_already_uses(self, frames):
        """A new synonym would be invisible to every rule naming the old one —
        the same argument `marathi_ingredient_names.py` makes."""
        others = pd.concat([frames[c] for c in CITIES if c != "pune"])
        known = set(others["key_ingredient"].fillna("").astype(str)
                    .str.strip().str.lower())
        for dish in self._SPEC["dishes"]:
            assert dish["key_ingredient"] in known, dish

    def test_the_new_rows_carry_no_inherited_flags(self, frames):
        """Cloned from a template row, so an `is_deep_fried` or `is_premium` from
        the template would silently make these dishes something they are not."""
        df = frames["pune"]
        flags = [c for c in df.columns if str(c).startswith("is_")]
        allowed = set(self._SPEC["flags"])
        for dish in self._SPEC["dishes"]:
            row = df[df["item"].astype(str).str.strip() == dish["item"]].iloc[0]
            on = {f for f in flags
                  if pd.to_numeric(row[f], errors="coerce") == 1}
            assert on <= allowed, (dish["item"], sorted(on - allowed))


# --------------------------------------------------------------------------
# Shape and idempotence
# --------------------------------------------------------------------------

class TestShape:
    def test_the_schema_is_unchanged_and_shared(self, frames):
        widths = {c: len(df.columns) for c, df in frames.items()}
        assert set(widths.values()) == {134}, widths

    @pytest.mark.parametrize("city", CITIES)
    def test_no_duplicate_names_or_ids(self, frames, city):
        df = frames[city]
        assert not df["item"].astype(str).str.strip().str.lower().duplicated().any()
        assert not df["item_id"].duplicated().any()

    def test_the_pool_token_follows_each_city_s_convention(self, frames):
        for city, _src, _course_name, names in COPIES:
            df = frames[city]
            for name in names:
                row = df[df["item"].astype(str).str.strip() == name].iloc[0]
                assert str(row["client"]).strip().lower() == "common", name

    def test_rerunning_adds_nothing(self, capsys):
        main(dry_run=True)
        out = capsys.readouterr().out
        assert "already present" in out, out
        assert "nothing to add" in out or "+0" not in out, out
