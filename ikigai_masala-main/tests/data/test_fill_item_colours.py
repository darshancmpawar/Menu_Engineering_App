"""`item_color` drives the only rule that keeps a plate from being five browns.

`MenuSolver._add_color_constraints` clamps the day's required distinct colours to
the number actually PRESENT among the candidates, so a blank colour does not
merely go unchecked — it quietly relaxes the rule for every day it appears on.
That is what made 2,440 blank rows worth attacking rather than tolerating.

These tests pin the tiers, the measured thresholds, the fixed point, and the
determinism of the report — the last because a derived artefact that will not
reproduce cannot be tested at all.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.fill_item_colours import (
    CITIES, MIN_ATTR_AGREEMENT, MIN_ATTR_ROWS, MIN_TOKEN_AGREEMENT,
    MIN_TOKEN_ROWS, apply, colour_bearing_attributes, colour_bearing_flags,
    colour_bearing_tokens, colour_by_name, group_questions, infer, _known,
)
from src.ontology.paths import CITY_ITEMS_DIR

VOCAB = {"brown", "red", "green", "yellow", "white", "orange", "black"}


@pytest.fixture(scope="module")
def frames():
    return {c: pd.read_excel(CITY_ITEMS_DIR / f"{c}.xlsx") for c in CITIES}


@pytest.fixture(scope="module")
def learned(frames):
    known = _known(frames)
    return {
        "known": known,
        "by_name": colour_by_name(known),
        "tokens": colour_bearing_tokens(known),
        "attrs": colour_bearing_attributes(known),
        "flags": colour_bearing_flags(known),
    }


class TestTheColumnItself:
    def test_every_colour_is_in_the_vocabulary(self, frames):
        for city, df in frames.items():
            got = set(df["item_color"].dropna().astype(str).str.strip().str.lower())
            assert got <= VOCAB, (city, got - VOCAB)

    def test_the_fill_actually_moved_the_needle(self, frames):
        """Two thirds of the list was already coloured; the fill took it past
        four fifths. The exact figures are not pinned — new imports change them
        — but a regression that dropped coverage back below 75% would mean the
        colour rule had gone quiet again."""
        total = sum(len(df) for df in frames.values())
        coloured = sum(int(df["item_color"].notna().sum()) for df in frames.values())
        assert coloured / total >= 0.75, f"{coloured}/{total}"

    def test_no_city_is_left_mostly_blank(self, frames):
        for city, df in frames.items():
            share = int(df["item_color"].notna().sum()) / len(df)
            assert share >= 0.60, (city, share)


class TestTiers:
    def test_a_dish_coloured_elsewhere_settles_the_copy(self):
        colour, why = infer("palak_paneer", {"palak_paneer": "green"}, {})
        assert colour == "green"
        assert "another city" in why

    def test_the_token_vote_needs_an_outright_majority(self):
        tokens = {"palak": "green", "tomato": "red"}
        colour, why = infer("palak_tomato_curry", {}, tokens)
        assert colour is None and "disagree" in why
        colour, _ = infer("palak_methi_tomato", {}, {**tokens, "methi": "green"})
        assert colour == "green"

    def test_an_attribute_is_used_only_when_the_name_says_nothing(self, learned):
        """Order of evidence matters: a name that carries a colour word must not
        be overruled by a blunter signal."""
        row = pd.Series({"course_type": "veg_dry", "key_ingredient": "spinach"})
        attrs = {(("course_type", "key_ingredient"), ("veg_dry", "spinach")): "green"}
        colour, why = infer("mystery_dish", {}, {}, row, attrs, {})
        assert colour == "green" and "key_ingredient" in why
        # …but a name with a colour-bearing word wins.
        colour, why = infer("tomato_thing", {}, {"tomato": "red"}, row, attrs, {})
        assert colour == "red" and "token vote" in why

    def test_a_form_flag_is_the_last_resort(self, learned):
        row = pd.Series({"course_type": "x", "is_leafy_based_dish": 1})
        colour, why = infer("nameless", {}, {}, row, {}, {"is_leafy_based_dish": "green"})
        assert colour == "green" and "flag" in why

    def test_the_learned_flags_include_the_ones_worth_having(self, learned):
        flags = learned["flags"]
        assert flags.get("is_leafy_based_dish") == "green"
        assert all(c in VOCAB for c in flags.values())

    def test_every_learned_rule_meets_its_stated_threshold(self, learned):
        """The thresholds are the whole argument for trusting this data, so they
        must be what the code actually applied."""
        assert MIN_TOKEN_ROWS == 6 and MIN_TOKEN_AGREEMENT == 0.70
        assert MIN_ATTR_ROWS == 8 and MIN_ATTR_AGREEMENT == 0.85
        assert all(c in VOCAB for c in learned["tokens"].values())
        assert all(c in VOCAB for c in learned["attrs"].values())


class TestFixedPointAndIdempotence:
    def test_a_further_pass_fills_nothing(self, frames, learned):
        """`main()` loops to a fixed point because each colour filled is
        evidence for the next pass. Without the loop one invocation left 77 rows
        a second would have taken, so the correction chain did not converge."""
        for city, df in frames.items():
            _out, filled, _left = apply(
                df, learned["by_name"], learned["tokens"],
                learned["attrs"], learned["flags"])
            assert filled == [], (city, filled[:5])

    def test_apply_never_touches_a_row_that_has_a_colour(self, frames, learned):
        df = frames["pune"]
        before = df["item_color"].tolist()
        apply(df, learned["by_name"], learned["tokens"],
              learned["attrs"], learned["flags"])
        assert df["item_color"].tolist() == before


class TestTheClientReport:
    def test_the_grouping_is_deterministic(self):
        """`_question_tokens` returns a set, and set iteration is hash-salted per
        process — an unsorted greedy scan broke ties differently on every run and
        the committed report changed by a group or two each time."""
        rows = [("bangalore", "palak_paneer", "veg_gravy", "", "why"),
                ("bangalore", "palak_dal", "dal", "", "why"),
                ("ncr", "paneer_tikka", "veg_gravy", "", "why")]
        first = group_questions(rows)[0]
        for _ in range(4):
            assert group_questions(rows)[0] == first

    def test_it_asks_far_fewer_questions_than_there_are_dishes(self):
        rows = [("bangalore", f"chicken_dish_{i}", "nonveg_main", "", "w")
                for i in range(20)]
        rows += [("bangalore", f"paneer_thing_{i}", "veg_gravy", "", "w")
                 for i in range(15)]
        groups, items, leftovers = group_questions(rows)
        assert len(items) == 35
        assert len(groups) + len(leftovers) <= 4, groups
        assert groups[0][0] == ("chicken", "nonveg_main")

    def test_every_dish_is_covered_by_some_question(self):
        rows = [("b", "aloo_gobi", "veg_dry", "", "w"),
                ("b", "gobi_manchurian", "veg_dry", "", "w"),
                ("b", "xyz", "dal", "", "w")]
        groups, items, leftovers = group_questions(rows)
        covered = {i for _k, members in groups for i in members}
        assert len(covered) + len(leftovers) == len(items)

    def test_the_committed_report_matches_the_workbooks(self, frames, learned):
        """The report is what the client is asked to fill, so a stale one asks
        for dishes that have since been coloured."""
        import csv
        from scripts.fill_item_colours import REPORT
        listed = {(r["city"], r["item"])
                  for r in csv.DictReader(open(REPORT))}
        actual = {(city, str(r["item"]).strip().lower())
                  for city, df in frames.items()
                  for _i, r in df[df["item_color"].isna()].iterrows()}
        assert listed == actual, {
            "in the report but now coloured": sorted(listed - actual)[:5],
            "blank but missing from the report": sorted(actual - listed)[:5],
        }
