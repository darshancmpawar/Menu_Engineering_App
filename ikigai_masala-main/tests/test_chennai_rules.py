"""The Chennai ruleset and ontology.

Chennai arrived as an item list plus ONE client's service history, with no
rulebook — unlike Pune, whose 36 rules transcribe `Pune_menu_rulebook_101.xlsx`.
So `chennai.json` is the engine skeleton plus caps provable from the list, and
what these tests pin is that every rule still *matches real Chennai items*: an
inert rule is the failure mode this file exists to catch, because it reads as
enforced and constrains nothing.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule


@pytest.fixture(scope='module')
def chennai_df():
    from api.config import city_excel_path
    from src.preprocessor.data_cleanser import DataCleanser
    from src.preprocessor.excel_reader import ExcelReader
    return DataCleanser(ExcelReader(city_excel_path('Chennai')).read()).clean()


@pytest.fixture(scope='module')
def chennai_pools(chennai_df):
    from api.config import city_required_slots
    from src.preprocessor.pool_builder import PoolBuilder
    return PoolBuilder().build_pools(
        chennai_df, required_slots=city_required_slots('Chennai'))


@pytest.fixture(scope='module')
def chennai_rules():
    return MenuRuleLoader().load_for_city('Chennai')


class TestOntology:
    def test_the_workbook_is_in_reference_shape(self, chennai_df):
        ref = pd.read_excel('data/raw/city_items/bangalore.xlsx', nrows=1)
        chn = pd.read_excel('data/raw/city_items/chennai.xlsx', nrows=1)
        assert list(chn.columns) == list(ref.columns)

    def test_city_resolves_to_its_own_workbook(self):
        import os
        from api.config import city_excel_path
        assert os.path.basename(city_excel_path('Chennai')) == 'chennai.xlsx'

    def test_declared_categories_are_all_covered(self, chennai_pools):
        """`ontology_categories.json` is the strict check — a declared category
        that comes out empty is a mapping regression, not a menu decision."""
        declared = json.load(
            open('data/raw/city_items/ontology_categories.json'))['chennai']
        for cat in declared:
            assert len(chennai_pools.get(cat, [])) > 0, f'{cat} is empty'

    def test_chennai_has_no_welcome_drinks(self, chennai_df):
        """The reason chennai.json is standalone rather than extending Bangalore:
        every drink rule Bangalore ships would be inert here."""
        assert 'welcome_drink' not in set(chennai_df['course_type'])
        assert int(pd.to_numeric(
            chennai_df['is_welcome_drink'], errors='coerce').fillna(0).sum()) == 0
        declared = json.load(
            open('data/raw/city_items/ontology_categories.json'))['chennai']
        assert 'welcome_drink' not in declared

    def test_chennai_carries_nonveg(self, chennai_df):
        """Unlike Pune (all-veg), so dishes render red and nonveg rules apply."""
        assert len(chennai_df[chennai_df['course_type'] == 'nonveg_main']) > 0


class TestEveryRuleIsValidAndMatchesSomething:
    def test_no_rule_fails_validation(self, chennai_rules):
        bad = {r.name: r.validation_errors() for r in chennai_rules
               if not r.validate_config()}
        assert not bad, bad

    def test_the_ruleset_is_standalone(self):
        raw = json.load(open('data/configs/city_rules/chennai.json'))
        assert 'extends' not in raw, (
            "chennai.json must not extend bangalore: a third of Bangalore's "
            "rules key on flags Chennai leaves at 0")
        assert len(raw['rules']) > 20

    @pytest.mark.parametrize('attr', ['_inc', '_sel', '_sel_a', '_sel_b', '_exc'])
    def test_no_selector_matches_nothing(self, chennai_rules, chennai_df, attr):
        """A selector matching zero rows is a rule that does nothing."""
        inert = []
        for r in chennai_rules:
            m = getattr(r, attr, None)
            if m is None:
                continue
            n = sum(1 for _i, row in chennai_df.iterrows()
                    if SelectorFrequencyRule._matches(row, m))
            if n == 0:
                inert.append(f'{r.name}.{attr}')
        assert not inert, inert

    @pytest.mark.parametrize('slot,col', [
        ('dal', 'item_color'),
        ('sambar', 'key_ingredient'),
        ('dessert', 'dessert_form'),
        ('veg_gravy', 'key_ingredient'),
        ('veg_dry', 'key_ingredient'),
    ])
    def test_attribute_grouping_columns_are_populated(self, chennai_df, slot, col):
        """`group_by` on an empty column is silently inert, the same trap as a
        selector matching nothing."""
        sub = chennai_df[chennai_df['course_type'] == slot]
        vals = sub[col].astype(str).str.strip()
        vals = vals[~vals.isin(('', 'nan', 'None'))]
        assert len(vals) == len(sub), f'{slot}.{col} has blanks'
        assert vals.nunique() >= 2, f'{slot}.{col} has only one value'


class TestStaplesThatWouldOtherwiseStarve:
    """Chennai's spine slots hold 2-4 dishes each and run most days. Without the
    staple declarations `unique_items` empties them inside a single plan."""

    @pytest.mark.parametrize('slot,expected_max', [
        ('rasam', 2), ('curd_rice', 2), ('curd_side', 4),
    ])
    def test_the_slot_really_is_that_small(self, chennai_pools, slot, expected_max):
        assert len(chennai_pools[slot]) <= expected_max

    @pytest.mark.parametrize('slot', ['rasam', 'curd_side', 'curd_rice', 'bread'])
    def test_a_staple_rule_covers_the_slot(self, chennai_rules, chennai_pools, slot):
        from src.menu_rules.unique_items_menu_rule import matches_declared
        declared = {}
        for r in chennai_rules:
            hook = getattr(r, 'repeatable_item_flags', None)
            if hook:
                for k, v in (hook() or {}).items():
                    declared.setdefault(k, []).append(v)
        pool = chennai_pools[slot]
        exempt = [row['item'] for _i, row in pool.iterrows()
                  if matches_declared(row, slot, declared)]
        assert exempt, f'{slot} has no declared staple'


class TestBreadIsExemptFromTheCuisineLock:
    """The bread cuisine lock used to run AHEAD of the `exempt_slots` check and
    could not be switched off — listing `bread` was silently ignored (the
    diagnose path even read `if base in exempt_slots and base != 'bread'`).

    Chennai needs it off: its 29-dish bread pool narrows to the 10 south-tagged
    rows on a south day, and those are the dosai/idly family, so a Tamil lunch
    lost the chapati it actually serves beside the rice.
    """

    @pytest.fixture(scope='class')
    def filter_rule(self):
        return next(r for r in MenuRuleLoader().load_for_city('Chennai')
                    if r.rule_type.value == 'theme_slot_filter')

    def test_chennai_lists_bread_as_exempt(self, filter_rule):
        assert 'bread' in filter_rule.exempt_slots

    @pytest.mark.parametrize('day_type', ['south', 'north', 'biryani'])
    def test_bread_is_not_narrowed_on_any_theme(self, filter_rule, chennai_pools,
                                                day_type):
        pool = chennai_pools['bread']
        out = filter_rule.pre_filter_pool(
            pool.copy(), dt.date(2026, 8, 3), 'bread', day_type, {})
        assert len(out) == len(pool)

    def test_wheat_flatbreads_survive_a_south_day(self, filter_rule, chennai_pools):
        """The point of the exemption, stated positively: without it none of the
        chapati/paratha family is eligible on a south day."""
        pool = chennai_pools['bread']
        out = filter_rule.pre_filter_pool(
            pool.copy(), dt.date(2026, 8, 3), 'bread', 'south', {})
        flags = ['is_plain_phulka_chapathi', 'is_paratha', 'is_maida_bread',
                 'is_tandoori_roti']
        n = sum(
            1 for _i, row in out.iterrows()
            if any(int(pd.to_numeric([row.get(f)], errors='coerce')[0] or 0) == 1
                   for f in flags)
        )
        assert n >= 15, f'only {n} wheat flatbreads eligible on a south day'

    @pytest.mark.parametrize('city', ['Bangalore', 'Pune'])
    def test_cities_not_listing_bread_still_get_the_lock(self, city, chennai_df):
        """The fix must not switch the lock off anywhere else. Bangalore's bread
        pool genuinely narrows by cuisine and should keep doing so."""
        from api.config import city_excel_path, city_required_slots
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader
        from src.preprocessor.pool_builder import PoolBuilder
        rule = next(r for r in MenuRuleLoader().load_for_city(city)
                    if r.rule_type.value == 'theme_slot_filter')
        assert 'bread' not in rule.exempt_slots
        df = DataCleanser(ExcelReader(city_excel_path(city)).read()).clean()
        pools = PoolBuilder().build_pools(
            df, required_slots=city_required_slots(city))
        pool = pools['bread']
        south = rule.pre_filter_pool(
            pool.copy(), dt.date(2026, 8, 3), 'bread', 'south', {})
        if len(pool) > 10:      # Pune's pool is 2 chapatis; nothing to narrow
            assert len(south) < len(pool), (
                f'{city} bread should still narrow on a south day')
