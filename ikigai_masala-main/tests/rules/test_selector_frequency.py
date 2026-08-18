"""Fast tests for the generic SelectorFrequencyRule (Phase 1 rule framework).

End-to-end CP-SAT behavior (exact-2 non-consecutive, max caps) is asserted on
real data in the slow integration suite.
"""

import pandas as pd

from src.menu_rules import MenuRuleLoader
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule


class TestConfig:
    def test_loader_registers_type(self):
        r = MenuRuleLoader()._create_rule({
            'type': 'selector_frequency', 'name': 'x',
            'selector': {'flag': 'is_mixedveg_gravy'}, 'max': 1,
        })
        assert isinstance(r, SelectorFrequencyRule)
        assert r.sel_kind == 'flag' and r.sel_value == 'is_mixedveg_gravy' and r.max == 1

    def test_all_selector_kinds(self):
        for kind, raw, norm in [
            ('sub_category', 'South Curd Rice', 'south curd rice'),
            ('primary_protein', 'Paneer', 'paneer'),
            ('course_type', 'Veg_Gravy', 'veg_gravy'),
            ('cuisine_family', 'Continental', 'continental'),
            ('key_ingredient', 'Mushroom', 'mushroom'),
        ]:
            r = SelectorFrequencyRule({'name': 'x', 'selector': {kind: raw}, 'max': 1})
            assert r.sel_kind == kind and r.sel_value == norm

    def test_requires_selector_and_a_count(self):
        assert not SelectorFrequencyRule({'name': 'x', 'max': 1}).validate_config()      # no selector
        assert not SelectorFrequencyRule({'name': 'x', 'selector': {'flag': 'f'}}).validate_config()  # no count

    def test_exact_excludes_max_min(self):
        r = SelectorFrequencyRule({'name': 'x', 'selector': {'flag': 'f'}, 'exact': 2, 'max': 3})
        assert not r.validate_config()
        assert 'exact cannot be combined' in ' '.join(r.validation_errors())

    def test_min_le_max(self):
        r = SelectorFrequencyRule({'name': 'x', 'selector': {'flag': 'f'}, 'min': 3, 'max': 1})
        assert not r.validate_config()

    def test_valid_configs(self):
        for cfg in [
            {'name': 'x', 'selector': {'flag': 'f'}, 'max': 1},
            {'name': 'x', 'selector': {'flag': 'f'}, 'exact': 2, 'non_consecutive': True},
            {'name': 'x', 'selector': {'flag': 'f'}, 'daily_max': 3},
        ]:
            assert SelectorFrequencyRule(cfg).validate_config()

    def test_non_consecutive_alone_is_valid(self):
        # A pure adjacency ban with no count (e.g. sugar-syrup sweets not on
        # consecutive days) is a complete rule on its own.
        r = SelectorFrequencyRule({
            'name': 'x', 'selector': {'flag': 'is_sugar_syrup_heavy_dessert'},
            'non_consecutive': True})
        assert r.validate_config()
        assert r.non_consecutive and r.max is None and r.min is None
        # ...but nothing at all (no count, no non_consecutive) is still invalid.
        assert not SelectorFrequencyRule({'name': 'x', 'selector': {'flag': 'f'}}).validate_config()


class TestRowMatches:
    def test_flag_and_text(self):
        rf = SelectorFrequencyRule({'name': 'x', 'selector': {'flag': 'is_pulao'}, 'max': 1})
        assert rf._row_matches(pd.Series({'is_pulao': 1}))
        assert not rf._row_matches(pd.Series({'is_pulao': 0}))
        rt = SelectorFrequencyRule({'name': 'x', 'selector': {'course_type': 'dessert'}, 'max': 1})
        assert rt._row_matches(pd.Series({'course_type': 'Dessert'}))
        assert not rt._row_matches(pd.Series({'course_type': 'rice'}))

    def test_any_flag_is_or(self):
        r = SelectorFrequencyRule({
            'name': 'x', 'selector': {'any_flag': ['is_a', 'is_b']}, 'max': 1})
        assert r.validate_config() and r.sel_kind == 'any_flag'
        assert r._row_matches(pd.Series({'is_a': 1, 'is_b': 0}))
        assert r._row_matches(pd.Series({'is_a': 0, 'is_b': 1}))
        assert not r._row_matches(pd.Series({'is_a': 0, 'is_b': 0}))

    def test_exclude_subtracts(self):
        r = SelectorFrequencyRule({
            'name': 'x', 'selector': {'flag': 'is_legume'},
            'exclude': {'flag': 'is_salad'}, 'daily_max': 1})
        assert r._row_matches(pd.Series({'is_legume': 1, 'is_salad': 0}))
        assert not r._row_matches(pd.Series({'is_legume': 1, 'is_salad': 1}))  # excluded
        assert not r._row_matches(pd.Series({'is_legume': 0, 'is_salad': 0}))
