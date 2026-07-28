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

    def test_solver_forced_relaxation_via_cfg(self):
        """cfg.relax_unique_slots (the degraded retry) lifts a healthy slot."""
        m = cp_model.CpModel()
        cells = _build(m, 5, 'dessert', ['d1', 'd2', 'd3', 'd4', 'd5'])
        cfg = type('C', (), {'relax_unique_slots': {'dessert'}})()
        rule = UniqueItemsMenuRule({'name': 'u', 'type': 'unique_items'})
        rule.apply(m, {}, None, {
            'cells': cells, 'item_to_vars': _item_to_vars(cells), 'cfg': cfg})
        m.Add(cells[0].x_vars[0] == 1)
        m.Add(cells[1].x_vars[0] == 1)
        assert _status(m) in ('OPTIMAL', 'FEASIBLE')


# --------------------------------------------------------------------------
# nonveg biryani weekly cap auto-relax
# --------------------------------------------------------------------------

class TestNonvegBiryaniAutoRelax:
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

    def test_relaxes_when_every_day_forces_biryani(self):
        m = cp_model.CpModel()
        cells = self._cells(m, 5, all_biryani=True)
        rule = NonvegBiryaniWeeklyRule({
            'name': 'nb', 'type': 'nonveg_biryani_weekly', 'max_per_week': 1})
        with capture_logs('src.menu_rules.nonveg_rules') as msgs:
            rule.apply(m, {}, None, self._ctx(cells, 5))
        assert _status(m) in ('OPTIMAL', 'FEASIBLE')
        assert any('raised to 5' in msg for msg in msgs), msgs

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
