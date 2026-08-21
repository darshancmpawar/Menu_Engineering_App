"""`docs/client_rules_index.md` is derived, so it must not go stale.

Same argument as `data/raw/city_items/pool_tokens.json`: a committed artefact
generated from the configs is fast to read and free to keep — right up to the
moment someone edits a client rule and not the doc, at which point it is a third
thing that can disagree with the configs. This recomputes it and fails on any
difference, so the doc is either current or the build is red.
"""

from __future__ import annotations

import pytest

from scripts.dump_client_rules_index import TARGET, render, summarise


def test_the_committed_index_matches_the_configs():
    assert TARGET.exists(), f"{TARGET} is missing — run the dump script"
    assert TARGET.read_text() == render(), (
        "docs/client_rules_index.md is stale — run "
        "`python scripts/dump_client_rules_index.py` and commit the diff"
    )


def test_every_configured_client_has_a_section():
    from src.menu_rules import MenuRuleLoader
    text = TARGET.read_text()
    for client in MenuRuleLoader()._read_client_blob():
        assert f"\n## {client}\n" in text, client


def test_the_client_count_in_the_header_is_current():
    from src.menu_rules import MenuRuleLoader
    n = len(MenuRuleLoader()._read_client_blob())
    assert f"**{n} clients have per-client rules.**" in TARGET.read_text()


class TestSummaries:
    """The summary line is the whole value of the doc, so the shapes that carry
    a client requirement must each render as something a person can read."""

    def test_a_day_count_says_days_not_dishes(self):
        out = summarise({'type': 'selector_frequency', 'max': 1,
                         'selector': {'flag': 'is_paneer_gravy'},
                         'base_slot': 'veg_gravy'})
        assert out == "is_paneer_gravy @ veg_gravy: ≤ 1 day(s)"

    def test_a_daily_cap_is_distinguished_from_a_horizon_cap(self):
        assert "per day" in summarise({'type': 'selector_frequency',
                                       'daily_max': 1,
                                       'selector': {'flag': 'f'}})

    def test_a_weekday_restriction_names_the_days(self):
        out = summarise({'type': 'slot_day_restriction', 'base_slot': 'soup',
                         'allowed_weekdays': ['tue', 'thu']})
        assert out == "soup runs only on tue, thu (blank otherwise)"

    def test_a_weekday_composition_lists_each_day(self):
        out = summarise({
            'type': 'slot_composition', 'base_slot': 'nonveg_main',
            'min_slot_count': 1,
            'components_by_weekday': {
                'tue': [{'selector': {'flag': 'is_egg_dish'}, 'count': 1}]}})
        assert 'on tue: is_egg_dish' in out

    def test_a_cooldown_scoped_staple_reads_differently_from_a_plain_one(self):
        base = {'type': 'repeatable_items', 'base_slot': 'welcome_drink',
                'selector': {'flag': 'is_buttermilk'}}
        assert 'any day' in summarise(base)
        assert 'distinct within one' in summarise({**base, 'scope': 'cooldown'})

    def test_the_new_soft_mode_names_both_slots_and_the_values(self):
        out = summarise({'type': 'soft_preference', 'mode': 'match_attribute',
                         'priority': 'medium', 'group_by': 'cuisine_family',
                         'values': ['north_indian', 'south_indian'],
                         'base_slot_a': 'rice', 'base_slot_b': 'veg_gravy'})
        assert 'rice' in out and 'veg_gravy' in out and 'north_indian' in out

    def test_an_any_of_selector_is_readable(self):
        out = summarise({'type': 'selector_frequency', 'max': 1,
                         'selector': {'any_of': [{'key_ingredient': 'paneer'},
                                                 {'flag': 'is_veg_kofta_gravy'}]}})
        assert 'key_ingredient paneer or is_veg_kofta_gravy' in out

    def test_a_history_window_says_how_long(self):
        out = summarise({'type': 'selector_history_window', 'window_days': 15,
                         'selector': {'flag': 'is_kadhi_dal'},
                         'base_slot': 'veg_gravy'})
        assert 'once per 15 days' in out

    @pytest.mark.parametrize("kind", [
        'selector_frequency', 'selector_history_window', 'item_frequency',
        'slot_day_restriction', 'slot_composition', 'repeatable_items',
        'fixed_daily_item', 'ingredient_ban', 'same_day_exclusion',
        'attribute_grouping', 'soft_preference', 'theme_slot_filter',
        'unique_items',
    ])
    def test_no_rule_type_falls_through_to_a_bare_type_name(self, kind):
        """A type this renderer does not know prints its own name and tells the
        reader nothing. Every type a client file uses must be handled."""
        from src.menu_rules import MenuRuleLoader
        used = {
            r.get('type')
            for entry in MenuRuleLoader()._read_client_blob().values()
            if isinstance(entry, dict)
            for r in (entry.get('rules') or [])
            if isinstance(r, dict)
        }
        if kind not in used:
            pytest.skip(f"no client uses {kind}")
        for entry in MenuRuleLoader()._read_client_blob().values():
            if not isinstance(entry, dict):
                continue
            for rule in entry.get('rules') or []:
                if isinstance(rule, dict) and rule.get('type') == kind:
                    assert summarise(rule) != kind, rule.get('name')
