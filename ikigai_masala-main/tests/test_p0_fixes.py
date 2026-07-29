"""Fast unit tests for the P0 fixes.

The all-clients sweep in ``test_all_clients_generate.py`` proves these fixes
against real client configs, but it is marked ``slow`` and so is deselected on
pull requests. These tests cover the same logic cheaply — no full solve, no
Excel — so a regression is caught by the default CI run.
"""

import contextlib
import datetime as dt
import logging

import pandas as pd
import pytest
from ortools.sat.python import cp_model


from src.menu_rules.menu_rule_loader import MenuRuleLoader
from src.menu_rules.nonveg_rules import NonvegBiryaniWeeklyRule
from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
from src.menu_rules.slot_composition_rule import SlotCompositionRule
from src.menu_rules.unique_items_menu_rule import (
    UniqueItemsMenuRule,
    starved_slots,
)
from src.solver._helpers import planned_dates, weekday_name
from src.solver.solution_formatter import SolutionFormatter

MON = dt.date(2026, 8, 3)


@contextlib.contextmanager
def capture_logs(logger_name, level=logging.WARNING):
    """Collect messages from one logger, independent of dictConfig.

    ``caplog`` attaches to the root logger, and ``api.logging_config`` configures
    the ``api`` hierarchy with its own handler, so root never sees those records.
    Attaching directly to the named logger keeps these tests working regardless
    of how logging is configured.
    """
    logger = logging.getLogger(logger_name)
    messages = []

    class _Collect(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Collect(level=level)
    prev_level, prev_disabled = logger.level, logger.disabled
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.disabled = False
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.disabled = prev_disabled


class _Cell:
    def __init__(self, d_idx, base_slot, x_vars, cand_rows, slot_id=None):
        self.d_idx = d_idx
        self.base_slot = base_slot
        self.slot_id = slot_id or base_slot
        self.x_vars = x_vars
        self.cand_rows = cand_rows
        self.date = MON + dt.timedelta(days=d_idx)


def _rows(names):
    return [pd.Series({'item': n}) for n in names]


def _build(model, n_days, base_slot, item_names, cells_per_day=1):
    """One cell per (day, index), each choosing exactly one of *item_names*."""
    cells = []
    for di in range(n_days):
        for ci in range(cells_per_day):
            xs = [model.NewBoolVar(f'{base_slot}_{di}_{ci}_{i}')
                  for i in range(len(item_names))]
            model.Add(sum(xs) == 1)
            cells.append(_Cell(di, base_slot, xs, _rows(item_names)))
    return cells


def _item_to_vars(cells):
    out = {}
    for c in cells:
        for v, r in zip(c.x_vars, c.cand_rows):
            out.setdefault(r['item'], []).append(v)
    return out


def _status(model):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    return solver.StatusName(solver.Solve(model))


# --------------------------------------------------------------------------
# weekday / horizon helpers
# --------------------------------------------------------------------------

class TestPlannedDates:
    def test_weekday_name_is_locale_independent(self):
        assert weekday_name(MON) == 'monday'
        assert weekday_name(MON + dt.timedelta(days=4)) == 'friday'

    def test_explicit_dates_win(self):
        cfg = type('C', (), {
            'explicit_dates': [MON, MON + dt.timedelta(days=1)],
            'working_days': None})()
        assert planned_dates(cfg) == [MON, MON + dt.timedelta(days=1)]

    def test_working_days_filter_the_horizon(self):
        cfg = type('C', (), {
            'explicit_dates': [MON + dt.timedelta(days=i) for i in range(5)],
            'working_days': ['wednesday', 'friday']})()
        assert [weekday_name(d) for d in planned_dates(cfg)] == [
            'wednesday', 'friday']

    def test_range_used_when_no_explicit_dates(self):
        cfg = type('C', (), {
            'explicit_dates': None, 'start_date': MON, 'days': 3,
            'working_days': None})()
        assert len(planned_dates(cfg)) == 3

    def test_no_overlap_yields_empty(self):
        """A horizon containing none of the working days must be detectable."""
        cfg = type('C', (), {
            'explicit_dates': [MON], 'working_days': ['sunday']})()
        assert planned_dates(cfg) == []


# --------------------------------------------------------------------------
# unique_items: starvation detection + relaxation
# --------------------------------------------------------------------------

class TestStarvedSlots:
    def test_detects_slot_with_fewer_items_than_cells(self):
        m = cp_model.CpModel()
        cells = _build(m, 5, 'curd_rice', ['a', 'b', 'c', 'd'])
        assert 'curd_rice' in starved_slots(cells)

    def test_healthy_slot_not_flagged(self):
        m = cp_model.CpModel()
        cells = _build(m, 5, 'dessert', ['a', 'b', 'c', 'd', 'e', 'f'])
        assert starved_slots(cells) == {}

    def test_repeatable_slot_never_flagged(self):
        m = cp_model.CpModel()
        cells = _build(m, 5, 'curd', ['only_one'])
        assert starved_slots(cells) == {}


class TestUniqueItemsRelaxation:
    def test_strict_uniqueness_is_infeasible_when_starved(self):
        """Baseline: 4 items for 5 days cannot be unique."""
        m = cp_model.CpModel()
        cells = _build(m, 5, 'curd_rice', ['a', 'b', 'c', 'd'])
        for vars_ in _item_to_vars(cells).values():
            m.Add(sum(vars_) <= 1)
        assert _status(m) == 'INFEASIBLE'

    def test_rule_relaxes_starved_slot_instead_of_failing(self):
        m = cp_model.CpModel()
        cells = _build(m, 5, 'curd_rice', ['a', 'b', 'c', 'd'])
        rule = UniqueItemsMenuRule({'name': 'u', 'type': 'unique_items'})
        with capture_logs('src.menu_rules.unique_items_menu_rule') as msgs:
            rule.apply(m, {}, None,
                       {'cells': cells, 'item_to_vars': _item_to_vars(cells)})
        assert _status(m) in ('OPTIMAL', 'FEASIBLE')
        assert any('curd_rice' in msg for msg in msgs), msgs

    def test_healthy_slots_keep_strict_uniqueness(self):
        """Relaxing one slot must not license repeats in another."""
        m = cp_model.CpModel()
        starved = _build(m, 5, 'curd_rice', ['a', 'b', 'c', 'd'])
        healthy = _build(m, 5, 'dessert', ['d1', 'd2', 'd3', 'd4', 'd5'])
        cells = starved + healthy
        rule = UniqueItemsMenuRule({'name': 'u', 'type': 'unique_items'})
        rule.apply(m, {}, None,
                   {'cells': cells, 'item_to_vars': _item_to_vars(cells)})
        # force two dessert days onto the same item -> must be rejected
        m.Add(healthy[0].x_vars[0] == 1)
        m.Add(healthy[1].x_vars[0] == 1)
        assert _status(m) == 'INFEASIBLE'

    def test_relaxed_slot_still_maximises_variety(self):
        """Relaxed must not mean "serve one dish five times".

        4 items over 5 days has to repeat exactly once. The repeat penalty must
        drive the solver to use all 4 rather than take the cheapest feasible
        answer of one item five times.
        """
        m = cp_model.CpModel()
        cells = _build(m, 5, 'curd_rice', ['a', 'b', 'c', 'd'])
        rule = UniqueItemsMenuRule({'name': 'u', 'type': 'unique_items'})
        ctx = {'cells': cells, 'item_to_vars': _item_to_vars(cells)}
        rule.apply(m, {}, None, ctx)
        terms = rule.get_objective_terms(m, ctx)
        assert terms, "a relaxed slot must contribute a repeat penalty"
        m.Maximize(sum(terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.parameters.num_search_workers = 1
        assert solver.StatusName(solver.Solve(m)) in ('OPTIMAL', 'FEASIBLE')

        picked = []
        for c in cells:
            for v, r in zip(c.x_vars, c.cand_rows):
                if solver.Value(v) == 1:
                    picked.append(r['item'])
        assert len(picked) == 5
        assert len(set(picked)) == 4, (
            f"expected all 4 items used with a single repeat, got {picked}"
        )


# --------------------------------------------------------------------------
# nonveg biryani weekly cap auto-relax
# --------------------------------------------------------------------------

class TestNonvegBiryaniCap:
    def _cells(self, model, n_days, all_biryani):
        cells = []
        for di in range(n_days):
            xs = [model.NewBoolVar(f'nv{di}_{i}') for i in range(2)]
            model.Add(sum(xs) == 1)
            rows = [pd.Series({'item': f'b{di}', 'is_nonveg_biryani': 1}),
                    pd.Series({'item': f'x{di}',
                               'is_nonveg_biryani': 1 if all_biryani else 0})]
            cells.append(_Cell(di, 'nonveg_main', xs, rows))
        return cells

    def _ctx(self, cells, n_days):
        from src.solver.menu_solver import _link_any
        return {
            'cells': cells,
            'dates': [MON + dt.timedelta(days=i) for i in range(n_days)],
            'link_any_fn': _link_any,
        }

    def test_cap_is_never_silently_raised(self):
        """A theme map that forces more biryani days than the cap is a config
        conflict. The rule must keep enforcing the cap — silently raising it
        would hand back a menu that breaks the weekly-variety rule."""
        m = cp_model.CpModel()
        cells = self._cells(m, 5, all_biryani=True)
        rule = NonvegBiryaniWeeklyRule({
            'name': 'nb', 'type': 'nonveg_biryani_weekly', 'max_per_week': 1})
        rule.apply(m, {}, None, self._ctx(cells, 5))
        assert _status(m) == 'INFEASIBLE'

    def test_conflict_is_reported_as_a_blocking_diagnostic(self):
        """...and the conflict is surfaced with the config change to make."""
        from src.menu_rules.base_menu_rule import (
            DiagnoseContext, DiagnosticSeverity,
        )
        pool = pd.DataFrame({
            'item': ['b1', 'b2'], 'is_nonveg_biryani': [1, 1],
        })
        dates = [MON + dt.timedelta(days=i) for i in range(5)]
        ctx = DiagnoseContext(
            pools={'nonveg_main': pool}, dates=dates,
            day_types={d: 'biryani' for d in dates},
            cfg=type('C', (), {'rice_exclude_items': set()})(),
            df=pool, banned_by_date={}, ricebread_ban_day={}, skip_cells=set(),
            client_cfg=type('K', (), {'slot_counts': {'nonveg_main': 1}})(),
            active_base_slots=['nonveg_main'],
        )
        rule = NonvegBiryaniWeeklyRule({
            'name': 'nonveg_biryani_once_per_week',
            'type': 'nonveg_biryani_weekly', 'max_per_week': 1})
        errors = [d for d in rule.diagnose(ctx)
                  if d.severity == DiagnosticSeverity.ERROR]
        assert errors, "the contradiction must block, not reach the solver"
        assert 'disable' in errors[0].suggestion
        assert errors[0].affected['forced_biryani_days'] == 5

    def test_cap_still_binds_when_alternatives_exist(self):
        m = cp_model.CpModel()
        cells = self._cells(m, 5, all_biryani=False)
        rule = NonvegBiryaniWeeklyRule({
            'name': 'nb', 'type': 'nonveg_biryani_weekly', 'max_per_week': 1})
        rule.apply(m, {}, None, self._ctx(cells, 5))
        # two days both on the biryani candidate must be rejected
        m.Add(cells[0].x_vars[0] == 1)
        m.Add(cells[1].x_vars[0] == 1)
        assert _status(m) == 'INFEASIBLE'


# --------------------------------------------------------------------------
# slot_composition: pinned sibling must not disable or over-constrain
# --------------------------------------------------------------------------

class TestSlotCompositionWithPinnedSibling:
    RULE = {
        'name': 'pair', 'type': 'slot_composition', 'base_slot': 'nonveg_main',
        'requires_slot_count': 2,
        'components': [
            {'selector': {'flag': 'is_egg_dish'}, 'count': 1},
            {'selector': {'primary_protein': 'chicken'}, 'count': 1},
        ],
    }
    CANDS = [
        {'item': 'egg1', 'is_egg_dish': 1},
        {'item': 'chk1', 'primary_protein': 'chicken'},
    ]

    def _run(self, surviving_cells, configured=2):
        m = cp_model.CpModel()
        cells = []
        for ci in range(surviving_cells):
            xs = [m.NewBoolVar(f'p{ci}_{i}') for i in range(len(self.CANDS))]
            m.Add(sum(xs) == 1)
            cells.append(_Cell(0, 'nonveg_main', xs,
                               [pd.Series(c) for c in self.CANDS]))
        cfg = type('C', (), {'slot_counts': {'nonveg_main': configured}})()
        rule = SlotCompositionRule(dict(self.RULE))
        rule.apply(m, {}, None, {
            'cells': cells, 'dates': [MON], 'day_types': ['mix'], 'cfg': cfg})
        return _status(m)

    def test_both_components_enforced_when_both_cells_present(self):
        assert self._run(2) in ('OPTIMAL', 'FEASIBLE')

    def test_single_surviving_cell_stays_feasible(self):
        """A pinned sibling leaves one cell; the rule must degrade, not demand
        two different dishes from it."""
        assert self._run(1) in ('OPTIMAL', 'FEASIBLE')

    def test_rule_still_applies_with_one_cell(self):
        """It must not silently switch off: the surviving cell is constrained
        to the first component."""
        m = cp_model.CpModel()
        xs = [m.NewBoolVar(f'q{i}') for i in range(len(self.CANDS))]
        m.Add(sum(xs) == 1)
        cells = [_Cell(0, 'nonveg_main', xs,
                       [pd.Series(c) for c in self.CANDS])]
        cfg = type('C', (), {'slot_counts': {'nonveg_main': 2}})()
        SlotCompositionRule(dict(self.RULE)).apply(m, {}, None, {
            'cells': cells, 'dates': [MON], 'day_types': ['mix'], 'cfg': cfg})
        # first component is is_egg_dish -> the chicken-only pick is excluded
        m.Add(xs[1] == 1)
        assert _status(m) == 'INFEASIBLE'


# --------------------------------------------------------------------------
# rule override is a per-key merge
# --------------------------------------------------------------------------

class TestOverrideMerge:
    PARENT = [{
        'name': 'pair', 'type': 'slot_composition', 'base_slot': 'nonveg_main',
        'requires_slot_count': 2,
        'components': [{'selector': {'flag': 'a'}, 'count': 1}],
        'components_by_theme': {'chinese': [{'selector': {'flag': 'c'},
                                             'count': 1}]},
    }]

    def test_omitted_keys_are_inherited(self):
        child = [{'name': 'pair', 'type': 'slot_composition',
                  'base_slot': 'nonveg_main', 'requires_slot_count': 2,
                  'components': [{'selector': {'flag': 'b'}, 'count': 1}]}]
        merged = MenuRuleLoader._merge_rule_dicts(self.PARENT, child, [])
        assert len(merged) == 1
        assert merged[0]['components'][0]['selector'] == {'flag': 'b'}
        assert 'components_by_theme' in merged[0], (
            "a partial override must not delete the base rule's theme variants"
        )

    def test_explicit_null_removes_an_inherited_key(self):
        child = [{'name': 'pair', 'components_by_theme': None}]
        merged = MenuRuleLoader._merge_rule_dicts(self.PARENT, child, [])
        assert 'components_by_theme' not in merged[0]

    def test_disable_drops_the_rule(self):
        merged = MenuRuleLoader._merge_rule_dicts(self.PARENT, [], ['pair'])
        assert merged == []

    def test_new_names_append_and_no_duplicates(self):
        child = [{'name': 'other', 'type': 'unique_items'}]
        merged = MenuRuleLoader._merge_rule_dicts(self.PARENT, child, [])
        names = [r['name'] for r in merged]
        assert names == ['pair', 'other']
        assert len(names) == len(set(names))


# --------------------------------------------------------------------------
# pinned constants: non-veg tagging
# --------------------------------------------------------------------------

class TestPinnedConstantNonvegTagging:
    def _fmt(self, plan):
        return SolutionFormatter(
            plan, [MON], nonveg_items={'boiled_egg', 'murgh_makhni'},
        ).to_dict()[MON.isoformat()]['items']

    def test_space_written_constant_matches_snake_case_ontology(self):
        items = self._fmt({MON: {'nonveg_main': 'boiled egg'}})
        assert items['nonveg_main']['is_nonveg'] is True

    def test_anything_in_the_nonveg_slot_is_nonveg(self):
        items = self._fmt({MON: {'nonveg_main__2': 'some off-menu dish'}})
        assert items['nonveg_main__2']['is_nonveg'] is True

    def test_veg_slot_constant_stays_veg(self):
        items = self._fmt({MON: {'salad': 'green salad'}})
        assert items['salad']['is_nonveg'] is False

    def test_known_nonveg_item_still_tagged(self):
        items = self._fmt({MON: {'veg_gravy': 'murgh_makhni'}})
        assert items['veg_gravy']['is_nonveg'] is True


# --------------------------------------------------------------------------
# constant value validation
# --------------------------------------------------------------------------

class TestConstantValueValidation:
    @pytest.fixture
    def df(self):
        return pd.DataFrame({'item': ['boiled_egg', 'green_salad']})

    def test_unknown_value_warns(self, df):
        from api.app import _validate_constant_values
        with capture_logs('api.app') as msgs:
            _validate_constant_values('X', {'salad': 'nonexistent dish'}, df)
        assert any('nonexistent dish' in m for m in msgs), msgs

    def test_known_value_is_quiet(self, df):
        from api.app import _validate_constant_values
        with capture_logs('api.app') as msgs:
            _validate_constant_values('X', {'salad': 'green salad'}, df)
        assert msgs == []

    def test_non_string_value_warns(self, df):
        from api.app import _validate_constant_values
        with capture_logs('api.app') as msgs:
            _validate_constant_values('X', {'salad': 5}, df)
        assert any('not a string' in m for m in msgs), msgs

    def test_weekday_map_values_are_checked(self, df):
        from api.app import _validate_constant_values
        with capture_logs('api.app') as msgs:
            _validate_constant_values(
                'X', {'curd': {'monday': 'green salad', 'friday': 'bogus'}}, df)
        joined = ' '.join(msgs)
        assert 'bogus' in joined and 'green salad' not in joined


# --------------------------------------------------------------------------
# per-counter scoping of client rule overrides
# --------------------------------------------------------------------------

class TestPerCounterScoping:
    BLOCK = {
        'disable': ['client_wide_rule'],
        'rules': [{'name': 'client_rule', 'type': 'unique_items'}],
        'constant_items': {'salad': 'client salad'},
        'counters': {
            'Non Veg Lunch': {
                'disable': ['nonveg_biryani_once_per_week'],
                'rules': [{'name': 'counter_rule', 'type': 'unique_items'}],
                'constant_items': {'bread': 'counter bread'},
            },
        },
    }

    def test_counter_layer_adds_to_client_layer(self):
        p = MenuRuleLoader._parse_client_block(self.BLOCK, 'Non Veg Lunch')
        assert p['disable'] == [
            'client_wide_rule', 'nonveg_biryani_once_per_week']
        assert [r['name'] for r in p['rules']] == ['client_rule', 'counter_rule']
        assert p['constant_items'] == {
            'salad': 'client salad', 'bread': 'counter bread'}

    def test_other_counters_do_not_see_the_scoped_override(self):
        """The whole point: a rule dropped for one station stays on elsewhere."""
        p = MenuRuleLoader._parse_client_block(self.BLOCK, 'South Lunch')
        assert p['disable'] == ['client_wide_rule']
        assert 'nonveg_biryani_once_per_week' not in p['disable']
        assert [r['name'] for r in p['rules']] == ['client_rule']
        assert p['constant_items'] == {'salad': 'client salad'}

    def test_no_counter_name_yields_client_layer_only(self):
        p = MenuRuleLoader._parse_client_block(self.BLOCK, None)
        assert p['disable'] == ['client_wide_rule']

    def test_legacy_list_form_still_supported(self):
        p = MenuRuleLoader._parse_client_block(
            [{'name': 'x', 'type': 'unique_items'}], 'Any')
        assert [r['name'] for r in p['rules']] == ['x']
        assert p['disable'] == [] and p['constant_items'] == {}

    def test_real_config_scopes_the_lt_biryani_cap(self):
        """The shipped L&T entry must apply only to its non-veg counter."""
        import json
        from pathlib import Path
        import src.menu_rules.menu_rule_loader as loader_mod
        blob = json.loads(Path(loader_mod.CLIENT_RULES_CONFIG_PATH).read_text())
        block = blob.get('L&T')
        if not block:
            pytest.skip('no L&T entry configured')
        nonveg = MenuRuleLoader._parse_client_block(block, 'Non Veg Lunch')
        south = MenuRuleLoader._parse_client_block(block, 'South Lunch')
        assert 'nonveg_biryani_once_per_week' in nonveg['disable']
        assert 'nonveg_biryani_once_per_week' not in south['disable']


# --------------------------------------------------------------------------
# diagnose() on the config-driven rule types (P1)
# --------------------------------------------------------------------------

def _diag_ctx(pools, *, dates=None, day_types=None, slot_counts=None,
              active=None, skip=None):
    from src.menu_rules.base_menu_rule import DiagnoseContext
    dates = dates or [MON + dt.timedelta(days=i) for i in range(5)]
    return DiagnoseContext(
        pools=pools, dates=dates,
        day_types=day_types or {d: 'mix' for d in dates},
        cfg=type('C', (), {'rice_exclude_items': set()})(),
        df=pd.DataFrame(), banned_by_date={}, ricebread_ban_day={},
        skip_cells=skip or set(),
        client_cfg=type('K', (), {'slot_counts': slot_counts or {}})(),
        active_base_slots=active,
    )


class TestSelectorFrequencyDiagnose:
    """The most-used rule type was invisible to pre-flight before this."""

    def _rule(self, **over):
        cfg = {'name': 'r', 'type': 'selector_frequency',
               'selector': {'flag': 'is_liquid_dessert'},
               'base_slot': 'dessert'}
        cfg.update(over)
        return SelectorFrequencyRule(cfg)

    def _pool(self, liquid_flags):
        return pd.DataFrame({
            'item': [f'd{i}' for i in range(len(liquid_flags))],
            'is_liquid_dessert': liquid_flags,
        })

    def test_inert_selector_reports_info(self):
        """A flag no item carries silently dropped a client requirement."""
        rule = self._rule(exact=2)
        ctx = _diag_ctx({'dessert': self._pool([0, 0, 0, 0, 0])},
                        slot_counts={'dessert': 1}, active=['dessert'])
        diags = rule.diagnose(ctx)
        assert [d.severity.value for d in diags] == ['info']
        assert 'inert' in diags[0].message

    def test_shortfall_reports_warning_not_error(self):
        """apply() caps the target, so this must not gate /plan with a 422."""
        rule = self._rule(exact=2)
        ctx = _diag_ctx({'dessert': self._pool([1, 0, 0, 0, 0])},
                        slot_counts={'dessert': 1}, active=['dessert'])
        diags = rule.diagnose(ctx)
        assert [d.severity.value for d in diags] == ['warning']
        assert diags[0].affected['achievable'] == 1
        assert diags[0].affected['target'] == 2

    def test_satisfiable_target_is_quiet(self):
        rule = self._rule(exact=2)
        ctx = _diag_ctx({'dessert': self._pool([1, 1, 1, 0, 0])},
                        slot_counts={'dessert': 1}, active=['dessert'])
        assert rule.diagnose(ctx) == []

    def test_max_only_rule_is_quiet(self):
        """max/daily_max only tighten; a thin pool makes them trivially met."""
        rule = self._rule(max=1)
        ctx = _diag_ctx({'dessert': self._pool([0, 0, 0])},
                        slot_counts={'dessert': 1}, active=['dessert'])
        assert rule.diagnose(ctx) == []


class TestSlotCompositionDiagnose:
    RULE = {
        'name': 'pair', 'type': 'slot_composition', 'base_slot': 'nonveg_main',
        'requires_slot_count': 2,
        'components': [
            {'selector': {'flag': 'is_egg_dish'}, 'count': 1},
            {'selector': {'primary_protein': 'chicken'}, 'count': 1},
        ],
    }

    def test_inactive_when_slot_count_differs(self):
        rule = SlotCompositionRule(dict(self.RULE))
        pool = pd.DataFrame({'item': ['a'], 'is_egg_dish': [1],
                             'primary_protein': ['egg']})
        ctx = _diag_ctx({'nonveg_main': pool},
                        slot_counts={'nonveg_main': 1},
                        active=['nonveg_main'])
        diags = rule.diagnose(ctx)
        assert [d.severity.value for d in diags] == ['info']
        assert 'inactive' in diags[0].message

    def test_missing_component_reports_the_days(self):
        rule = SlotCompositionRule(dict(self.RULE))
        # egg present, chicken absent -> the chicken half cannot be composed
        pool = pd.DataFrame({'item': ['e1', 'e2'], 'is_egg_dish': [1, 1],
                             'primary_protein': ['egg', 'egg']})
        ctx = _diag_ctx({'nonveg_main': pool},
                        slot_counts={'nonveg_main': 2},
                        active=['nonveg_main'])
        diags = rule.diagnose(ctx)
        assert [d.severity.value for d in diags] == ['warning']
        assert 'chicken' in diags[0].affected['component']
        assert len(diags[0].affected['days']) == 5

    def test_satisfiable_composition_is_quiet(self):
        rule = SlotCompositionRule(dict(self.RULE))
        pool = pd.DataFrame({'item': ['e1', 'c1'], 'is_egg_dish': [1, 0],
                             'primary_protein': ['egg', 'chicken']})
        ctx = _diag_ctx({'nonveg_main': pool},
                        slot_counts={'nonveg_main': 2},
                        active=['nonveg_main'])
        assert rule.diagnose(ctx) == []


class TestAttributeGroupingDiagnose:
    def _rule(self, **over):
        from src.menu_rules.attribute_grouping_rule import AttributeGroupingRule
        cfg = {'name': 'g', 'type': 'attribute_grouping', 'base_slot': 'sambar',
               'group_by': 'key_ingredient'}
        cfg.update(over)
        return AttributeGroupingRule(cfg)

    def test_missing_column_reports_info(self):
        rule = self._rule(max_per_group=1)
        ctx = _diag_ctx({'sambar': pd.DataFrame({'item': ['a', 'b']})},
                        slot_counts={'sambar': 1}, active=['sambar'])
        diags = rule.diagnose(ctx)
        assert [d.severity.value for d in diags] == ['info']
        assert 'key_ingredient' in diags[0].message

    def test_cap_capacity_shortfall_warns(self):
        """2 distinct values x max 1 each = 2 placements for a 5-day plan."""
        rule = self._rule(max_per_group=1)
        pool = pd.DataFrame({'item': ['a', 'b'],
                             'key_ingredient': ['drumstick', 'brinjal']})
        ctx = _diag_ctx({'sambar': pool}, slot_counts={'sambar': 1},
                        active=['sambar'])
        diags = rule.diagnose(ctx)
        assert [d.severity.value for d in diags] == ['warning']
        assert diags[0].affected['capacity'] == 2
        assert diags[0].affected['cells_needed'] == 5

    def test_enough_variety_is_quiet(self):
        rule = self._rule(max_per_group=1)
        pool = pd.DataFrame({
            'item': list('abcde'),
            'key_ingredient': ['a1', 'b1', 'c1', 'd1', 'e1'],
        })
        ctx = _diag_ctx({'sambar': pool}, slot_counts={'sambar': 1},
                        active=['sambar'])
        assert rule.diagnose(ctx) == []


# ---------------------------------------------------------------------------
# Theme-forced vs. frequency-cap conflict detection
# ---------------------------------------------------------------------------


class _ConflictCfg:
    rice_exclude_items = ()
    cuisine_col = 'cuisine_family'
    cuisine_south_value = 'south_indian'
    cuisine_north_value = 'north_indian'


class _ConflictClientCfg:
    def __init__(self, slot_counts):
        self.slot_counts = slot_counts


def _conflict_ctx(pools, dates, day_types, slot_counts=None, active=None):
    from src.menu_rules.base_menu_rule import DiagnoseContext
    return DiagnoseContext(
        pools=pools, dates=dates, day_types=day_types, cfg=_ConflictCfg(),
        df=None, banned_by_date={}, ricebread_ban_day={}, skip_cells=set(),
        client_cfg=_ConflictClientCfg(slot_counts or {}),
        active_base_slots=active if active is not None else list(pools),
    )


class TestForcedVersusMaxConflict:
    """A `max` rule the pool forces past is provably unsatisfiable.

    This is how Amadeus's Chinese counter failed: every weekday resolves to
    `continental`, the theme filter narrows `rice` to continental rice only, and
    `continental_rice_weekly` allows one such day.
    """

    def _rule(self, **extra):
        cfg = {'type': 'selector_frequency', 'name': 'cont_rice_weekly',
               'selector': {'flag': 'is_cont'}, 'base_slot': 'rice', 'max': 1}
        cfg.update(extra)
        return SelectorFrequencyRule(cfg)

    def test_errors_when_every_day_is_forced(self):
        pool = pd.DataFrame([
            {'item': 'cont_a', 'is_cont': 1},
            {'item': 'cont_b', 'is_cont': 1},
        ])
        dates = [MON + dt.timedelta(days=i) for i in range(3)]
        ctx = _conflict_ctx({'rice': pool}, dates, {d: 'continental' for d in dates})
        diags = self._rule().diagnose(ctx)
        errors = [d for d in diags if d.severity.value == 'error']
        assert errors, [d.message for d in diags]
        assert errors[0].affected['forced_days'] == 3
        assert errors[0].affected['limit'] == 1
        # The message has to name the fix, not just the failure.
        assert 'disable' in errors[0].suggestion

    def test_silent_when_the_pool_offers_alternatives(self):
        pool = pd.DataFrame([
            {'item': 'cont_a', 'is_cont': 1},
            {'item': 'indian_a', 'is_cont': 0},
        ])
        dates = [MON + dt.timedelta(days=i) for i in range(3)]
        ctx = _conflict_ctx({'rice': pool}, dates, {d: 'mix' for d in dates})
        assert not [d for d in self._rule().diagnose(ctx)
                    if d.severity.value == 'error']

    def test_max_equal_to_forced_is_not_an_error(self):
        pool = pd.DataFrame([{'item': 'cont_a', 'is_cont': 1}])
        dates = [MON]
        ctx = _conflict_ctx({'rice': pool}, dates, {MON: 'continental'})
        assert not [d for d in self._rule().diagnose(ctx)
                    if d.severity.value == 'error']


class TestCompositionForcesCap:
    """A composition mandating a selector forces it as hard as a thin pool."""

    def test_days_forced_by_composition_counts_theme_days(self):
        from src.menu_rules.slot_composition_rule import (
            days_forced_by_composition,
        )
        comp = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'pair',
            'base_slot': 'nonveg_main', 'min_slot_count': 2,
            'components': [{'selector': {'flag': 'is_dry'}, 'count': 1}],
            'components_by_theme': {
                'biryani': [{'selector': {'flag': 'is_biry'}, 'count': 1}],
            },
        })
        pool = pd.DataFrame([
            {'item': 'chicken_biryani', 'is_biry': 1, 'is_dry': 0},
            {'item': 'chicken_gravy', 'is_biry': 0, 'is_dry': 0},
            {'item': 'chicken_fry', 'is_biry': 0, 'is_dry': 1},
        ])
        dates = [MON + dt.timedelta(days=i) for i in range(3)]
        day_types = {dates[0]: 'biryani', dates[1]: 'mix', dates[2]: 'biryani'}
        ctx = _conflict_ctx({'nonveg_main': pool}, dates, day_types,
                        slot_counts={'nonveg_main': 3})
        forced = days_forced_by_composition(
            [comp], ctx, 'nonveg_main', lambda r: int(r.get('is_biry', 0)) == 1,
        )
        assert forced == 2, 'both biryani-theme days mandate a biryani'

    def test_inactive_composition_forces_nothing(self):
        from src.menu_rules.slot_composition_rule import (
            days_forced_by_composition,
        )
        comp = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'pair',
            'base_slot': 'nonveg_main', 'min_slot_count': 2,
            'components_by_theme': {
                'biryani': [{'selector': {'flag': 'is_biry'}, 'count': 1}],
            },
        })
        pool = pd.DataFrame([{'item': 'b', 'is_biry': 1}])
        ctx = _conflict_ctx({'nonveg_main': pool}, [MON], {MON: 'biryani'},
                        slot_counts={'nonveg_main': 1})   # below min_slot_count
        assert days_forced_by_composition(
            [comp], ctx, 'nonveg_main', lambda r: True) == 0


