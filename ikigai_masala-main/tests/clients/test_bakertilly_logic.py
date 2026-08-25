"""Bakertilly: two non-veg on the biryani day and ONE on the rest, and a veg
gravy from the client's named families every day.

Two statements, one correction each.

**"Non veg 2 will come only on biryani day, and 1."** The earlier reading was
that the whole station stood down Mon/Tue/Thu/Fri, which dropped the base slot
and left those four days with no non-veg at all. The client means the SECOND
dish is the biryani-day one; the first runs daily. `slot_indices` is what
expresses that — it stands down one expansion instead of the family.

**"Need a veg gravy (paneer, baby corn, gobi, mushroom, rajma, chole, channa)
all day, first priority."** A one-slot component with `count: 1` IS "this slot
must be a matching dish" (note 20), and a composition component relaxes rather
than failing when a day cannot supply one — which is what makes it a first
priority rather than an ultimatum.

The selector deliberately reads `primary_protein` and the dish NAME for paneer
and never `key_ingredient`: that column is the de-facto default for a Chinese
dish in this ontology, which is why a Thai green curry used to count as a paneer
gravy (`scripts/definitional_flags.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.ontology.paths import city_excel_path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "data" / "configs" / "clients" / "bakertilly.json"

NONVEG_RULE = "bakertilly_second_nonveg_on_the_biryani_day_only"
GRAVY_RULE = "bakertilly_veg_gravy_from_the_named_families_daily"


@pytest.fixture(scope="module")
def block():
    return json.loads(CONFIG.read_text(encoding="utf-8"))["Bakertilly"]


@pytest.fixture(scope="module")
def by_name(block):
    return {r["name"]: r for r in block["rules"]}


@pytest.fixture(scope="module")
def gravies():
    df = pd.read_excel(city_excel_path("bangalore"))
    df.columns = [c.strip() for c in df.columns]
    return df[df["course_type"].astype(str).str.strip().str.lower() == "veg_gravy"]


class TestTheSecondNonVegIsTheBiryaniDayOne:
    def test_it_stands_down_only_the_second_expansion(self, by_name):
        rule = by_name[NONVEG_RULE]
        assert rule["base_slot"] == "nonveg_main"
        assert rule["slot_indices"] == [2], (
            "without slot_indices this drops the whole family and the other four "
            "days lose their non-veg entirely — the bug this replaced")
        assert rule["allowed_weekdays"] == ["wed"]

    def test_the_old_whole_slot_rule_is_gone(self, by_name):
        assert "bakertilly_nonveg_biryani_day_only" not in by_name

    def test_wednesday_is_the_biryani_day(self):
        """The rule names a weekday, so it is only right while that weekday is
        the biryani day. If the theme map moves, this fails rather than quietly
        putting the second dish on an ordinary day."""
        from tests.client_fixtures import CLIENTS
        row = next(r for r in CLIENTS if r["name"] == "Bakertilly")
        assert row["counters"][0]["theme_map"]["wednesday"] == "biryani"

    def test_the_counter_still_has_two_nonveg_slots(self):
        """`slot_indices: [2]` addresses an expansion that has to exist."""
        from tests.client_fixtures import CLIENTS
        row = next(r for r in CLIENTS if r["name"] == "Bakertilly")
        assert row["counters"][0]["slot_counts"]["nonveg_main"] == 2

    def test_the_two_wednesday_dishes_are_still_both_dry(self, by_name):
        """The client's other statement about the biryani day, unchanged."""
        comp = by_name["bakertilly_two_chicken_dry_on_the_biryani_day"]
        biryani = comp["components_by_theme"]["biryani"]
        assert biryani[0]["count"] == 2


