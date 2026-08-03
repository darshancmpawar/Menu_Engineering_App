"""Seafood is a real branch of the ontology, not a chicken bucket with fish in it.

The master taxonomy grew up around a chicken-and-egg non-veg list. Chennai is the
first city with fish, and the import filed all 8 fish dishes under the nearest
chicken bucket — `fish_kuzhambu` arrived as `sub_category: chicken_south_coastal`,
`key_ingredient: chicken`, carrying `is_south_chicken_gravy`.

These tests pin the corrected state AND the reason each piece matters, because a
re-import through `normalize_city_ontology.py` silently drops the edits — the same
failure mode `test_pune_rules.py::test_flag_corrections_are_applied` guards.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from scripts.seafood_taxonomy import (
    FISH_PROTEINS,
    NEW_FLAG_COLUMNS,
    SEAFOOD_PROTEINS,
    apply_seafood_taxonomy,
)

CITY_DIR = 'data/raw/city_items'
CITIES = ['bangalore', 'chennai', 'pune']


def _read(city):
    return pd.read_excel(os.path.join(CITY_DIR, f'{city}.xlsx'))


def _to01(s):
    return pd.to_numeric(s, errors='coerce').fillna(0).astype(int)


@pytest.fixture(scope='module')
def chennai():
    return _read('chennai')


class TestTheColumnsExistEverywhere:
    """A column missing from the reference list cannot exist in any city:
    `normalize_city_ontology.py` forces a new city's column set to match it."""

    @pytest.mark.parametrize('city', CITIES)
    @pytest.mark.parametrize('col', NEW_FLAG_COLUMNS)
    def test_every_city_workbook_has_the_column(self, city, col):
        assert col in _read(city).columns

    def test_the_columns_sit_next_to_the_other_protein_flag(self):
        """Grouped after `is_egg_dish` rather than appended to a 133-column tail,
        so the protein-identity flags read together."""
        cols = list(_read('bangalore').columns)
        i = cols.index('is_egg_dish')
        assert cols[i + 1:i + 3] == list(NEW_FLAG_COLUMNS)

    def test_all_cities_share_one_column_order(self):
        ref = list(_read('bangalore').columns)
        for city in CITIES[1:]:
            assert list(_read(city).columns) == ref, city


class TestChennaiFishIsClassifiedAsFish:
    def test_all_eight_fish_rows_are_flagged(self, chennai):
        assert int(_to01(chennai['is_seafood']).sum()) == 8
        assert int(_to01(chennai['is_fish_dish']).sum()) == 8

    def test_no_fish_row_is_still_in_a_chicken_sub_category(self, chennai):
        fish = chennai[_to01(chennai['is_seafood']) == 1]
        bad = [(r['item'], r['sub_category']) for _i, r in fish.iterrows()
               if str(r['sub_category']).startswith('chicken_')]
        assert not bad, bad

    def test_the_descriptive_suffix_survived_the_rename(self, chennai):
        """`chicken_south_coastal` -> `fish_south_coastal`, not a flat `fish`.
        Nothing keys on these strings today, but throwing away 'south_coastal'
        would lose the only record of what kind of dish it is."""
        subs = dict(zip(chennai['item'], chennai['sub_category']))
        assert subs['fish_kuzhambu'] == 'fish_south_coastal'
        assert subs['chilli_fish'] == 'fish_chinese_dry'
        assert subs['fish_65'] == 'fish_spicy_fry'

    def test_key_ingredient_says_fish(self, chennai):
        """The live bug this fixes: `ingredient_ban_rule` matches on
        `key_ingredient` AND `primary_protein`, so while these rows read
        `key_ingredient: chicken` a client banning chicken also lost the fish."""
        fish = chennai[_to01(chennai['is_seafood']) == 1]
        assert set(fish['key_ingredient'].str.strip().str.lower()) == {'fish'}

    def test_no_chicken_flag_survives_on_a_fish(self, chennai):
        """`fish_kuzhambu` held `is_south_chicken_gravy`, which put a fish inside
        a rule about chicken (`avoid_consecutive_south_chicken`) and inside
        `_augment_nonveg_pair`'s regional-chicken-gravy exemption."""
        fish = chennai[_to01(chennai['is_seafood']) == 1]
        chicken_cols = [c for c in chennai.columns
                        if c.startswith('is_') and 'chicken' in c]
        for col in chicken_cols:
            assert int(_to01(fish[col]).sum()) == 0, col

    def test_the_structural_nonveg_flags_are_kept(self, chennai):
        """Clearing the chicken flags must not strip what is still true: these
        are protein-agnostic and describe the dish's role on the plate."""
        fish = chennai.set_index('item')
        assert int(_to01(pd.Series([fish.at['fish_kuzhambu', 'is_nonveg_gravy']]))[0]) == 1
        assert int(_to01(pd.Series([fish.at['fish_roast', 'is_nonveg_dry']]))[0]) == 1


