"""Tests for MenuRuleLoader and BaseMenuRule."""

import pytest
from src.menu_rules import MenuRuleLoader
from src.menu_rules.base_menu_rule import BaseMenuRule, MenuRuleType


class TestMenuRuleLoader:
    def test_load_from_json_file(self):
        loader = MenuRuleLoader('data/configs/indian_menu_rules.json')
        rules = loader.load_from_file()
        assert len(rules) == 14

    def test_all_rules_are_base_menu_rule(self):
        loader = MenuRuleLoader('data/configs/indian_menu_rules.json')
        rules = loader.load_from_file()
        for rule in rules:
            assert isinstance(rule, BaseMenuRule)

    def test_all_rules_have_rule_type(self):
        loader = MenuRuleLoader('data/configs/indian_menu_rules.json')
        rules = loader.load_from_file()
        for rule in rules:
            assert rule.rule_type is not None
            assert isinstance(rule.rule_type, MenuRuleType)

    def test_all_rules_validate(self):
        loader = MenuRuleLoader('data/configs/indian_menu_rules.json')
        rules = loader.load_from_file()
        for rule in rules:
            assert rule.validate_config() is True

    def test_load_from_dict(self):
        config = {
            "rules": [
                {"name": "test_premium", "type": "premium", "max_per_day": 1,
                 "min_per_horizon": 1, "max_per_horizon": 2}
            ]
        }
        loader = MenuRuleLoader()
        rules = loader.load_from_dict(config)
        assert len(rules) == 1
        assert rules[0].name == "test_premium"
        assert rules[0].rule_type == MenuRuleType.PREMIUM

    def test_unknown_rule_type_skipped(self):
        config = {"rules": [{"name": "bad", "type": "nonexistent"}]}
        loader = MenuRuleLoader()
        rules = loader.load_from_dict(config)
        assert len(rules) == 0

    def test_get_rules_by_type(self):
        loader = MenuRuleLoader('data/configs/indian_menu_rules.json')
        loader.load_from_file()
        premiums = loader.get_rules_by_type('premium')
        assert len(premiums) == 1

    def test_get_enabled_rules_returns_all(self):
        loader = MenuRuleLoader('data/configs/indian_menu_rules.json')
        rules = loader.load_from_file()
        enabled = loader.get_enabled_rules()
        assert len(enabled) == len(rules)

    def test_missing_file_raises(self):
        loader = MenuRuleLoader('/nonexistent/file.json')
        with pytest.raises(FileNotFoundError):
            loader.load_from_file()

    def test_get_description(self):
        config = {"rules": [{"name": "test_coupling", "type": "coupling"}]}
        loader = MenuRuleLoader()
        rules = loader.load_from_dict(config)
        desc = rules[0].get_description()
        assert 'coupling' in desc
        assert 'test_coupling' in desc

    def test_rule_repr(self):
        config = {"rules": [{"name": "test_repr", "type": "premium",
                              "max_per_day": 1, "min_per_horizon": 1, "max_per_horizon": 2}]}
        loader = MenuRuleLoader()
        rules = loader.load_from_dict(config)
        r = repr(rules[0])
        assert 'PremiumMenuRule' in r
        assert 'test_repr' in r
