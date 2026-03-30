"""
Unit tests for individual menu rule implementations.

Tests validate_config, rule_type, config parsing, and basic properties.
CP-SAT constraint logic is tested indirectly via the integration test.
"""

import datetime as dt

import pandas as pd
import pytest
from src.menu_rules.coupling_menu_rule import CouplingMenuRule
from src.menu_rules.curd_side_menu_rule import CurdSideMenuRule
from src.menu_rules.premium_menu_rule import PremiumMenuRule
from src.menu_rules.theme_day_menu_rule import ThemeDayMenuRule
from src.menu_rules.welcome_drink_color_menu_rule import WelcomeDrinkColorMenuRule
from src.menu_rules.week_signature_cooldown_menu_rule import WeekSignatureCooldownMenuRule
from src.menu_rules.theme_starter_preference_rule import ThemeStarterPreferenceRule
from src.menu_rules.theme_fallback_penalty_rule import ThemeFallbackPenaltyRule
from src.menu_rules.unique_items_menu_rule import UniqueItemsMenuRule
from src.menu_rules.color_pairing_menu_rule import ColorPairingMenuRule
from src.menu_rules.color_variety_menu_rule import ColorVarietyMenuRule
from src.menu_rules.cuisine_menu_rule import CuisineMenuRule
from src.menu_rules.item_cooldown_menu_rule import ItemCooldownMenuRule
from src.menu_rules.ricebread_gap_menu_rule import RiceBreadGapMenuRule
from src.menu_rules.theme_slot_filter_rule import ThemeSlotFilterRule
from src.menu_rules.nonveg_dry_preference_rule import NonvegDryPreferenceRule
from src.menu_rules.base_menu_rule import MenuRuleType


# --- CouplingMenuRule ---