class TestCuisineFamilyMatchesTheMastersOwnConvention:
    """The master files `chicken_65` as south_indian; Chennai's import put
    `fish_65` in north_indian. That is not cosmetic — the theme filter narrows
    `nonveg_main` by cuisine, so a mis-tagged dish is simply unavailable on the
    city's south days, which is most of Toast Tab's week."""

    def test_chicken_65_is_south_in_the_master(self):
        blr = _read('bangalore')
        row = blr[blr['item'] == 'chicken_65'].iloc[0]
        assert str(row['cuisine_family']).strip().lower() == 'south_indian'

    @pytest.mark.parametrize('item', ['fish_65', 'fish_roast', 'fish_kuzhambu'])
    def test_south_indian_fish_is_tagged_south(self, chennai, item):
        row = chennai[chennai['item'] == item].iloc[0]
        assert str(row['cuisine_family']).strip().lower() == 'south_indian'

    def test_tawa_fry_stays_north(self, chennai):
        """Deliberately not 'fix everything named fish': tawa fry is a north /
        street preparation and the master keeps a street/tawa bucket for it."""
        row = chennai[chennai['item'] == 'fish_tawa_fry'].iloc[0]
        assert str(row['cuisine_family']).strip().lower() == 'north_indian'

    def test_fish_is_available_on_a_south_day(self, chennai):
        """The payoff, stated directly — before the fix only fish_kuzhambu was."""
        fish = chennai[_to01(chennai['is_seafood']) == 1]
        south = fish[fish['cuisine_family'].str.strip().str.lower() == 'south_indian']
        assert len(south) >= 3


class TestTheCorrectionsAreStillApplied:
    """Re-importing a workbook through the normaliser drops these edits, so this
    is the test that notices."""

    @pytest.mark.parametrize('city', CITIES)
    def test_rerunning_the_script_changes_nothing(self, city):
        before = _read(city)
        after, changes = apply_seafood_taxonomy(before)
        assert not changes['columns_added']
        assert not changes['sub_category']
        assert not changes['key_ingredient']
        assert not changes['chicken_flags_cleared']
        assert not changes['cuisine_family']
        assert before.equals(after)

    def test_veg_only_cities_get_the_columns_but_no_rows(self):
        for city in ('bangalore', 'pune'):
            df = _read(city)
            assert int(_to01(df['is_seafood']).sum()) == 0, city

    def test_fish_is_a_subset_of_seafood(self, chennai):
        """`is_fish_dish` is the fish-only subset; a future prawn or crab row is
        `is_seafood` without being `is_fish_dish`, which is why both exist."""
        assert FISH_PROTEINS <= SEAFOOD_PROTEINS
        seafood = _to01(chennai['is_seafood'])
        fish = _to01(chennai['is_fish_dish'])
        assert ((fish == 1) <= (seafood == 1)).all()


class TestTheFlagsAreLoadBearing:
    def test_a_rule_actually_uses_the_seafood_flag(self):
        """Flags nothing reads are indistinguishable from absent ones."""
        import json
        raw = json.load(open('data/configs/city_rules/chennai.json'))
        users = [r['name'] for r in raw['rules']
                 if 'is_seafood' in json.dumps(r.get('selector', {}))]
        assert users, 'no Chennai rule reads is_seafood'

    def test_the_seafood_cap_matches_real_items(self):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader
        from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
        rule = next(r for r in MenuRuleLoader().load_for_city('Chennai')
                    if r.name == 'seafood_weekly')
        assert rule.validate_config(), rule.validation_errors()
        df = _read('chennai')
        n = sum(1 for _i, row in df.iterrows()
                if SelectorFrequencyRule._matches(row, rule._inc))
        assert n == 8
