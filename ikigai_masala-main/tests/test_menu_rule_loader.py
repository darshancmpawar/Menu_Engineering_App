"""Tests for MenuRuleLoader and BaseMenuRule."""

import pytest
from src.menu_rules import MenuRuleLoader
from src.menu_rules.base_menu_rule import BaseMenuRule, MenuRuleType


# Number of rules in the reference (bangalore) ruleset. Asserted rather than
# hard-coded per test so adding a city rule is a one-line update here.
_CITY_RULE_COUNT = 57


class TestMenuRuleLoader:
    def test_load_from_json_file(self):
        loader = MenuRuleLoader('data/configs/city_rules/bangalore.json')
        rules = loader.load_from_file()
        assert len(rules) == _CITY_RULE_COUNT

    def test_all_rules_are_base_menu_rule(self):
        loader = MenuRuleLoader('data/configs/city_rules/bangalore.json')
        rules = loader.load_from_file()
        for rule in rules:
            assert isinstance(rule, BaseMenuRule)

    def test_all_rules_have_rule_type(self):
        loader = MenuRuleLoader('data/configs/city_rules/bangalore.json')
        rules = loader.load_from_file()
        for rule in rules:
            assert rule.rule_type is not None
            assert isinstance(rule.rule_type, MenuRuleType)

    def test_all_rules_validate(self):
        loader = MenuRuleLoader('data/configs/city_rules/bangalore.json')
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
        loader = MenuRuleLoader('data/configs/city_rules/bangalore.json')
        loader.load_from_file()
        # The broad `premium` rule (per-day + weekly cap) was retired per the
        # Bangalore rulebook (§5, rules 45-46) in favour of two slot-specific
        # exactly-one selector_frequency rules.
        assert len(loader.get_rules_by_type('premium')) == 0
        premium_exact = [r for r in loader.get_rules_by_type('selector_frequency')
                         if r.name in ('premium_veg_gravy_exactly_one',
                                       'premium_veg_dry_exactly_one')]
        assert len(premium_exact) == 2
        assert all(r.exact == 1 for r in premium_exact)

    def test_get_enabled_rules_returns_all(self):
        loader = MenuRuleLoader('data/configs/city_rules/bangalore.json')
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


