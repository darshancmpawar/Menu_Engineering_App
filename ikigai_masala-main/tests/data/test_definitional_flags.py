"""`is_liquid_dessert` and `is_buttermilk` mean one thing, in both directions.

A flag that is only ever SET drifts — the argument `seafood_taxonomy.py` made
for `is_fish_dish` and `bread_form_flags.py` for `is_plain_phulka_chapathi`.
These two are the same shape and both are load-bearing for a shipped client
rule: Corning Chakan bans liquid sweets outright, and Citrix, World Bank and
ICON Chn each serve buttermilk daily or twice a week.

The failure that prompted this was a false POSITIVE, which is the direction a
fill-only script can never fix: NCR carried `is_liquid_dessert` on 55 pethas,
laddus, cakes and brownies, learned by a token vote from a dessert list that is
mostly payasams.
"""

from __future__ import annotations

import pathlib

import pandas as pd
import pytest

from scripts.definitional_flags import (
    BUTTERMILK_NAMES, BUTTERMILK_WORDS, CITIES, COURSE_INGREDIENT_FLAGS,
    DEFINITIONS, LIQUID_DESSERT_WORDS, REFILE_TO_WELCOME_DRINK, enforce,
    enforce_ingredient, has_ingredient, main, matches,
)
from src.menu_rules.menu_rule_loader import CITY_RULES_DIR
from src.ontology.paths import CITY_ITEMS_DIR

CLIENT_DIR = CITY_ITEMS_DIR.parent.parent / "configs" / "clients"


@pytest.fixture(scope="module")
def frames():
    out = {}
    for city in CITIES:
        df = pd.read_excel(CITY_ITEMS_DIR / f"{city}.xlsx")
        df.columns = [c.strip() for c in df.columns]
        out[city] = df
    return out


def _flag(frame, col):
    return pd.to_numeric(frame[col], errors="coerce").fillna(0).eq(1)


class TestThePredicate:
    def test_a_payasam_is_liquid_and_a_laddu_is_not(self):
        assert matches("semiya_payasam", LIQUID_DESSERT_WORDS, set())
        assert matches("rose_kheer", LIQUID_DESSERT_WORDS, set())
        assert matches("sheer_korma", LIQUID_DESSERT_WORDS, set())
        assert not matches("motichur_laddu", LIQUID_DESSERT_WORDS, set())
        assert not matches("achari_petha", LIQUID_DESSERT_WORDS, set())
        assert not matches("red_velvet_brownie", LIQUID_DESSERT_WORDS, set())

    def test_a_two_word_name_needs_the_whole_name_list(self):
        """`butter_milk` tokenises to `butter` + `milk`, neither of which is a
        drink word — which is also why `audit_course_types.py` missed the three
        buttermilk drinks filed as gravies."""
        assert not matches("butter_milk", BUTTERMILK_WORDS, set())
        assert matches("butter_milk", BUTTERMILK_WORDS, BUTTERMILK_NAMES)
        assert matches("spiced_buttermilk", BUTTERMILK_WORDS, set())


class TestBothDirections:
    def test_no_dessert_outside_the_definition_carries_the_flag(self, frames):
        for city, df in frames.items():
            d = df[df["course_type"].astype(str).str.strip().str.lower()
                   == "dessert"]
            wrong = [r["item"] for _i, r in d[_flag(d, "is_liquid_dessert")].iterrows()
                     if not matches(r["item"], LIQUID_DESSERT_WORDS, set())]
            assert wrong == [], (city, wrong[:8])

    def test_no_liquid_dessert_is_left_unflagged(self, frames):
        for city, df in frames.items():
            d = df[df["course_type"].astype(str).str.strip().str.lower()
                   == "dessert"]
            missed = [r["item"] for _i, r in d[~_flag(d, "is_liquid_dessert")].iterrows()
                      if matches(r["item"], LIQUID_DESSERT_WORDS, set())]
            assert missed == [], (city, missed[:8])

    def test_the_buttermilk_flag_matches_the_definition(self, frames):
        for city, df in frames.items():
            d = df[df["course_type"].astype(str).str.strip().str.lower()
                   == "welcome_drink"]
            if not len(d):
                continue
            flagged = _flag(d, "is_buttermilk")
            for i, r in d.iterrows():
                want = matches(r["item"], BUTTERMILK_WORDS, BUTTERMILK_NAMES)
                assert want == bool(flagged[i]), (city, r["item"], want)

    def test_the_scope_is_the_course_and_nothing_wider(self, frames):
        """`mor_kuzhambu` and `majjige_huli` ARE buttermilk curries and belong
        in `veg_gravy`; `mor_rasam` is a rasam. Widening the buttermilk family
        past `welcome_drink` would put a gravy in the drink slot's rules.

        The same clear caught the one nobody would have looked for: NCR's
        `kheera_raita` carried `is_liquid_dessert`, the token vote having read
        "kheera" as "kheer"."""
        for city, df in frames.items():
            outside = df[df["course_type"].astype(str).str.strip().str.lower()
                         != "welcome_drink"]
            assert not _flag(outside, "is_buttermilk").any(), city
            not_dessert = df[df["course_type"].astype(str).str.strip().str.lower()
                             != "dessert"]
            assert not _flag(not_dessert, "is_liquid_dessert").any(), city


