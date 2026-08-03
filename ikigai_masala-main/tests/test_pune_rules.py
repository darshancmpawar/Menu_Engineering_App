"""The Pune regional ruleset, and the two rule types it needed.

`data/configs/city_rules/pune.json` is a transcription of
`Pune_menu_rulebook_101.xlsx` (R1-R70), so these tests check the transcription
holds — the rules load, they are enforceable against the Pune item list, and the
menu the solver returns actually obeys the ones that bite. Two capabilities were
added for it and are pinned here:

* ``color_variety`` — a city's colour numbers (R1/R2) reaching SolverConfig.
* ``repeatable_items`` — R36's "plain chapathi may run on consecutive days",
  honoured by BOTH unique_items and the item cooldown.
"""

import datetime as dt

import pandas as pd
import pytest

from api.config import city_excel_path
from src.menu_rules.color_rules import ColorVarietyMenuRule
from src.menu_rules.cooldown_rules import ItemCooldownMenuRule
from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.repeatable_items_rule import RepeatableItemsRule
from src.menu_rules.unique_items_menu_rule import matches_declared
from src.preprocessor.data_cleanser import DataCleanser
from src.preprocessor.excel_reader import ExcelReader
from src.preprocessor.pool_builder import PoolBuilder


@pytest.fixture(scope='module')
def pune_pools():
    df = DataCleanser(ExcelReader(city_excel_path('Pune')).read()).clean()
    return df, PoolBuilder.build_pools(df, required_slots=set())


@pytest.fixture(scope='module')
def pune_rules():
    return MenuRuleLoader().load_for_city('Pune')


def _flag(pool, col):
    return pool[pd.to_numeric(pool[col], errors='coerce').fillna(0) == 1]


class TestPuneRulesetShape:
    def test_all_rules_valid(self, pune_rules):
        bad = [r.name for r in pune_rules if not r.validate_config()]
        assert not bad, bad

    def test_rule_names_are_unique(self, pune_rules):
        names = [r.name for r in pune_rules]
        assert len(names) == len(set(names))

    def test_every_rule_carries_a_rulebook_reference(self):
        """Each entry names the R-number(s) it implements, so the next person can
        check the transcription against the source workbook."""
        import json
        with open('data/configs/city_rules/pune.json', encoding='utf-8') as fh:
            raw = json.load(fh)
        missing = [
            r['name'] for r in raw['rules'] if not str(r.get('_comment', '')).strip()
        ]
        assert not missing, missing

    def test_no_nonveg_or_sambar_rules(self, pune_rules):
        """Pune's item list has no non-veg station and no sambar/rasam, so a rule
        for either would be dead config that reads as coverage."""
        for rule in pune_rules:
            assert getattr(rule, 'base_slot', None) not in (
                'nonveg_main', 'sambar', 'rasam',
            ), rule.name