class TestLoadForClient:
    """Tests for MenuRuleLoader.load_for_client()."""

    def test_missing_file_returns_generic(self, monkeypatch):
        monkeypatch.setattr(
            'src.menu_rules.menu_rule_loader.CLIENT_RULES_CONFIG_PATH',
            '/nonexistent/nope.json')
        loader = MenuRuleLoader()
        generic = [object()]  # dummy rule
        result = loader.load_for_client('Tekion', generic)
        assert result == generic

    def test_unknown_client_returns_generic(self):
        loader = MenuRuleLoader()
        generic = [object()]
        result = loader.load_for_client('UnknownClientXYZ', generic)
        assert result == generic

    def test_tekion_seed_loads_its_configured_rules(self):
        """Asserts the rule *types* present, not a count.

        A count assertion breaks every time a client gains a requirement, which
        says nothing about whether the loader works. Tekion's block grew from 3
        rules to 8 when its sheet-embedded requirements were configured.
        """
        from src.menu_rules.ingredient_ban_rule import IngredientBanRule
        from src.menu_rules.item_frequency_rule import ItemFrequencyRule
        from src.menu_rules.slot_day_restriction_rule import SlotDayRestrictionRule
        from src.menu_rules.slot_composition_rule import SlotCompositionRule
        loader = MenuRuleLoader()
        result = loader.load_for_client('Tekion', [])
        assert result, 'Tekion has a client_rules block; it must load'
        kinds = {type(r) for r in result}
        for expected in (IngredientBanRule, ItemFrequencyRule,
                         SlotDayRestrictionRule, SlotCompositionRule):
            assert expected in kinds, (expected.__name__, sorted(
                k.__name__ for k in kinds))
        assert all(r.validate_config() for r in result), [
            (r.name, r.validation_errors()) for r in result
            if not r.validate_config()]

    def test_invalid_rule_is_skipped(self, tmp_path):
        import json
        bad_file = tmp_path / 'client_rules.json'
        bad_file.write_text(json.dumps({
            "TestClient": [
                {"name": "bad", "type": "nonexistent_type"},
                {"name": "good", "type": "ingredient_ban", "ingredients": ["egg"]},
            ]
        }))
        from unittest.mock import patch
        with patch('src.menu_rules.menu_rule_loader.CLIENT_RULES_CONFIG_PATH', str(bad_file)):
            loader = MenuRuleLoader()
            result = loader.load_for_client('TestClient', [])
        assert len(result) == 1
        assert result[0].name == 'good'

    def test_object_form_disable_and_override(self, tmp_path):
        import json
        from src.menu_rules.welcome_drink_buttermilk_rule import WelcomeDrinkButtermilkRule
        from src.menu_rules.ingredient_ban_rule import IngredientBanRule
        city = MenuRuleLoader().load_from_dict({'rules': [
            {'name': 'buttermilk_twice_weekly', 'type': 'welcome_drink_buttermilk',
             'count': 2, 'non_consecutive': True},
            {'name': 'keep_me', 'type': 'unique_items'},
            {'name': 'drop_me', 'type': 'unique_items'},
        ]})
        cfg = tmp_path / 'client_rules.json'
        cfg.write_text(json.dumps({
            "Acme": {
                "disable": ["drop_me"],
                "rules": [
                    {"name": "buttermilk_twice_weekly", "type": "welcome_drink_buttermilk",
                     "count": 1, "non_consecutive": False},
                    {"name": "acme_ban", "type": "ingredient_ban", "ingredients": ["egg"]},
                ],
                "constant_items": {"salad": "green salad"},
            }
        }))
        from unittest.mock import patch
        with patch('src.menu_rules.menu_rule_loader.CLIENT_RULES_CONFIG_PATH', str(cfg)):
            loader = MenuRuleLoader()
            result = loader.load_for_client('Acme', city)
            consts = loader.get_client_constant_items('Acme')
        names = [r.name for r in result]
        assert names == ['buttermilk_twice_weekly', 'keep_me', 'acme_ban']
        assert isinstance(result[0], WelcomeDrinkButtermilkRule)
        assert result[0].count == 1
        assert isinstance(result[2], IngredientBanRule)
        assert consts == {"salad": "green salad"}

    def test_legacy_list_form_still_appends(self, tmp_path):
        import json
        city = MenuRuleLoader().load_from_dict({'rules': [
            {'name': 'city_rule', 'type': 'unique_items'},
        ]})
        cfg = tmp_path / 'client_rules.json'
        cfg.write_text(json.dumps({
            "Legacy": [
                {"name": "extra", "type": "ingredient_ban", "ingredients": ["egg"]},
            ]
        }))
        from unittest.mock import patch
        with patch('src.menu_rules.menu_rule_loader.CLIENT_RULES_CONFIG_PATH', str(cfg)):
            result = MenuRuleLoader().load_for_client('Legacy', city)
        assert [r.name for r in result] == ['city_rule', 'extra']

    def test_quince_disables_curd_raita_and_has_constants(self):
        city = MenuRuleLoader().load_for_city('bangalore')
        loader = MenuRuleLoader()
        rules = loader.load_for_client('Quince', city)
        names = [r.name for r in rules]
        assert 'curd_raita_logic' not in names
        assert len(names) == len(set(names))  # no duplicate names after merge
        consts = loader.get_client_constant_items('Quince')
        assert consts['curd_side']['friday'] == 'raita'