class TestTheThreeMisfiledDrinks:
    def test_a_buttermilk_drink_is_not_a_gravy(self, frames):
        """`butter_milk` and `masala_chaas` sat in `veg_gravy`, so a Delhi
        counter could serve "Butter Milk" as the day's gravy."""
        for city, wanted in REFILE_TO_WELCOME_DRINK.items():
            df = frames[city]
            for dish in wanted:
                row = df[df["item"].astype(str).str.lower() == dish]
                assert len(row) == 1, (city, dish)
                assert str(row.iloc[0]["course_type"]) == "welcome_drink"

    def test_the_buttermilk_curries_were_left_alone(self, frames):
        """The other half of the same call: `majjige_huli` stays a veg gravy."""
        blr = frames["bangalore"]
        huli = blr[blr["item"].astype(str).str.contains("majjige_huli", na=False)]
        assert len(huli) >= 3
        assert set(huli["course_type"].astype(str)) == {"veg_gravy", "curd_side"}


class TestEnforceItself:
    def test_it_clears_a_planted_false_positive(self):
        df = pd.DataFrame([
            {"item": "motichur_laddu", "course_type": "dessert",
             "is_liquid_dessert": 1},
            {"item": "rice_kheer", "course_type": "dessert",
             "is_liquid_dessert": 0},
        ])
        was_set, cleared = enforce(df, "is_liquid_dessert", "dessert",
                                   LIQUID_DESSERT_WORDS, set())
        assert was_set == ["rice_kheer"]
        assert cleared == ["motichur_laddu"]
        assert list(df["is_liquid_dessert"]) == [0, 1]

    def test_it_never_sets_the_flag_outside_the_course(self):
        """A buttermilk rasam is a rasam. The name matches the family, but the
        rule that reads this column is about the day's DRINK, so the course is
        what decides — and the flag is cleared rather than set."""
        df = pd.DataFrame([
            {"item": "mor_rasam", "course_type": "rasam", "is_buttermilk": 1},
            {"item": "majjige_huli", "course_type": "veg_gravy",
             "is_buttermilk": 0},
        ])
        was_set, cleared = enforce(df, "is_buttermilk", "welcome_drink",
                                   BUTTERMILK_WORDS, BUTTERMILK_NAMES)
        assert was_set == []
        assert cleared == ["mor_rasam"]
        assert list(df["is_buttermilk"]) == [0, 0]

    def test_every_definition_names_a_course(self):
        for _flag_name, course, tokens, _names in DEFINITIONS:
            assert course and tokens


