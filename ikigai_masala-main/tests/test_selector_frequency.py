"""Fast tests for the generic SelectorFrequencyRule (Phase 1 rule framework).

End-to-end CP-SAT behavior (exact-2 non-consecutive, max caps) is asserted on
real data in the slow integration suite.
"""

import pandas as pd
import pytest

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


class TestRowMatches:
    def test_flag_and_text(self):
        rf = SelectorFrequencyRule({'name': 'x', 'selector': {'flag': 'is_pulao'}, 'max': 1})
        assert rf._row_matches(pd.Series({'is_pulao': 1}))
        assert not rf._row_matches(pd.Series({'is_pulao': 0}))
        rt = SelectorFrequencyRule({'name': 'x', 'selector': {'course_type': 'dessert'}, 'max': 1})
        assert rt._row_matches(pd.Series({'course_type': 'Dessert'}))
        assert not rt._row_matches(pd.Series({'course_type': 'rice'}))