class TestPuneRulesBiteOnPuneData:
    """A max/min rule whose selector matches nothing is silently inert. These
    assert the rules that are supposed to constrain the Pune list actually
    match items in it — and name the ones knowingly inert."""

    KNOWN_INERT = {
        # These three are inert because the Pune list carries NO SUCH DISH — its
        # bread pool is chapati and phulka. That is a fact about the menu, not a
        # data gap: the rules are kept so they bite the day a maida, multigrain or
        # oil-based bread is added.
        #
        # (`black_chana_gravy_weekly` and `leafy_veg_dry_weekly` were inert too,
        # for the opposite reason — the dishes existed but the flags were 0.
        # scripts/pune_flag_corrections.py fixed that, and this set is what stops
        # a re-import from silently undoing it.)
        'maida_bread_weekly',
        'oil_based_bread_weekly',
        'multigrain_bread_non_consecutive',
    }

    def test_selector_rules_match_pune_items(self, pune_rules, pune_pools):
        df, pools = pune_pools
        inert = []
        for rule in pune_rules:
            if rule.rule_type.value != 'selector_frequency':
                continue
            scope = pools.get(rule.base_slot) if rule.base_slot else df
            if scope is None or not len(scope):
                inert.append(rule.name)
                continue
            n = sum(1 for _i, row in scope.iterrows() if rule._row_matches(row))
            if n == 0:
                inert.append(rule.name)
        assert set(inert) == self.KNOWN_INERT, (
            f"inert rules changed: {sorted(inert)}"
        )

    def test_attribute_grouping_columns_are_populated(self, pune_rules, pune_pools):
        _df, pools = pune_pools
        for rule in pune_rules:
            if rule.rule_type.value != 'attribute_grouping':
                continue
            pool = pools[rule.base_slot]
            values = pool[rule.group_by].dropna()
            assert len(values) == len(pool), (
                f"{rule.name}: {rule.group_by} is unset for "
                f"{len(pool) - len(values)} of {len(pool)} {rule.base_slot} items"
            )
            assert values.nunique() >= 2, (
                f"{rule.name}: only one distinct {rule.group_by}, so "
                f"non_consecutive can never be satisfied"
            )

    def test_yellow_dal_floor_is_achievable(self, pune_rules, pune_pools):
        """min targets auto-cap to what is placeable, so an over-ambitious floor
        degrades silently. Pin that Pune's really is reachable."""
        _df, pools = pune_pools
        rule = next(r for r in pune_rules if r.name == 'yellow_dal_at_least_twice')
        matching = _flag(pools['dal'], 'is_yellow_dal')
        assert len(matching) >= rule.min

    def test_flag_corrections_are_applied(self, pune_pools):
        """scripts/pune_flag_corrections.py fills two flags the raw workbook left
        at 0, which made R14 and R31 silently inert. Re-importing a fresh workbook
        from the ops team drops them again, so assert them by name rather than
        relying on the inert-rule set above to notice.
        """
        from scripts.pune_flag_corrections import (
            COLUMN_CORRECTIONS, CORRECTIONS,
        )
        df, _pools = pune_pools
        for item, flags in CORRECTIONS.items():
            row = df[df['item'] == item]
            assert len(row) == 1, f"{item} is not in the Pune list any more"
            for flag, value in flags.items():
                actual = pd.to_numeric(
                    pd.Series([row.iloc[0][flag]]), errors='coerce'
                ).fillna(0).iloc[0]
                assert int(actual) == value, (
                    f"{item}.{flag} is {actual}, expected {value} — re-run "
                    f"scripts/pune_flag_corrections.py"
                )
        for item, columns in COLUMN_CORRECTIONS.items():
            row = df[df['item'] == item]
            assert len(row) == 1, f"{item} is not in the Pune list any more"
            for column, value in columns.items():
                assert str(row.iloc[0][column]).strip() == value, (
                    f"{item}.{column} is {row.iloc[0][column]!r}, expected "
                    f"{value!r} — re-run scripts/pune_flag_corrections.py"
                )

    def test_chapati_exemption_matches_the_whole_bread_pool(self, pune_pools):
        """Pune's bread slot is chapati + phulka only. If the exemption stopped
        covering one of them, the 20-day cooldown would empty the slot in week 2
        — the failure R36 exists to prevent."""
        _df, pools = pune_pools
        bread = pools['bread']
        rule = next(
            r for r in MenuRuleLoader().load_for_city('Pune')
            if r.name == 'plain_chapati_may_repeat'
        )
        covered = [r['item'] for _i, r in bread.iterrows() if rule._row_matches(r)]
        assert sorted(covered) == sorted(bread['item'].tolist())


class TestColorVarietyRule:
    def test_overrides_are_read_from_the_ruleset(self, pune_rules):
        rule = next(r for r in pune_rules if r.rule_type.value == 'color_variety')
        assert rule.solver_overrides() == {
            'min_distinct_colors_per_day': 3,
            'min_distinct_colors_per_day_chinese': 3,
            'min_distinct_colors_per_day_biryani': 3,
            'max_same_color_per_day': 2,
            'max_colors_at_reach': 0,
            'ignore_rice_gravy_color_diff_on_chinese_day': True,
        }

    def test_rejects_non_integer_and_negative_values(self):
        assert not ColorVarietyMenuRule(
            {'name': 'x', 'type': 'color_variety', 'min_distinct_per_day': 'three'}
        ).validate_config()
        assert not ColorVarietyMenuRule(
            {'name': 'x', 'type': 'color_variety', 'max_same_color_per_day': -1}
        ).validate_config()

    def test_rejects_reach_below_the_soft_cap(self):
        rule = ColorVarietyMenuRule({
            'name': 'x', 'type': 'color_variety',
            'max_same_color_per_day': 3, 'max_same_color_reach': 2,
        })
        assert not rule.validate_config()
        assert any('reach' in e for e in rule.validation_errors())

    def test_rejects_an_empty_config(self):
        assert not ColorVarietyMenuRule(
            {'name': 'x', 'type': 'color_variety'}
        ).validate_config()

    def test_reaches_solver_config(self):
        import api.app as api_app
        from src.client.client_config import ClientConfig
        cfg = api_app._build_solver_config(
            pd.DataFrame([{'item': 'x', 'is_premium_veg': 0}]),
            ClientConfig(
                name='t', active_slots=['dal'], slot_counts={'dal': 1},
                theme_map={},
            ),
            dt.date(2026, 8, 3), 5, 60, [dt.date(2026, 8, 3)],
            rules=MenuRuleLoader().load_for_city('Pune'),
        )
        assert cfg.min_distinct_colors_per_day == 3
        assert cfg.max_same_color_per_day == 2
        assert cfg.max_colors_at_reach == 0

    def test_bangalore_keeps_the_defaults(self):
        import api.app as api_app
        from src.client.client_config import ClientConfig
        from src.solver.menu_solver import SolverConfig
        cfg = api_app._build_solver_config(
            pd.DataFrame([{'item': 'x', 'is_premium_veg': 0}]),
            ClientConfig(
                name='t', active_slots=['dal'], slot_counts={'dal': 1},
                theme_map={},
            ),
            dt.date(2026, 8, 3), 5, 60, [dt.date(2026, 8, 3)],
            rules=MenuRuleLoader().load_for_city('Bangalore'),
        )
        default = SolverConfig(days=5, start_date=dt.date(2026, 8, 3))
        assert cfg.min_distinct_colors_per_day == default.min_distinct_colors_per_day
        assert cfg.max_colors_at_reach == default.max_colors_at_reach

    def test_unknown_field_is_dropped_not_applied(self, caplog):
        import api.app as api_app

        class Rogue:
            name = 'rogue'

            def solver_overrides(self):
                return {'time_limit_sec': 9999, 'max_same_color_per_day': 2}

        out = api_app._rule_solver_overrides([Rogue()])
        assert out == {'max_same_color_per_day': 2}

    def test_a_raising_rule_does_not_break_planning(self):
        import api.app as api_app

        class Broken:
            name = 'broken'

            def solver_overrides(self):
                raise RuntimeError('boom')

        assert api_app._rule_solver_overrides([Broken()]) == {}