class TestTheDailyVegGravyFamily:
    def test_it_is_a_one_slot_daily_component(self, by_name):
        rule = by_name[GRAVY_RULE]
        assert rule["base_slot"] == "veg_gravy"
        assert rule["min_slot_count"] == 1 and rule["max_slot_count"] == 1
        assert len(rule["components"]) == 1
        assert rule["components"][0]["count"] == 1

    def test_every_family_the_client_named_is_selectable(self, by_name, gravies):
        """Each of the seven has to match something, or that word in the client's
        sentence is silently doing nothing."""
        names = gravies["item"].astype(str).str.strip().str.lower()
        ki = gravies["key_ingredient"].astype(str).str.strip().str.lower()
        pp = gravies["primary_protein"].astype(str).str.strip().str.lower()
        for label, mask in (
            ("paneer", pp.eq("paneer") | names.str.contains("paneer|cottage_cheese")),
            ("baby corn", names.str.contains("baby_corn|babycorn")),
            ("gobi", ki.isin(["cauliflower", "gobi"]) | names.str.contains("gobi|cauliflower")),
            ("mushroom", ki.eq("mushroom") | names.str.contains("mushroom")),
            ("rajma", ki.eq("rajma") | names.str.contains("rajma")),
            ("chole", names.str.contains("chole")),
            ("channa", names.str.contains("chana|channa")),
        ):
            assert int(mask.sum()) > 0, label

    def test_paneer_is_not_selected_on_key_ingredient(self, by_name):
        """`key_ingredient == paneer` is the de-facto default for a Chinese dish
        here — selecting on it would count a Thai green curry as a paneer gravy."""
        sel = by_name[GRAVY_RULE]["components"][0]["selector"]
        parts = sel["any_of"]
        assert {"key_ingredient": "paneer"} not in parts
        assert {"primary_protein": "paneer"} in parts

    def test_the_family_is_deep_enough_for_a_daily_slot(self, gravies):
        """A count-1 slot under the 20-day cooldown needs roughly one distinct
        dish per working day in the window plus the week being planned."""
        names = gravies["item"].astype(str).str.strip().str.lower()
        ki = gravies["key_ingredient"].astype(str).str.strip().str.lower()
        pp = gravies["primary_protein"].astype(str).str.strip().str.lower()
        fam = (pp.eq("paneer") | names.str.contains("paneer|cottage_cheese")
               | ki.eq("mushroom") | names.str.contains("mushroom")
               | names.str.contains("baby_corn|babycorn")
               | ki.isin(["cauliflower", "gobi"]) | names.str.contains("gobi|cauliflower")
               | ki.eq("rajma") | names.str.contains("rajma")
               | ki.isin(["chickpea", "chole", "kabuli_chana"])
               | names.str.contains("chole|chana|channa"))
        assert int(fam.sum()) >= 25

    def test_it_does_not_fight_the_city_premium_cap(self, gravies):
        """Bangalore allows a premium veg gravy on exactly ONE day. Paneer, baby
        corn and mushroom are premium, so a daily family gravy would contradict
        that if the family were premium-only. It is not: the non-premium members
        cover the other four days."""
        names = gravies["item"].astype(str).str.strip().str.lower()
        ki = gravies["key_ingredient"].astype(str).str.strip().str.lower()
        pp = gravies["primary_protein"].astype(str).str.strip().str.lower()
        fam = (pp.eq("paneer") | names.str.contains("paneer|cottage_cheese")
               | ki.eq("mushroom") | names.str.contains("mushroom")
               | names.str.contains("baby_corn|babycorn")
               | ki.isin(["cauliflower", "gobi"]) | names.str.contains("gobi|cauliflower")
               | ki.eq("rajma") | names.str.contains("rajma")
               | ki.isin(["chickpea", "chole", "kabuli_chana"])
               | names.str.contains("chole|chana|channa"))
        premium = pd.to_numeric(
            gravies["is_premium_gravy"], errors="coerce").fillna(0).eq(1)
        assert int((fam & ~premium).sum()) >= 20

    def test_the_paneer_weekly_cap_is_still_declared(self, block):
        """`bakertilly_paneer_1x` caps paneer's share of the daily gravy at one
        day. Both can hold — the family has six other members."""
        refs = [u.get("as") for u in (block.get("use") or [])]
        assert "bakertilly_paneer_1x" in refs


class TestTheRulesLoad:
    def test_every_bakertilly_rule_validates(self):
        rules = MenuRuleLoader().load_for_client(
            "Bakertilly", MenuRuleLoader().load_for_city("bangalore"), "Counter 1")
        for want in (NONVEG_RULE, GRAVY_RULE):
            rule = next((r for r in rules if r.name == want), None)
            assert rule is not None, f"{want} did not load"
            assert rule.validate_config(), want
