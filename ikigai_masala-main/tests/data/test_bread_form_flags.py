"""`is_plain_phulka_chapathi` means one thing, in both directions.

Four clients state their bread rule as "chapati only" and Pune's R36 makes the
plain chapati a staple, so this column decides what lands in a bread slot. It
was wrong both ways: set on 19 NCR rows that are not chapatis (three of them not
even breads) and on a puri, a bhel puri and a millet ball in Bangalore, and
absent from every `chapati`-spelled row in every city.

`scripts/bread_form_flags.py` derives it from the dish name. These tests pin the
committed workbooks, the predicate's edge cases, and that a re-run changes
nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.bread_form_flags import (
    CITIES, FLAG, apply, is_chapati,
)
from src.ontology.paths import CITY_ITEMS_DIR


@pytest.fixture(scope="module")
def frames():
    return {c: pd.read_excel(CITY_ITEMS_DIR / f"{c}.xlsx") for c in CITIES}


def _flagged(df):
    on = pd.to_numeric(df[FLAG], errors="coerce").fillna(0).astype(int) == 1
    return sorted(df.loc[on, "item"].astype(str).str.strip().str.lower())


# --------------------------------------------------------------------------
# The predicate
# --------------------------------------------------------------------------

class TestPredicate:
    @pytest.mark.parametrize("name", [
        "plain_chapati", "plain_chapatti", "chapati", "plain_phulka",
        "methi_chapati", "butter_chapati", "masala_chapati",
        # A roti is the same bread under another name, when it is wheat.
        "tawa_roti", "butter_roti", "garlic_roti", "wheat_palak_roti",
    ])
    def test_the_everyday_wheat_flatbread_is_a_chapati(self, name):
        assert is_chapati(name, "bread"), name

    @pytest.mark.parametrize("name", [
        # A different grain is a different bread — and the ontology already
        # treats the majority of these as not a chapati.
        "akki_roti", "ragi_roti", "jowar_roti", "bajra_roti", "rava_roti",
        "multigrain_roti", "joleda_roti", "coorg_roti", "makki_roti",
        # A named speciality or a tandoor bread, which Clario's own menu lists
        # as a *special* bread rather than the chapati.
        "rumali_roti", "romali_roti", "tandoori_roti", "tandoor_butter_roti",
        "missi_roti",
        # A different bread form entirely.
        "amras_puri", "bhel_puri", "bhelpuri", "cholay_kulcha",
        "ajjwaini_paratha", "kerala_parotta", "butter_naan", "pav_bhaji",
        "pao", "fried_idli", "ragi_mudde",
        # A combination cell a menu import split badly: it names two dishes,
        # and the other one is not a chapati.
        "jeera_chapati_dosa", "triangle_chapati_puri", "puri_chapati_chutney",
        "appam_chapati",
        # Not a bread at all.
        "jodhpuri_pulao", "aloo_gobi",
    ])
    def test_everything_else_is_not(self, name):
        assert not is_chapati(name, "bread"), name

    def test_the_course_gates_it(self):
        """A bread flag on a curry is the defect this script removes, so the
        predicate refuses to set it outside `course_type == bread` whatever the
        name says."""
        assert not is_chapati("dhaba_chicken_curry", "nonveg_main")
        assert not is_chapati("kolhapuri_chicken", "nonveg_main")
        assert not is_chapati("chapati_soup", "soup")
        assert is_chapati("plain_chapati", "bread")

    def test_the_match_is_token_scoped_not_substring(self):
        """`kolhapuri` contains "puri" and `jodhpuri` contains "puri", but
        neither is a puri — the same trap `audit_course_types.py` documents."""
        assert is_chapati("kolhapuri_chapati", "bread")
        assert not is_chapati("kolhapuri_paneer", "bread")

    def test_case_and_spacing_do_not_matter(self):
        assert is_chapati(" Plain Chapati ", "Bread")
        assert is_chapati("PLAIN-PHULKA", "bread")


# --------------------------------------------------------------------------
# The committed workbooks
# --------------------------------------------------------------------------

class TestCommittedWorkbooks:
    def test_no_flagged_row_is_outside_the_bread_course(self, frames):
        for city, df in frames.items():
            on = pd.to_numeric(df[FLAG], errors="coerce").fillna(0) == 1
            courses = set(df.loc[on, "course_type"].astype(str).str.lower())
            assert courses <= {"bread"}, (city, courses)

    def test_every_flagged_row_is_a_chapati_phulka_or_wheat_roti(self, frames):
        for city, df in frames.items():
            for name in _flagged(df):
                assert is_chapati(name, "bread"), (city, name)

    def test_every_chapati_named_bread_carries_the_flag(self, frames):
        """The half that was missing: `plain_chapati`, `garlic_chapati` and the
        seven curated flavoured chapatis were unflagged in every city, so a rule
        about chapatis could not see them."""
        for city, df in frames.items():
            breads = df[df["course_type"].astype(str).str.lower() == "bread"]
            on = pd.to_numeric(breads[FLAG], errors="coerce").fillna(0) == 1
            for name in breads.loc[~on, "item"].astype(str).str.strip().str.lower():
                assert not is_chapati(name, "bread"), (city, name)

    @pytest.mark.parametrize("gone", [
        "dhaba_chicken_curry", "kolhapuri_chicken", "egg_curry_masala",
        "jodhpuri_pulao", "pav_bhaji", "pao", "roasted_pao", "fried_idli",
        "bhelpuri", "mumbai_bhelpuri", "bhel_poori", "cholay_poori",
        "vrat_poori", "jai_poori_aloo_pyaaz", "cholay_kulcha", "matar_kulcha",
        "dilli_waley_matar_kulcha", "ajjwaini_paratha", "tikona_paratha",
        "multigrain_roti", "romali_roti",
        "amras_puri", "bhel_puri", "ragi_mudde", "missi_roti", "rava_roti",
        "coorg_roti", "tandoor_butter_roti",
    ])
    def test_the_named_offenders_no_longer_carry_the_flag(self, frames, gone):
        for city, df in frames.items():
            assert gone not in _flagged(df), (city, gone)

    def test_the_pool_is_deep_enough_for_a_daily_chapati_slot(self, frames):
        """Citrix, AT&T and Booking all run one bread a day. Under a 20-day
        cooldown that needs roughly one distinct dish per working day in the
        window; Chennai is short of that, which is why Chennai's ruleset also
        declares the plain chapati a staple."""
        counts = {c: len(_flagged(df)) for c, df in frames.items()}
        assert counts["bangalore"] >= 20, counts
        assert counts["ncr"] >= 8, counts
        # Chennai and Pune are thin on purpose — the staple declaration is what
        # keeps their bread slot fillable, and it is asserted elsewhere.
        assert all(n >= 2 for n in counts.values()), counts

    def test_the_flag_is_not_what_the_staple_exemption_selects_on(self, frames):
        """Widening this flag must NOT widen a no-repeat exemption.

        Pune's R36 and Chennai's `plain_chapati_may_repeat` used to select on it,
        and this correction took Pune from 2 flagged rows to 9 — which would have
        licensed a beetroot chapati every day as a side effect of a data fix.
        Both rules now name the two plain dishes, so the flag is free to mean
        what a "chapati only" bread rule needs it to mean.
        """
        from src.menu_rules import MenuRuleLoader
        for city in ('Pune', 'Chennai'):
            rule = next(r for r in MenuRuleLoader().load_for_city(city)
                        if r.name == 'plain_chapati_may_repeat')
            assert rule._inc[0] != 'flag', (city, rule._inc)

    def test_the_flag_still_matches_something_in_every_city(self, frames):
        """A "chapati only" bread rule that matched nothing would starve the
        slot, so an emptied flag is a blocking regression, not a tidy-up."""
        for city, df in frames.items():
            assert _flagged(df), city


class TestIdempotent:
    def test_a_second_pass_changes_nothing(self, frames):
        for city, df in frames.items():
            out, gained, lost = apply(df)
            assert not gained and not lost, (city, gained, lost)

    def test_apply_does_not_mutate_its_input(self, frames):
        df = frames["bangalore"]
        before = df[FLAG].tolist()
        apply(df)
        assert df[FLAG].tolist() == before

    def test_a_planted_wrong_flag_is_cleared(self, frames):
        """So the guard cannot pass vacuously."""
        df = frames["bangalore"].copy()
        idx = df.index[df["course_type"].astype(str).str.lower()
                       == "nonveg_main"][0]
        df.at[idx, FLAG] = 1
        out, gained, lost = apply(df)
        assert df.at[idx, "item"] in lost
        assert pd.to_numeric(out.at[idx, FLAG]) == 0

    def test_a_planted_missing_flag_is_set(self, frames):
        df = frames["bangalore"].copy()
        idx = df.index[df["item"].astype(str).str.strip().str.lower()
                       == "plain_chapati"]
        if not len(idx):                                 # pragma: no cover
            pytest.skip("plain_chapati not in this workbook")
        df.at[idx[0], FLAG] = 0
        out, gained, lost = apply(df)
        assert "plain_chapati" in [g.strip().lower() for g in gained]
        assert pd.to_numeric(out.at[idx[0], FLAG]) == 1