class TestCouplingMenuRule:
    def test_validate(self):
        rule = CouplingMenuRule({"name": "coupling", "type": "coupling"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = CouplingMenuRule({"name": "coupling", "type": "coupling"})
        assert rule.rule_type == MenuRuleType.COUPLING

    def test_apply_no_context_is_safe(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = CouplingMenuRule({"name": "coupling", "type": "coupling"})
        # apply with empty context should not crash
        rule.apply(model, {}, None, {})


# --- CurdSideMenuRule ---

class TestCurdSideMenuRule:
    def test_validate(self):
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side",
                                  "pulao_subcats": ["south_veg_pulao"]})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side"})
        assert rule.rule_type == MenuRuleType.CURD_SIDE

    def test_pulao_subcats_default(self):
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side"})
        assert isinstance(rule.pulao_subcats, (list, set))

    def test_apply_no_context_is_safe(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side"})
        rule.apply(model, {}, None, {})


# --- PremiumMenuRule ---

class TestPremiumMenuRule:
    def test_validate(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium",
                                "max_per_day": 1, "min_per_horizon": 1, "max_per_horizon": 2})
        assert rule.validate_config()

    def test_config_defaults(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium"})
        assert rule.max_per_day == 1
        assert rule.min_per_horizon == 1
        assert rule.max_per_horizon == 2

    def test_config_override(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium",
                                "max_per_day": 2, "max_per_horizon": 5})
        assert rule.max_per_day == 2
        assert rule.max_per_horizon == 5

    def test_rule_type(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium"})
        assert rule.rule_type == MenuRuleType.PREMIUM

    def test_apply_no_cfg_is_safe(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = PremiumMenuRule({"name": "prem", "type": "premium"})
        rule.apply(model, {}, None, {})


# --- ThemeDayMenuRule ---

class TestThemeDayMenuRule:
    def test_validate(self):
        rule = ThemeDayMenuRule({"name": "theme", "type": "theme_day"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = ThemeDayMenuRule({"name": "theme", "type": "theme_day"})
        assert rule.rule_type == MenuRuleType.THEME_DAY


# --- WelcomeDrinkColorMenuRule ---

class TestWelcomeDrinkColorMenuRule:
    def test_validate(self):
        rule = WelcomeDrinkColorMenuRule({"name": "wd_color", "type": "welcome_drink_color"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = WelcomeDrinkColorMenuRule({"name": "wd_color", "type": "welcome_drink_color"})
        assert rule.rule_type == MenuRuleType.WELCOME_DRINK_COLOR


# --- WeekSignatureCooldownMenuRule ---

class TestWeekSignatureCooldownMenuRule:
    def test_validate(self):
        rule = WeekSignatureCooldownMenuRule({"name": "sig", "type": "week_signature_cooldown",
                                               "cooldown_days": 30})
        assert rule.validate_config()

    def test_cooldown_default(self):
        rule = WeekSignatureCooldownMenuRule({"name": "sig", "type": "week_signature_cooldown"})
        assert rule.cooldown_days == 30

    def test_rule_type(self):
        rule = WeekSignatureCooldownMenuRule({"name": "sig", "type": "week_signature_cooldown"})
        assert rule.rule_type == MenuRuleType.WEEK_SIGNATURE_COOLDOWN


# --- ThemeStarterPreferenceRule ---

class TestThemeStarterPreferenceRule:
    def test_validate(self):
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference",
                                            "bonus_weight": 1000000})
        assert rule.validate_config()

    def test_bonus_default(self):
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        assert rule.bonus_weight == 1000000

    def test_rule_type(self):
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        assert rule.rule_type == MenuRuleType.THEME_STARTER_PREFERENCE

    def test_apply_is_noop(self):
        """apply() should be a no-op since this rule only contributes to objective."""
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        rule.apply(model, {}, None, {})

    def test_get_objective_terms_empty_context(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        terms = rule.get_objective_terms(model, {})
        assert terms == []


# --- ThemeFallbackPenaltyRule ---

class TestThemeFallbackPenaltyRule:
    def test_validate(self):
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty",
                                          "penalty": 2000000})
        assert rule.validate_config()

    def test_penalty_default(self):
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty"})
        assert rule.penalty == 2000000

    def test_rule_type(self):
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty"})
        assert rule.rule_type == MenuRuleType.THEME_FALLBACK_PENALTY

    def test_get_objective_terms_empty_context(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty"})
        terms = rule.get_objective_terms(model, {})
        assert terms == []


# --- UniqueItemsMenuRule ---

class TestUniqueItemsMenuRule:
    def test_validate(self):
        rule = UniqueItemsMenuRule({"name": "unique", "type": "unique_items", "scope": "session"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = UniqueItemsMenuRule({"name": "unique", "type": "unique_items"})
        assert rule.rule_type == MenuRuleType.UNIQUE_ITEMS


# --- ColorPairingMenuRule ---

class TestColorPairingMenuRule:
    def test_validate(self):
        rule = ColorPairingMenuRule({"name": "color_pair", "type": "color_pairing",
                                      "course_type_a": "rice", "course_type_b": "veg_gravy"})
        assert rule.validate_config()

    def test_validate_fails_without_courses(self):
        rule = ColorPairingMenuRule({"name": "color_pair", "type": "color_pairing"})
        assert rule.validate_config() is False

    def test_rule_type(self):
        rule = ColorPairingMenuRule({"name": "color_pair", "type": "color_pairing",
                                      "course_type_a": "rice", "course_type_b": "veg_gravy"})
        assert rule.rule_type == MenuRuleType.COLOR_PAIRING


# --- ColorVarietyMenuRule ---

class TestColorVarietyMenuRule:
    def test_validate(self):
        rule = ColorVarietyMenuRule({"name": "color_var", "type": "color_variety",
                                      "min_distinct_colors": {"lunch": 3}})
        assert rule.validate_config()

    def test_validate_fails_without_mapping(self):
        rule = ColorVarietyMenuRule({"name": "color_var", "type": "color_variety"})
        assert rule.validate_config() is False

    def test_rule_type(self):
        rule = ColorVarietyMenuRule({"name": "color_var", "type": "color_variety",
                                      "min_distinct_colors": {"lunch": 3}})
        assert rule.rule_type == MenuRuleType.COLOR_VARIETY


# --- CuisineMenuRule ---

class TestCuisineMenuRule:
    def test_validate(self):
        rule = CuisineMenuRule({"name": "cuisine", "type": "cuisine",
                                 "cuisine_family": "italian",
                                 "days_of_week": ["monday", "tuesday"]})
        assert rule.validate_config()

    def test_validate_fails_without_family(self):
        rule = CuisineMenuRule({"name": "cuisine", "type": "cuisine"})
        assert rule.validate_config() is False

    def test_rule_type(self):
        rule = CuisineMenuRule({"name": "cuisine", "type": "cuisine",
                                 "cuisine_family": "italian",
                                 "days_of_week": ["monday"]})
        assert rule.rule_type == MenuRuleType.CUISINE


# --- ItemCooldownMenuRule ---

class TestItemCooldownMenuRule:
    def test_validate(self):
        rule = ItemCooldownMenuRule({"name": "cd", "type": "item_cooldown", "cooldown_days": 20})
        assert rule.validate_config()

    def test_cooldown_default(self):
        rule = ItemCooldownMenuRule({"name": "cd", "type": "item_cooldown"})
        assert rule.cooldown_days == 20

    def test_rule_type(self):
        rule = ItemCooldownMenuRule({"name": "cd", "type": "item_cooldown"})
        assert rule.rule_type == MenuRuleType.ITEM_COOLDOWN

    def test_pre_filter_removes_banned(self):
        rule = ItemCooldownMenuRule({"name": "cd", "type": "item_cooldown"})
        pool = pd.DataFrame({'item': ['paneer_tikka', 'dal_makhani', 'chole']})
        d = dt.date(2026, 3, 24)
        ctx = {'banned_by_date': {d: {'paneer_tikka', 'chole'}}}
        filtered = rule.pre_filter_pool(pool, d, 'starter', 'south', ctx)
        assert list(filtered['item']) == ['dal_makhani']

    def test_pre_filter_no_bans_returns_all(self):
        rule = ItemCooldownMenuRule({"name": "cd", "type": "item_cooldown"})
        pool = pd.DataFrame({'item': ['paneer_tikka', 'dal_makhani']})
        d = dt.date(2026, 3, 24)
        filtered = rule.pre_filter_pool(pool, d, 'starter', 'south', {})
        assert len(filtered) == 2

    def test_apply_is_noop(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ItemCooldownMenuRule({"name": "cd", "type": "item_cooldown"})
        rule.apply(model, {}, None, {})


# --- RiceBreadGapMenuRule ---

class TestRiceBreadGapMenuRule:
    def test_validate(self):
        rule = RiceBreadGapMenuRule({"name": "rb", "type": "ricebread_gap", "gap_days": 10})
        assert rule.validate_config()

    def test_gap_default(self):
        rule = RiceBreadGapMenuRule({"name": "rb", "type": "ricebread_gap"})
        assert rule.gap_days == 10

    def test_rule_type(self):
        rule = RiceBreadGapMenuRule({"name": "rb", "type": "ricebread_gap"})
        assert rule.rule_type == MenuRuleType.RICEBREAD_GAP

    def test_pre_filter_removes_ricebread_when_banned(self):
        rule = RiceBreadGapMenuRule({"name": "rb", "type": "ricebread_gap"})
        pool = pd.DataFrame({
            'item': ['naan', 'rice_roti', 'chapati'],
            'is_rice_bread': [0, 1, 0],
        })
        d = dt.date(2026, 3, 24)
        ctx = {'ricebread_ban_day': {d: True}}
        filtered = rule.pre_filter_pool(pool, d, 'bread', 'south', ctx)
        assert list(filtered['item']) == ['naan', 'chapati']

    def test_pre_filter_ignores_non_bread(self):
        rule = RiceBreadGapMenuRule({"name": "rb", "type": "ricebread_gap"})
        pool = pd.DataFrame({'item': ['x'], 'is_rice_bread': [1]})
        d = dt.date(2026, 3, 24)
        ctx = {'ricebread_ban_day': {d: True}}
        filtered = rule.pre_filter_pool(pool, d, 'rice', 'south', ctx)
        assert len(filtered) == 1


# --- ThemeSlotFilterRule ---

class TestThemeSlotFilterRule:
    def test_validate(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        assert rule.rule_type == MenuRuleType.THEME_SLOT_FILTER

    def test_chinese_filters_rice(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['veg_fried_rice', 'jeera_rice', 'schezwan_rice'],
            'is_chinese_fried_rice': [1, 0, 1],
        })
        d = dt.date(2026, 3, 24)
        cfg = type('Cfg', (), {'cuisine_col': 'cuisine_family',
                                'cuisine_south_value': 'south_indian',
                                'cuisine_north_value': 'north_indian'})()
        filtered = rule.pre_filter_pool(pool, d, 'rice', 'chinese', {'cfg': cfg})
        assert set(filtered['item']) == {'veg_fried_rice', 'schezwan_rice'}

    def test_biryani_filters_rice(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['veg_biryani', 'jeera_rice'],
            'is_mixedveg_biryani': [1, 0],
        })
        d = dt.date(2026, 3, 24)
        filtered = rule.pre_filter_pool(pool, d, 'rice', 'biryani', {'cfg': None})
        assert list(filtered['item']) == ['veg_biryani']

    def test_chinese_does_not_force_starter_flag(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['paneer_tikka', 'schezwan_mushroom'],
            'is_chinese_starter': [0, 1],
        })
        d = dt.date(2026, 3, 24)
        filtered = rule.pre_filter_pool(pool, d, 'starter', 'chinese', {'cfg': None})
        assert set(filtered['item']) == {'paneer_tikka', 'schezwan_mushroom'}

    def test_south_filters_cuisine(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['sambar_rice', 'jeera_rice'],
            'cuisine_family': ['south_indian', 'north_indian'],
        })
        d = dt.date(2026, 3, 24)
        cfg = type('Cfg', (), {'cuisine_col': 'cuisine_family',
                                'cuisine_south_value': 'south_indian',
                                'cuisine_north_value': 'north_indian'})()
        filtered = rule.pre_filter_pool(pool, d, 'rice', 'south', {'cfg': cfg})
        assert list(filtered['item']) == ['sambar_rice']

    def test_exempt_slot_not_filtered(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['toor_dal', 'moong_dal'],
            'cuisine_family': ['south_indian', 'north_indian'],
        })
        d = dt.date(2026, 3, 24)
        cfg = type('Cfg', (), {'cuisine_col': 'cuisine_family',
                                'cuisine_south_value': 'south_indian',
                                'cuisine_north_value': 'north_indian'})()
        # 'dal' is exempt
        filtered = rule.pre_filter_pool(pool, d, 'dal', 'south', {'cfg': cfg})
        assert len(filtered) == 2

    def test_mix_day_no_filtering(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['a', 'b'],
            'cuisine_family': ['south_indian', 'north_indian'],
        })
        d = dt.date(2026, 3, 24)
        filtered = rule.pre_filter_pool(pool, d, 'rice', 'mix', {'cfg': None})
        assert len(filtered) == 2

    def test_bread_south_lock(self):
        rule = ThemeSlotFilterRule({"name": "tf", "type": "theme_slot_filter"})
        pool = pd.DataFrame({
            'item': ['dosa', 'naan', 'paratha'],
            'cuisine_family': ['south_indian', 'north_indian', 'north_indian'],
        })
        d = dt.date(2026, 3, 24)
        cfg = type('Cfg', (), {'cuisine_col': 'cuisine_family',
                                'cuisine_south_value': 'south_indian',
                                'cuisine_north_value': 'north_indian'})()
        # South day: bread should be south only
        filtered = rule.pre_filter_pool(pool, d, 'bread', 'south', {'cfg': cfg})
        assert list(filtered['item']) == ['dosa']

        # North day: bread should be non-south
        filtered = rule.pre_filter_pool(pool, d, 'bread', 'north', {'cfg': cfg})
        assert set(filtered['item']) == {'naan', 'paratha'}


# --- NonvegDryPreferenceRule ---

class TestNonvegDryPreferenceRule:
    def test_validate(self):
        rule = NonvegDryPreferenceRule({"name": "nv", "type": "nonveg_dry_preference"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = NonvegDryPreferenceRule({"name": "nv", "type": "nonveg_dry_preference"})
        assert rule.rule_type == MenuRuleType.NONVEG_DRY_PREFERENCE

    def test_ignores_slot_1(self):
        rule = NonvegDryPreferenceRule({"name": "nv", "type": "nonveg_dry_preference"})
        pool = pd.DataFrame({'item': ['chicken_gravy'], 'is_nonveg_dry': [0]})
        d = dt.date(2026, 3, 24)
        # slot_num=1 should not filter
        filtered = rule.pre_filter_pool(pool, d, 'nonveg_main', 'south', {'slot_num': 1})
        assert len(filtered) == 1

    def test_prefers_dry_for_slot_2(self):
        rule = NonvegDryPreferenceRule({"name": "nv", "type": "nonveg_dry_preference"})
        pool = pd.DataFrame({
            'item': ['chicken_fry', 'chicken_curry'],
            'is_nonveg_dry': [1, 0],
            'sub_category': ['', ''],
            'key_ingredient': ['chicken', 'chicken'],
            'category': ['', ''],
        })
        d = dt.date(2026, 3, 24)
        filtered = rule.pre_filter_pool(pool, d, 'nonveg_main', 'south',
                                         {'slot_num': 2, 'cfg': None,
                                          'banned_by_date': {}, 'pools': {}})
        assert list(filtered['item']) == ['chicken_fry']

    def test_apply_is_noop(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = NonvegDryPreferenceRule({"name": "nv", "type": "nonveg_dry_preference"})
        rule.apply(model, {}, None, {})
