"""Fast tests for the welcome-drink buttermilk rule (F3): config parsing,
loader registration, and is_buttermilk flag normalization. The end-to-end
"exactly 2, non-consecutive" behavior is asserted in the slow integration
suite (test_integration_slow.py)."""

import pandas as pd

from src.menu_rules import MenuRuleLoader
from src.menu_rules.welcome_drink_buttermilk_rule import WelcomeDrinkButtermilkRule
from src.preprocessor.column_mapper import ColumnMapper


class TestButtermilkRuleConfig:
    def test_loader_registers_type(self):
        loader = MenuRuleLoader()
        rule = loader._create_rule(
            {'type': 'welcome_drink_buttermilk', 'name': 'b', 'count': 2}
        )
        assert isinstance(rule, WelcomeDrinkButtermilkRule)
        assert rule.count == 2
        assert rule.non_consecutive is True

    def test_defaults(self):
        r = WelcomeDrinkButtermilkRule({'name': 'b'})
        assert r.count == 2
        assert r.flag == 'is_buttermilk'
        assert r.base_slot == 'welcome_drink'

    def test_non_consecutive_override(self):
        r = WelcomeDrinkButtermilkRule(
            {'name': 'b', 'count': 3, 'non_consecutive': False}
        )
        assert r.count == 3
        assert r.non_consecutive is False

    def test_validate_config(self):
        assert WelcomeDrinkButtermilkRule({'name': 'b', 'count': 2}).validate_config()
        assert not WelcomeDrinkButtermilkRule({'name': 'b', 'count': -1}).validate_config()


class TestButtermilkFlagNormalization:
    def test_is_buttermilk_normalized_to_01(self):
        df = pd.DataFrame({
            'item': ['spiced_buttermilk', 'lime_juice', 'jeera_buttermilk'],
            'course_type': ['welcome_drink'] * 3,
            'is_buttermilk': [1, 0, 'yes'],
        })
        mapper = ColumnMapper().detect(df)
        out = mapper.apply(df)
        assert out['is_buttermilk'].tolist() == [1, 0, 1]

    def test_is_buttermilk_defaults_zero_when_absent(self):
        df = pd.DataFrame({
            'item': ['lime_juice'],
            'course_type': ['welcome_drink'],
        })
        out = ColumnMapper().detect(df).apply(df)
        assert out['is_buttermilk'].tolist() == [0]