class TestCompositionSlotCountGate:
    """`requires_slot_count` is exact; `min_slot_count` is a range.

    The exact form silently excluded every counter serving more than the stated
    number, so a 3-dish non-veg counter got no composition at all.
    """

    def _rule(self, **gate):
        cfg = {'type': 'slot_composition', 'name': 'pair',
               'base_slot': 'nonveg_main',
               'components': [{'selector': {'flag': 'is_dry'}, 'count': 1}]}
        cfg.update(gate)
        return SlotCompositionRule(cfg)

    def test_min_slot_count_admits_more(self):
        r = self._rule(min_slot_count=2)
        assert r._gate_allows(2) and r._gate_allows(3) and r._gate_allows(5)
        assert not r._gate_allows(1)

    def test_requires_slot_count_stays_exact(self):
        r = self._rule(requires_slot_count=2)
        assert r._gate_allows(2)
        assert not r._gate_allows(3), 'exact gate must not widen silently'

    def test_no_gate_applies_everywhere(self):
        r = self._rule()
        assert r._gate_allows(1) and r._gate_allows(5)

    def test_both_gates_is_a_config_error(self):
        r = self._rule(min_slot_count=2, requires_slot_count=2)
        assert any('not both' in e for e in r.validation_errors())

    def test_shipped_ruleset_uses_the_range_form(self):
        """The base ruleset must not regress to the exact gate."""
        rules = MenuRuleLoader('data/configs/city_rules/bangalore.json').load_from_file()
        comps = [r for r in rules if isinstance(r, SlotCompositionRule)]
        assert comps, 'no slot_composition rules in the base ruleset'
        for r in comps:
            assert r.min_slot_count is not None, (
                f"{r.name} uses requires_slot_count; a counter serving more "
                f"than {r.requires_slot_count} would get no composition"
            )