class TestInvalidConfigLogging:
    """The loader should log *why* a rule was dropped so admins can fix it."""

    def test_min_gt_max_item_frequency_logs_reason(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        config = {
            "rules": [{
                "name": "bad_freq", "type": "item_frequency",
                "selector": {"flag": "is_liquid_rice"},
                "min_per_week": 3, "max_per_week": 1,
            }]
        }
        loader = MenuRuleLoader()
        rules = loader.load_from_dict(config)
        assert rules == []
        joined = "\n".join(rec.message for rec in caplog.records)
        assert "bad_freq" in joined
        assert "min_per_week" in joined and "<=" in joined

    def test_invalid_premium_rule_logs_reason(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        config = {
            "rules": [{
                "name": "bad_premium", "type": "premium",
                "min_per_horizon": 5, "max_per_horizon": 1,
            }]
        }
        loader = MenuRuleLoader()
        rules = loader.load_from_dict(config)
        assert rules == []
        joined = "\n".join(rec.message for rec in caplog.records)
        assert "bad_premium" in joined
        assert "min_per_horizon" in joined


class TestCityRules:
    """Per-city rule files: resolution, extends/override/disable, fallback."""

    def test_bangalore_loads_full_ruleset(self):
        rules = MenuRuleLoader().load_for_city('Bangalore')
        assert len(rules) == _CITY_RULE_COUNT
        assert all(r.validate_config() for r in rules)

    def test_city_name_is_case_insensitive(self):
        assert len(MenuRuleLoader().load_for_city('bangalore')) == _CITY_RULE_COUNT

    # Chennai left this list once it became standalone; hyderabad.json and
    # ncr.json are still extends-bangalore stubs.
    @pytest.mark.parametrize('city', ['Hyderabad', 'NCR'])
    def test_city_without_its_own_rules_inherits_bangalore(self, city):
        # These files extend bangalore with no overrides yet → same ruleset.
        assert len(MenuRuleLoader().load_for_city(city)) == _CITY_RULE_COUNT

    @pytest.mark.parametrize('city', ['Pune', 'Chennai'])
    def test_cities_with_their_own_ruleset_are_standalone(self, city):
        """Both have their own list and must not be Bangalore's. Chennai's is
        standalone for a different reason than Pune's: not a rival rulebook but
        an item list that leaves a third of Bangalore's selectors matching
        nothing — every welcome-drink rule among them."""
        import json
        raw = json.load(open(f'data/configs/city_rules/{city.lower()}.json'))
        assert 'extends' not in raw
        rules = MenuRuleLoader().load_for_city(city)
        assert 0 < len(rules) < _CITY_RULE_COUNT
        assert all(r.validate_config() for r in rules), [
            r.name for r in rules if not r.validate_config()]

    def test_pune_is_standalone_not_a_bangalore_extension(self):
        """Pune has its own rulebook, so its ruleset must NOT be Bangalore's.

        Pinned because pune.json used to be an extends-bangalore stub, and the
        two rulebooks genuinely disagree — Bangalore mandates exactly one
        premium gravy a week, Pune caps it at one.
        """
        rules = MenuRuleLoader().load_for_city('Pune')
        assert 0 < len(rules) < _CITY_RULE_COUNT
        assert all(r.validate_config() for r in rules), [
            r.name for r in rules if not r.validate_config()
        ]
        names = {r.name for r in rules}
        # Bangalore-only rules that must not leak in.
        assert 'nonveg_biryani_once_per_week' not in names
        assert 'premium_veg_gravy_exactly_one' not in names
        # Pune-specific rules that must be there.
        assert 'colour_three_distinct_max_two_alike' in names
        assert 'plain_chapati_may_repeat' in names

    def test_unknown_or_blank_city_falls_back_to_default(self):
        assert len(MenuRuleLoader().load_for_city('Atlantis')) == _CITY_RULE_COUNT
        assert len(MenuRuleLoader().load_for_city(None)) == _CITY_RULE_COUNT

    def test_extends_override_and_disable(self, tmp_path):
        import json
        (tmp_path / 'bangalore.json').write_text(json.dumps({'rules': [
            {'name': 'a', 'type': 'coupling'},
            {'name': 'b', 'type': 'unique_items'},
        ]}))
        (tmp_path / 'pune.json').write_text(json.dumps({
            'extends': 'bangalore', 'disable': ['b'],
            'rules': [{'name': 'c', 'type': 'curd_side'}],
        }))
        rules = MenuRuleLoader().load_for_city('pune', cities_dir=str(tmp_path))
        names = [r.name for r in rules]
        assert names == ['a', 'c']  # b disabled, c appended, bangalore order kept

    def test_child_overrides_parent_by_name(self, tmp_path):
        import json
        (tmp_path / 'bangalore.json').write_text(json.dumps({'rules': [
            {'name': 'cap', 'type': 'selector_frequency',
             'selector': {'flag': 'is_pulao'}, 'max': 1},
        ]}))
        (tmp_path / 'pune.json').write_text(json.dumps({
            'extends': 'bangalore',
            'rules': [{'name': 'cap', 'type': 'selector_frequency',
                       'selector': {'flag': 'is_pulao'}, 'max': 3}],
        }))
        rules = MenuRuleLoader().load_for_city('pune', cities_dir=str(tmp_path))
        assert len(rules) == 1 and rules[0].max == 3  # child's max wins

    def test_circular_extends_raises(self, tmp_path):
        import json
        import pytest as _pytest
        (tmp_path / 'a.json').write_text(json.dumps({'extends': 'b', 'rules': []}))
        (tmp_path / 'b.json').write_text(json.dumps({'extends': 'a', 'rules': []}))
        with _pytest.raises(ValueError, match='circular'):
            MenuRuleLoader().load_for_city('a', cities_dir=str(tmp_path))