class TestThePaneerFlags:
    """`is_paneer_fry` was empty in all four cities while a shipped rule
    selected on it, and `is_paneer_gravy` — the twin that populated it — is what
    the `key_ingredient` column produces, which in this ontology means "Chinese"
    as often as it means "paneer"."""

    def test_the_predicate_reads_the_protein_column_and_the_name(self):
        assert has_ingredient({"item": "matar_paneer", "primary_protein": ""},
                              {"paneer"}, {"paneer", "cottage_cheese"})
        assert has_ingredient({"item": "malai_kofta", "primary_protein": "paneer"},
                              {"paneer"}, {"paneer", "cottage_cheese"})
        assert has_ingredient(
            {"item": "creole_spiced_grilled_cottage_cheese",
             "primary_protein": ""}, {"paneer"}, {"paneer", "cottage_cheese"})

    def test_it_does_not_read_key_ingredient(self):
        """The whole point. `thai_green_curry` and `bok_choy` carry
        `key_ingredient = paneer` and are not paneer dishes — that column is the
        de-facto default for a Chinese row, exactly as `baby_corn` is for a mixed
        salad."""
        for dish in ("thai_green_curry", "bok_choy", "chilli_gobi",
                     "gobi_salt_and_pepper", "fried_momos", "veg_chilli_fry"):
            assert not has_ingredient(
                {"item": dish, "key_ingredient": "paneer", "primary_protein": ""},
                {"paneer"}, {"paneer", "cottage_cheese"}), dish

    def test_enforce_clears_a_planted_thai_curry_and_sets_a_real_paneer(self):
        df = pd.DataFrame([
            {"item": "thai_green_curry", "course_type": "veg_gravy",
             "primary_protein": "", "is_paneer_gravy": 1},
            {"item": "matar_paneer", "course_type": "veg_gravy",
             "primary_protein": "paneer", "is_paneer_gravy": 0},
        ])
        was_set, cleared = enforce_ingredient(
            df, "is_paneer_gravy", "veg_gravy", {"paneer"},
            {"paneer", "cottage_cheese"})
        assert was_set == ["matar_paneer"]
        assert cleared == ["thai_green_curry"]

    def test_the_course_still_scopes_it(self):
        """A paneer tikka is a starter, not a gravy and not a veg dry."""
        df = pd.DataFrame([
            {"item": "paneer_tikka", "course_type": "starter",
             "primary_protein": "paneer", "is_paneer_fry": 1},
        ])
        was_set, cleared = enforce_ingredient(
            df, "is_paneer_fry", "veg_dry", {"paneer"},
            {"paneer", "cottage_cheese"})
        assert was_set == []
        assert cleared == ["paneer_tikka"]

    @pytest.mark.parametrize("city,flag,course", [
        (c, f, co) for c in ("bangalore", "chennai", "pune", "ncr")
        for f, co in (("is_paneer_gravy", "veg_gravy"),
                      ("is_paneer_fry", "veg_dry"))
    ])
    def test_the_shipped_workbooks_agree_with_the_definition(
            self, frames, city, flag, course):
        df = frames[city]
        in_course = df["course_type"].astype(str).str.strip().str.lower().eq(course)
        should = df.apply(
            lambda r: has_ingredient(r, {"paneer"},
                                     {"paneer", "cottage_cheese"}), axis=1) & in_course
        assert list(df.loc[_flag(df, flag) ^ should, "item"]) == []

    def test_is_paneer_fry_is_no_longer_empty_where_a_rule_reads_it(self, frames):
        """Zscaler is a Bangalore client and asks for exactly one paneer fry a
        week. `min` caps itself to what the pool can place, so an empty selector
        made the rule inert rather than failing — it had never constrained
        anything."""
        assert int(_flag(frames["bangalore"], "is_paneer_fry").sum()) >= 10

    def test_no_flag_column_a_config_reads_is_empty_in_every_city(self, frames):
        """The general form of the bug. A flag no row carries matches nothing,
        and a rule selecting on it is silently inert."""
        referenced = set()
        for directory in (CLIENT_DIR, pathlib.Path(CITY_RULES_DIR)):
            for p in sorted(directory.glob("*.json")):
                blob = p.read_text(encoding="utf-8")
                for col in frames["bangalore"].columns:
                    if col.startswith("is_") and f'"{col}"' in blob:
                        referenced.add(col)
        assert referenced, "no flag columns referenced — the scan found nothing"
        empty = [
            col for col in sorted(referenced)
            if all(int(_flag(frames[c], col).sum()) == 0
                   for c in CITIES if col in frames[c].columns)
        ]
        assert empty == [], empty


class TestConvergence:
    def test_a_second_run_changes_nothing(self, capsys):
        assert main(dry_run=True) == 0
        assert "nothing to do" in capsys.readouterr().out

    def test_the_token_vote_will_not_undo_it(self):
        """`complete_ontology.py` learned `is_liquid_dessert` from a mostly-
        payasam dessert list and would set it again on the next chain run, in
        whichever order the two scripts go — so it has to stand down. The two
        paneer flags are there for the matching reason on `key_ingredient`."""
        from scripts.complete_ontology import OWNED_ELSEWHERE
        assert ("is_liquid_dessert", "dessert") in OWNED_ELSEWHERE
        assert ("is_buttermilk", "welcome_drink") in OWNED_ELSEWHERE
        assert ("is_paneer_gravy", "veg_gravy") in OWNED_ELSEWHERE
        assert ("is_paneer_fry", "veg_dry") in OWNED_ELSEWHERE