class TestRepeatableItemsRule:
    def _rule(self, **kw):
        cfg = {
            'name': 'chapati_staple', 'type': 'repeatable_items',
            'base_slot': 'bread', 'selector': {'flag': 'is_plain_phulka_chapathi'},
        }
        cfg.update(kw)
        return RepeatableItemsRule(cfg)

    def test_requires_base_slot_and_selector(self):
        assert not RepeatableItemsRule(
            {'name': 'x', 'type': 'repeatable_items'}).validate_config()
        assert not RepeatableItemsRule(
            {'name': 'x', 'type': 'repeatable_items', 'base_slot': 'bread'}
        ).validate_config()
        assert self._rule().validate_config()

    def test_declares_its_slot_and_matcher(self):
        declared = self._rule().repeatable_item_flags()
        assert set(declared) == {'bread'}
        row = {'item': 'chapati', 'is_plain_phulka_chapathi': 1}
        assert matches_declared(row, 'bread', {'bread': [declared['bread']]})
        # Scoped to its slot: the same dish in another slot is not exempt.
        assert not matches_declared(row, 'rice', {'bread': [declared['bread']]})

    def test_exclude_narrows_the_exemption(self):
        rule = self._rule(exclude={'item': 'phulka'})
        assert rule._row_matches({'item': 'chapati', 'is_plain_phulka_chapathi': 1})
        assert not rule._row_matches({'item': 'phulka', 'is_plain_phulka_chapathi': 1})

    def test_cooldown_keeps_a_declared_staple(self):
        """The point of the rule. Without the declaration the cooldown empties a
        2-item bread slot as soon as both dishes are in history."""
        pool = pd.DataFrame([
            {'item': 'chapati', 'is_plain_phulka_chapathi': 1},
            {'item': 'phulka', 'is_plain_phulka_chapathi': 1},
            {'item': 'butter_naan', 'is_plain_phulka_chapathi': 0},
        ])
        d = dt.date(2026, 8, 3)
        banned = {'banned_by_date': {d: {'chapati', 'phulka', 'butter_naan'}}}
        cooldown = ItemCooldownMenuRule(
            {'name': 'cd', 'type': 'item_cooldown', 'cooldown_days': 20})

        without = cooldown.pre_filter_pool(pool, d, 'bread', 'north', banned)
        assert list(without['item']) == []

        declared = {'extra_repeatable': {
            'bread': [self._rule().repeatable_item_flags()['bread']]}}
        with_decl = cooldown.pre_filter_pool(
            pool, d, 'bread', 'north', {**banned, **declared})
        assert sorted(with_decl['item']) == ['chapati', 'phulka']

    def test_declaration_is_slot_scoped_in_the_cooldown(self):
        """A bread declaration must not exempt the same dish in another slot."""
        pool = pd.DataFrame([{'item': 'chapati', 'is_plain_phulka_chapathi': 1}])
        d = dt.date(2026, 8, 3)
        ctx = {
            'banned_by_date': {d: {'chapati'}},
            'extra_repeatable': {
                'bread': [self._rule().repeatable_item_flags()['bread']]},
        }
        cooldown = ItemCooldownMenuRule(
            {'name': 'cd', 'type': 'item_cooldown', 'cooldown_days': 20})
        assert len(cooldown.pre_filter_pool(pool, d, 'bread', 'north', ctx)) == 1
        assert len(cooldown.pre_filter_pool(pool, d, 'rice', 'north', ctx)) == 0

    def test_solver_collects_the_declaration(self):
        """MenuSolver._declared_repeatable is the single collection point both
        unique_items and the cooldown read."""
        from src.solver.menu_solver import MenuSolver, SolverConfig
        solver = MenuSolver(
            pools={}, solver_config=SolverConfig(days=1, start_date=dt.date(2026, 8, 3)),
            menu_rules=[self._rule()],
        )
        assert set(solver._declared_repeatable()) == {'bread'}
