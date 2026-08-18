"""Tests for the dual-field ingredient ban (#6) and cuisine exclusivity (#4a)."""

import datetime as dt

import pandas as pd

from src.menu_rules.ingredient_ban_rule import IngredientBanRule
from src.menu_rules.theme_rules import ThemeSlotFilterRule


class TestIngredientBanBothFields:
    def _pool(self):
        return pd.DataFrame([
            {'item': 'mushroom_masala', 'key_ingredient': 'mushroom', 'primary_protein': ''},
            {'item': 'creamy_mushroom', 'key_ingredient': 'cream', 'primary_protein': 'mushroom'},
            {'item': 'paneer_butter', 'key_ingredient': 'paneer', 'primary_protein': 'paneer'},
        ])

    def test_bans_by_key_ingredient_and_primary_protein(self):
        rule = IngredientBanRule({'name': 'no_mush', 'ingredients': ['mushroom']})
        out = rule.pre_filter_pool(self._pool(), dt.date(2026, 3, 23), 'veg_gravy', 'mix', {})
        items = set(out['item'])
        assert 'mushroom_masala' not in items       # matched key_ingredient
        assert 'creamy_mushroom' not in items        # matched primary_protein
        assert 'paneer_butter' in items              # untouched


class TestCuisineExclusivity:
    def _rule(self):
        return ThemeSlotFilterRule({'name': 'tf', 'type': 'theme_slot_filter'})

    def _pool(self):
        return pd.DataFrame([
            {'item': 'penne_arrabiata', 'cuisine_family': 'continental'},
            {'item': 'gobi_manchurian', 'cuisine_family': 'chinese'},
            {'item': 'paneer_tikka_masala', 'cuisine_family': 'north_indian'},
        ])

    def test_continental_dropped_from_main_slot_on_non_continental_day(self):
        out = self._rule()._exclude_offtheme_cuisines(self._pool(), 'veg_gravy', 'south')
        assert 'penne_arrabiata' not in set(out['item'])
        assert 'gobi_manchurian' not in set(out['item'])   # chinese also dropped
        assert 'paneer_tikka_masala' in set(out['item'])

    def test_continental_kept_on_continental_day(self):
        out = self._rule()._exclude_offtheme_cuisines(self._pool(), 'veg_gravy', 'continental')
        assert 'penne_arrabiata' in set(out['item'])
        assert 'gobi_manchurian' not in set(out['item'])   # chinese still dropped

    def test_veg_dry_never_continental_even_on_continental_day(self):
        # #4b: on a continental day the continental veg is the GRAVY; veg_dry
        # stays a normal (Indian) dish, so continental is dropped from veg_dry
        # even on the continental day.
        out = self._rule()._exclude_offtheme_cuisines(self._pool(), 'veg_dry', 'continental')
        items = set(out['item'])
        assert 'penne_arrabiata' not in items          # continental dropped
        assert 'gobi_manchurian' not in items          # chinese dropped
        assert 'paneer_tikka_masala' in items          # Indian stays

    def test_universal_slot_not_restricted(self):
        # salad is not a cuisine-main slot -> continental salads stay any day
        out = self._rule()._exclude_offtheme_cuisines(self._pool(), 'salad', 'south')
        assert 'penne_arrabiata' in set(out['item'])

    def test_never_empties_a_slot(self):
        # an all-continental main-slot pool on a non-continental day falls back
        pool = pd.DataFrame([{'item': 'pasta', 'cuisine_family': 'continental'}])
        out = self._rule()._exclude_offtheme_cuisines(pool, 'rice', 'north')
        assert len(out) == 1