class TestSlotCountCeiling:
    """A 5-dish non-veg counter must be configurable."""

    def test_five_is_accepted(self):
        from src.client.client_config import normalize_counter
        c = normalize_counter({
            'name': 'Non Veg', 'categories': ['nonveg_main'],
            'slot_counts': {'nonveg_main': 5},
        }, 0)
        assert c['slot_counts']['nonveg_main'] == 5

    def test_above_the_ceiling_still_clamps(self):
        from src.client.client_config import (
            normalize_counter, _MAX_SLOT_COUNT,
        )
        c = normalize_counter({
            'name': 'Non Veg', 'categories': ['nonveg_main'],
            'slot_counts': {'nonveg_main': 99},
        }, 0)
        assert c['slot_counts']['nonveg_main'] == _MAX_SLOT_COUNT

    def test_editor_bounds_match_the_loader(self):
        """The UI must not offer a value the loader would clamp."""
        import customisation.multi_slot_editor as ed
        from src.client.client_config import (
            _MAX_SLOT_COUNT, _MIN_SLOT_COUNT,
        )
        assert ed._MAX_SLOT_COUNT == _MAX_SLOT_COUNT
        assert ed._MIN_SLOT_COUNT == _MIN_SLOT_COUNT


class TestFiveDishNonvegStation:
    """A 5-dish non-veg station is expressible and does not collide with the
    2-dish pair (the pair is capped at 4 so exactly one composes a counter)."""

    def _comps(self):
        rules = MenuRuleLoader('data/configs/city_rules/bangalore.json').load_from_file()
        return {r.name: r for r in rules if isinstance(r, SlotCompositionRule)}

    def test_five_dish_rule_exists_with_the_expected_components(self):
        rule = self._comps()['nonveg_main_five_dish']
        assert rule.base_slot == 'nonveg_main'
        assert rule.min_slot_count == 5
        kinds = {m[0] for m, _c in rule.components}
        values = {str(m[1]) for m, _c in rule.components}
        assert 'flag' in kinds or 'any_flag' in kinds
        # biryani / gravy / dry / kebab / egg
        assert len(rule.components) == 5, rule.components
        assert any('biryani' in v for v in values), values
        assert any('egg' in v for v in values), values
        assert any('tandoor' in v for v in values), values

    def test_exactly_one_nonveg_composition_applies_per_slot_count(self):
        comps = self._comps()
        nonveg = [r for r in comps.values() if r.base_slot == 'nonveg_main']
        for count in range(1, 6):
            active = [r.name for r in nonveg if r._gate_allows(count)]
            assert len(active) <= 1, (
                f"{count} nonveg slots would be composed by {active}; two "
                f"compositions on one slot family can demand more dishes "
                f"than the counter has cells"
            )
        # And 2..5 each get exactly one.
        for count in (2, 3, 4, 5):
            assert len([r for r in nonveg if r._gate_allows(count)]) == 1, count

    def test_max_slot_count_bounds_the_pair(self):
        pair = self._comps()['nonveg_main_daily_pair']
        assert pair._gate_allows(4)
        assert not pair._gate_allows(5)

    def test_min_above_max_is_a_config_error(self):
        r = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'x', 'base_slot': 'rice',
            'min_slot_count': 4, 'max_slot_count': 2,
            'components': [{'selector': {'flag': 'f'}, 'count': 1}],
        })
        assert any('must be <=' in e for e in r.validation_errors())
