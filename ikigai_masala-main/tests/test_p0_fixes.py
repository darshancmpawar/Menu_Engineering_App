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
# Siemens Technology: typed non-veg constants on the Non Veg Lunch counter
# --------------------------------------------------------------------------

class TestSiemensTechNonvegConstants:
    """Non Veg Lunch, Wednesday only, ONE non-veg main, alternating weekly: Hyd
    Mutton Biryani one week and Fish Tikka Masala the next (neither in the
    Bangalore ontology, so stamped verbatim). Counter-scoped, so the client's
    two veg counters never inherit it."""

    def _spec(self):
        return MenuRuleLoader().get_client_constant_items(
            'Siemens Technology', 'Non Veg Lunch')['nonveg_main__1']

    def test_pin_is_wednesday_only_and_alternating(self):
        assert self._spec() == {
            'wed': ['Hyd Mutton Biryani', 'Fish Tikka Masala']}

    def test_alternates_by_iso_week_on_wednesday(self):
        from src.solver.menu_solver import _resolve_client_constant
        spec = self._spec()
        assert _resolve_client_constant(spec, 'wednesday', 32) == 'Hyd Mutton Biryani'
        assert _resolve_client_constant(spec, 'wednesday', 33) == 'Fish Tikka Masala'
        # only Wednesday carries a pin; other days are solved
        assert _resolve_client_constant(spec, 'monday', 32) is None

    def test_pins_are_counter_scoped(self):
        c = MenuRuleLoader().get_client_constant_items('Siemens Technology')
        assert 'nonveg_main__1' not in c


class TestConstantWeeklyAlternation:
    """The `_resolve_client_constant` list form (weekly alternation) in general."""

    def _r(self, spec, weekday, iso_week=None):
        from src.solver.menu_solver import _resolve_client_constant
        return _resolve_client_constant(spec, weekday, iso_week)

    def test_bare_list_alternates_every_day(self):
        assert self._r(['A', 'B'], 'monday', 10) == 'A'   # even
        assert self._r(['A', 'B'], 'monday', 11) == 'B'   # odd

    def test_string_and_weekday_map_still_work(self):
        assert self._r('Curd', 'monday', 10) == 'Curd'
        assert self._r({'friday': 'raita'}, 'friday', 10) == 'raita'
        assert self._r({'friday': 'raita'}, 'monday', 10) is None

    def test_empty_list_is_no_pin(self):
        assert self._r([], 'monday', 10) is None
        assert self._r({'wed': []}, 'wednesday', 10) is None


# --------------------------------------------------------------------------
# constant value validation
# --------------------------------------------------------------------------

class TestConstantValueValidation:
    """These captured `api.app` by name until `_validate_constant_values` moved to
    src/application/constant_items.py, at which point three failed loudly — and
    `test_known_value_is_quiet` started passing VACUOUSLY, because "no records
    from api.app" and "no warning was emitted" look identical to an
    `assert msgs == []`.

    So the logger is now taken from the module under test rather than written out,
    which cannot go stale if the code moves again, and the quiet case first proves
    the capture is wired up before asserting silence.
    """

    @pytest.fixture
    def df(self):
        return pd.DataFrame({'item': ['boiled_egg', 'green_salad']})

    @pytest.fixture
    def validate(self):
        """Logger taken from the module's own logger OBJECT, not from `__name__`.

        The name is deliberately pinned to `api.app` (src/log_names.py) so operator
        log filters survive refactors, so `__name__` would be wrong here — and
        hard-coding either string is what went stale last time.
        """
        from src.application import constant_items
        return constant_items._validate_constant_values, constant_items.logger.name

    def test_unknown_value_warns(self, df, validate):
        fn, logger_name = validate
        with capture_logs(logger_name) as msgs:
            fn('X', {'salad': 'nonexistent dish'}, df)
        assert any('nonexistent dish' in m for m in msgs), msgs

    def test_known_value_is_quiet(self, df, validate):
        """Silence for a real dish — but only meaningful if the capture works, so
        assert the positive case through the same channel first."""
        fn, logger_name = validate
        with capture_logs(logger_name) as msgs:
            fn('X', {'salad': 'nonexistent dish'}, df)
        assert msgs, 'capture is not wired to the emitting logger'

        with capture_logs(logger_name) as msgs:
            fn('X', {'salad': 'green salad'}, df)
        assert msgs == []

    def test_non_string_value_warns(self, df, validate):
        fn, logger_name = validate
        with capture_logs(logger_name) as msgs:
            fn('X', {'salad': 5}, df)
        assert any('not a string' in m for m in msgs), msgs

    def test_weekday_map_values_are_checked(self, df, validate):
        fn, logger_name = validate
        with capture_logs(logger_name) as msgs:
            fn('X', {'curd': {'monday': 'green salad', 'friday': 'bogus'}}, df)
        joined = ' '.join(msgs)
        assert 'bogus' in joined and 'green salad' not in joined

    def test_api_app_still_re_exports_it(self):
        """The route code calls it through api.app, so the name must stay there."""
        from api.app import _validate_constant_values
        from src.application.constant_items import (
            _validate_constant_values as moved)
        assert _validate_constant_values is moved


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


class TestAllowedDayTypes:
    """A themed dish belongs on its themed day.

    A `mix` day is not narrowed by the theme filter at all, so without this a
    counter served biryani on Monday and none on its actual biryani day.
    """

    def _rule(self):
        return SelectorFrequencyRule({
            'type': 'selector_frequency', 'name': 'biryani_on_biryani_days',
            'selector': {'flag': 'is_biry'}, 'base_slot': 'nonveg_main',
            'allowed_day_types': ['biryani'],
        })

    def test_parses_and_lowercases(self):
        assert self._rule().allowed_day_types == {'biryani'}

    def test_absent_means_unrestricted(self):
        r = SelectorFrequencyRule({
            'type': 'selector_frequency', 'name': 'x',
            'selector': {'flag': 'is_biry'}, 'max': 1,
        })
        assert r.allowed_day_types is None

    def test_ban_is_skipped_when_it_would_empty_a_cell(self):
        """A slot whose whole pool matches must stay fillable."""
        rule = self._rule()

        class _Cell:
            def __init__(self, rows):
                self.cand_rows = rows

        all_match = _Cell([{'item': 'a', 'is_biry': 1}])
        assert not rule._ban_leaves_every_cell_fillable([all_match])
        has_alt = _Cell([{'item': 'a', 'is_biry': 1}, {'item': 'b', 'is_biry': 0}])
        assert rule._ban_leaves_every_cell_fillable([has_alt])

    def test_shipped_rule_restricts_biryani_to_biryani_days(self):
        rules = MenuRuleLoader('data/configs/city_rules/bangalore.json').load_from_file()
        rule = next(r for r in rules if r.name == 'nonveg_biryani_one_per_day')
        assert rule.allowed_day_types == {'biryani'}
        assert rule.daily_max == 1


class TestHorizonLimitedComponent:
    """A component needing more distinct items than the pool holds must relax to
    the achievable count, not mandate the impossible.

    L&T's 5-dish station has a kebab candidate every day but only ONE distinct
    kebab in its pool, so "a kebab daily" over five days is unsatisfiable under
    unique_items however the solver picks.
    """

    def _rule(self):
        return SlotCompositionRule({
            'type': 'slot_composition', 'name': 'five',
            'base_slot': 'nonveg_main', 'min_slot_count': 2,
            'components': [
                {'selector': {'flag': 'is_biry'}, 'count': 1},
                {'selector': {'flag': 'is_kebab'}, 'count': 1},
            ],
        })

    def _cells(self, n_days):
        """One cell per day, each offering 3 biryanis and the single kebab."""
        class _Cell:
            def __init__(self, di, rows):
                self.d_idx, self.base_slot = di, 'nonveg_main'
                self.cand_rows = rows
                self.x_vars = [None] * len(rows)

        out = []
        for di in range(n_days):
            rows = [
                {'item': f'biryani_{di}_{k}', 'is_biry': 1, 'is_kebab': 0}
                for k in range(3)
            ] + [{'item': 'the_only_kebab', 'is_biry': 0, 'is_kebab': 1}]
            out.append(_Cell(di, rows))
        return out

    def test_scarce_component_is_flagged_as_horizon_limited(self):
        rule = self._rule()
        cells = self._cells(5)
        dates = [MON + dt.timedelta(days=i) for i in range(5)]

        class _Cfg:
            slot_counts = {'nonveg_main': 5}

        limited = rule._horizon_limited_components(
            cells, dates, [''] * 5, {'cfg': _Cfg()},
        )
        keys = {k[1] for k in limited}
        assert 'is_kebab' in keys, limited
        assert 'is_biry' not in keys, 'plenty of distinct biryanis exist'
        entry = next(v for k, v in limited.items() if k[1] == 'is_kebab')
        assert entry['distinct'] == 1
        assert entry['need'] == 5

    def test_plentiful_component_is_not_limited(self):
        rule = self._rule()
        cells = self._cells(2)
        dates = [MON, MON + dt.timedelta(days=1)]

        class _Cfg:
            slot_counts = {'nonveg_main': 5}

        limited = rule._horizon_limited_components(
            cells, dates, [''] * 2, {'cfg': _Cfg()},
        )
        assert 'is_biry' not in {k[1] for k in limited}


class TestPinnedDishGoesThroughTheSolver:
    """A pin naming a real dish is solved; one that names an unknown dish is
    printed verbatim. Adding the dish to the ontology switches it over with no
    config change."""

    def test_canonical_name_matches_spaces_and_underscores(self):
        import api.app as api_app
        known = frozenset({'boiled_egg', 'plain_curd'})
        assert api_app._canonical_item_name('Boiled Egg', known) == 'boiled_egg'
        assert api_app._canonical_item_name('boiled_egg', known) == 'boiled_egg'
        assert api_app._canonical_item_name('Mutton Biryani', known) is None
        assert api_app._canonical_item_name('', known) is None
        assert api_app._canonical_item_name(None, known) is None
        assert api_app._canonical_item_name(5, known) is None

    def test_solver_config_carries_forced_items(self):
        from src.solver.menu_solver import SolverConfig
        cfg = SolverConfig(days=1, start_date=MON)
        assert cfg.forced_items is None, 'default must not force anything'


class TestStapleItemsRecurDaily:
    """A staple is the same dish every day, like steamed rice.

    The chicken kebab on a non-veg station is one: only one kebab is eligible for
    a common-only client, so treating it as an ordinary variety dish made "a
    kebab daily" need five distinct ones and the counter unsatisfiable. The 20-day
    no-repeat window governs ordinary dishes, not staples.
    """

    def test_kebab_is_a_staple_in_the_nonveg_slot(self):
        from src.constants import repeatable_row
        kebab = {'item': 'tandoori_murgh_lababdar', 'is_tandoor': 1}
        assert repeatable_row(kebab, 'nonveg_main')

    def test_ordinary_nonveg_is_not_a_staple(self):
        from src.constants import repeatable_row
        assert not repeatable_row({'item': 'murgh_korma'}, 'nonveg_main')

    def test_tandoor_bread_is_not_a_staple_in_the_bread_slot(self):
        """The flags are keyed by slot for this reason.

        ``is_tandoor`` also marks tandoor breads and veg kebabs; a flat flag list
        would have let butter naan repeat all week in the bread slot and skip its
        cooldown.
        """
        from src.constants import repeatable_row
        naan = {'item': 'butter_naan', 'is_tandoor': 1}
        assert not repeatable_row(naan, 'bread')
        assert not repeatable_row(naan, 'rice')

    def test_plain_curd_stays_a_staple_by_name(self):
        from src.constants import repeatable_row
        assert repeatable_row({'item': 'curd'}, 'curd')
        assert repeatable_row({'item': 'curd'}, None)

    def test_a_slot_holding_a_staple_is_never_starved(self):
        """`starved_slots` must not relax uniqueness for a slot a staple can
        fill on its own — the staple already covers every cell."""
        class _Cell:
            def __init__(self, rows, slot='nonveg_main'):
                self.base_slot = slot
                self.cand_rows = rows

        one_staple = [
            _Cell([{'item': 'tandoori_murgh_lababdar', 'is_tandoor': 1}])
            for _ in range(5)
        ]
        assert starved_slots(one_staple) == {}
        # Without the staple flag the same shape IS starved.
        one_plain = [_Cell([{'item': 'murgh_korma'}]) for _ in range(5)]
        assert 'nonveg_main' in starved_slots(one_plain)

    def test_cooldown_never_bans_a_staple(self):
        import datetime as _dt
        from src.menu_rules.cooldown_rules import ItemCooldownMenuRule
        rule = ItemCooldownMenuRule({'type': 'item_cooldown',
                                     'name': 'cd', 'cooldown_days': 20})
        pool = pd.DataFrame([
            {'item': 'tandoori_murgh_lababdar', 'is_tandoor': 1},
            {'item': 'murgh_korma', 'is_tandoor': 0},
        ])
        day = _dt.date(2026, 8, 3)
        ctx = {'banned_by_date': {day: {'tandoori_murgh_lababdar', 'murgh_korma'}}}
        kept = rule.pre_filter_pool(pool, day, 'nonveg_main', 'mix', ctx)
        assert list(kept['item']) == ['tandoori_murgh_lababdar'], list(kept['item'])

    def test_cooldown_still_bans_a_tandoor_bread(self):
        """Slot scoping again: the same flag must not exempt a bread."""
        import datetime as _dt
        from src.menu_rules.cooldown_rules import ItemCooldownMenuRule
        rule = ItemCooldownMenuRule({'type': 'item_cooldown',
                                     'name': 'cd', 'cooldown_days': 20})
        pool = pd.DataFrame([
            {'item': 'butter_naan', 'is_tandoor': 1},
            {'item': 'jeera_chapatti', 'is_tandoor': 0},
        ])
        day = _dt.date(2026, 8, 3)
        ctx = {'banned_by_date': {day: {'butter_naan'}}}
        kept = rule.pre_filter_pool(pool, day, 'bread', 'mix', ctx)
        assert list(kept['item']) == ['jeera_chapatti'], list(kept['item'])

    def test_composition_does_not_relax_a_staple_component(self):
        """One kebab covering five days is not a shortfall — it is a staple."""
        rule = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'five',
            'base_slot': 'nonveg_main', 'min_slot_count': 2,
            'components': [{'selector': {'flag': 'is_tandoor'}, 'count': 1}],
        })

        class _Cell:
            def __init__(self, di, rows):
                self.d_idx, self.base_slot = di, 'nonveg_main'
                self.cand_rows = rows
                self.x_vars = [None] * len(rows)

        cells = [
            _Cell(di, [{'item': 'the_only_kebab', 'is_tandoor': 1}])
            for di in range(5)
        ]

        class _Cfg:
            slot_counts = {'nonveg_main': 5}

        limited = rule._horizon_limited_components(
            cells, [MON + dt.timedelta(days=i) for i in range(5)],
            [''] * 5, {'cfg': _Cfg()},
        )
        assert limited == {}, limited


class TestWholeHorizonPinStaysStamped:
    """A pin replacing a slot for the whole horizon must still be stamped.

    Routing an in-ontology pin through the solver is right for a per-day pin, but
    a whole-horizon pin has its base slot dropped from the model
    (`whole_slot_bases`), so there is no cell to narrow — and solving one anyway
    would be INFEASIBLE under unique_items, since the same dish cannot occupy
    five days unless it is a staple. Six counters shipped a blank salad /
    curd_side / healthy_rice row before this guard.
    """

    def _skips(self, monkeypatch, constants, active_slots, dates):
        import api.app as api_app
        monkeypatch.setattr('api.app._get_menu_rules_for_city', lambda city: [])
        monkeypatch.setattr(
            'src.menu_rules.MenuRuleLoader.load_for_client',
            lambda self, name, generic, counter_name=None: [],
        )
        monkeypatch.setattr(
            'src.menu_rules.MenuRuleLoader.get_client_constant_items',
            lambda self, name, counter_name=None: constants,
        )

        class _Cfg:
            def __init__(self, slots):
                self.name = 'T'
                self.counter_name = 'Counter 1'
                self.active_slots = list(slots)
                self.slot_counts = {}
                self.theme_map = {}

        _r, skips, _resolved, whole, forced = (
            api_app._rules_and_skip_for_client(
                'Booking.com', dates, city='bangalore',
                client_cfg=_Cfg(active_slots),
            )
        )
        return skips, whole, forced

    def test_daily_string_pin_is_stamped_not_solved(self, monkeypatch):
        dates = [MON + dt.timedelta(days=i) for i in range(5)]
        skips, whole, forced = self._skips(
            monkeypatch, {'salad': 'green salad'}, ['rice', 'salad'], dates,
        )
        assert 'salad' in whole, 'a daily string replaces the slot outright'
        assert not any(slot == 'salad' for _d, slot in forced), forced
        for d in dates:
            assert (d, 'salad') in skips, d

    def test_per_day_pin_of_a_real_dish_is_solved(self, monkeypatch):
        """The per-day case is the one that should reach the solver."""
        dates = [MON + dt.timedelta(days=i) for i in range(5)]
        wed = dates[2]
        skips, whole, forced = self._skips(
            monkeypatch, {'salad': {'wednesday': 'green salad'}},
            ['rice', 'salad'], dates,
        )
        assert 'salad' not in whole, 'a weekday map does not replace the slot'
        assert (wed, 'salad') in forced, forced
        assert (wed, 'salad') not in skips


class TestWeekdayKeyedComposition:
    """A dish family pinned to a named weekday, not to a theme.

    Six clients state requirements no theme expresses. Infenion's non-veg row is
    the clearest: "Monday chicken gravy, Wednesday egg, Friday biryani, other days
    blank" — and its sample menu serves exactly that.
    """

    def _infenion(self):
        return SlotCompositionRule({
            'type': 'slot_composition', 'name': 'infenion_nonveg_by_weekday',
            'base_slot': 'nonveg_main', 'min_slot_count': 1,
            'components_by_weekday': {
                'mon': [{'selector': {'any_flag': ['is_north_chicken_gravy',
                                                   'is_south_chicken_gravy']},
                         'count': 1}],
                'tue': [],
                'wed': [{'selector': {'flag': 'is_egg_dish'}, 'count': 1}],
                'thu': [],
                'fri': [{'selector': {'flag': 'is_nonveg_biryani'}, 'count': 1}],
            },
        })

    def test_each_weekday_gets_its_own_family(self):
        r = self._infenion()
        assert r.validate_config(), r.validation_errors()
        got = [
            [m[0] for m, _c in r._components_for(MON + dt.timedelta(days=i), 'mix')]
            for i in range(5)
        ]
        assert got == [['any_flag'], [], ['flag'], [], ['flag']], got

    def test_empty_weekday_list_composes_nothing(self):
        """"other days blank" — an empty list is a real instruction, not absence."""
        r = self._infenion()
        tue = MON + dt.timedelta(days=1)
        assert r._components_for(tue, 'biryani') == [], (
            'a weekday configured empty must not fall through to the theme map'
        )

    def test_weekday_outranks_theme_and_theme_outranks_default(self):
        r = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'x', 'base_slot': 'nonveg_main',
            'components': [{'selector': {'flag': 'is_default'}, 'count': 1}],
            'components_by_theme': {
                'biryani': [{'selector': {'flag': 'is_theme'}, 'count': 1}]},
            'components_by_weekday': {
                'friday': [{'selector': {'flag': 'is_weekday'}, 'count': 1}]},
        })
        fri, wed = MON + dt.timedelta(days=4), MON + dt.timedelta(days=2)
        assert r._components_for(fri, 'biryani')[0][0][1] == 'is_weekday'
        assert r._components_for(wed, 'biryani')[0][0][1] == 'is_theme'
        assert r._components_for(wed, 'mix')[0][0][1] == 'is_default'

    def test_accepts_short_and_long_weekday_tokens(self):
        for token in ('fri', 'friday', 'FRIDAY', ' Fri '):
            r = SlotCompositionRule({
                'type': 'slot_composition', 'name': 'x',
                'base_slot': 'nonveg_main',
                'components_by_weekday': {
                    token: [{'selector': {'flag': 'f'}, 'count': 1}]},
            })
            assert r.validate_config(), (token, r.validation_errors())
            assert 4 in r.components_by_weekday, token

    def test_unrecognised_weekday_is_a_config_error(self):
        r = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'x', 'base_slot': 'nonveg_main',
            'components': [{'selector': {'flag': 'f'}, 'count': 1}],
            'components_by_weekday': {
                'funday': [{'selector': {'flag': 'f'}, 'count': 1}]},
        })
        assert not r.validate_config()
        assert any('funday' in e for e in r.validation_errors())

    def test_bad_selector_under_a_weekday_is_not_silent(self):
        r = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'x', 'base_slot': 'nonveg_main',
            'components_by_weekday': {
                'mon': [{'selector': {'nonsense_key': 'v'}, 'count': 1}]},
        })
        assert not r.validate_config(), r.validation_errors()

    def test_no_weekday_config_is_unchanged(self):
        """Existing rules must behave exactly as before."""
        r = SlotCompositionRule({
            'type': 'slot_composition', 'name': 'pair',
            'base_slot': 'nonveg_main', 'min_slot_count': 2,
            'components': [{'selector': {'flag': 'is_dry'}, 'count': 1}],
            'components_by_theme': {
                'biryani': [{'selector': {'flag': 'is_biry'}, 'count': 1}]},
        })
        assert r.components_by_weekday == {}
        for i in range(5):
            d = MON + dt.timedelta(days=i)
            assert r._components_for(d, 'mix')[0][0][1] == 'is_dry'
            assert r._components_for(d, 'biryani')[0][0][1] == 'is_biry'


class TestComponentExclude:
    """A component may exclude a selector, because the flags are not clean.

    `egg_drumstick_curry` and `egg_kurma` carry `is_south_chicken_gravy` despite
    being egg dishes, so "a chicken gravy on Monday" was satisfied by an egg
    curry. Excluding `is_egg_dish` states the intent without a data fix.
    """

    def _rule(self, exclude=None):
        comp = {'selector': {'any_flag': ['is_north_chicken_gravy',
                                          'is_south_chicken_gravy']},
                'count': 1}
        if exclude:
            comp['exclude'] = exclude
        return SlotCompositionRule({
            'type': 'slot_composition', 'name': 'x',
            'base_slot': 'nonveg_main', 'components': [comp],
        })

    EGG_GRAVY = {'item': 'egg_drumstick_curry', 'is_south_chicken_gravy': 1,
                 'is_egg_dish': 1}
    CHICKEN_GRAVY = {'item': 'goan_chicken_curry', 'is_south_chicken_gravy': 1,
                     'is_egg_dish': 0}

    def test_without_exclude_the_egg_dish_matches(self):
        from src.menu_rules.slot_composition_rule import _component_matches
        matcher = self._rule().components[0][0]
        assert _component_matches(self.EGG_GRAVY, matcher)

    def test_exclude_rejects_the_egg_dish_and_keeps_the_chicken(self):
        from src.menu_rules.slot_composition_rule import _component_matches
        matcher = self._rule(exclude={'flag': 'is_egg_dish'}).components[0][0]
        assert not _component_matches(self.EGG_GRAVY, matcher)
        assert _component_matches(self.CHICKEN_GRAVY, matcher)

    def test_bad_exclude_selector_is_a_config_error(self):
        r = self._rule(exclude={'nonsense_key': 'v'})
        assert not r.validate_config(), r.validation_errors()

    def test_excluded_component_still_has_a_stable_key(self):
        """The horizon-limit bookkeeping keys components by matcher."""
        from src.menu_rules.slot_composition_rule import _matcher_key
        a = self._rule(exclude={'flag': 'is_egg_dish'}).components[0][0]
        b = self._rule(exclude={'flag': 'is_egg_dish'}).components[0][0]
        plain = self._rule().components[0][0]
        assert _matcher_key(a) == _matcher_key(b)
        assert _matcher_key(a) != _matcher_key(plain)


class TestInfenionMatchesItsSample:
    """The shipped Infenion config must encode its sample's weekday pattern."""

    def _rule(self):
        rules = MenuRuleLoader().load_for_client(
            'Infenion', MenuRuleLoader().load_for_city('bangalore'), 'Counter 1')
        return next(r for r in rules if r.name == 'infenion_nonveg_by_weekday')

    def test_weekday_pattern_is_configured(self):
        r = self._rule()
        assert r.validate_config(), r.validation_errors()
        shape = {
            i: [m[0] for m, _c in r.components_by_weekday[i]]
            for i in sorted(r.components_by_weekday)
        }
        assert shape == {
            0: ['_and_not'],   # Mon chicken gravy, excluding egg
            1: [],             # Tue blank
            2: ['flag'],       # Wed egg
            3: [],             # Thu blank
            4: ['flag'],       # Fri biryani
        }, shape

    def test_non_veg_is_restricted_to_three_days(self):
        rules = MenuRuleLoader().load_for_client(
            'Infenion', MenuRuleLoader().load_for_city('bangalore'), 'Counter 1')
        r = next(r for r in rules if r.name == 'infenion_nonveg_mon_wed_fri')
        assert r.allowed_weekdays == {0, 2, 4}, r.allowed_weekdays


class TestWeekdayClientsAreWired:
    """The five clients whose samples specify a weekday non-veg pattern.

    Config-shape assertions only — the generated-menu check lives in the slow
    sweep. These fail fast if a rule is renamed, dropped, or loses its weekdays.
    """

    def _rules(self, client, counter='Counter 1'):
        loader = MenuRuleLoader()
        return {
            r.name: r for r in loader.load_for_client(
                client, loader.load_for_city('bangalore'), counter)
        }

    @pytest.mark.parametrize('client,rule_name,expected', [
        # weekday index -> number of components mandated that day
        ('Infenion', 'infenion_nonveg_by_weekday', {0: 1, 1: 0, 2: 1, 3: 0, 4: 1}),
        ('Thales', 'thales_nonveg_by_weekday', {0: 1, 1: 1, 2: 1, 3: 1, 4: 1}),
        ('Konsberg', 'konsberg_nonveg_by_weekday', {0: 1, 1: 1, 2: 1, 4: 1}),
        ('Cloudera', 'cloudera_nonveg_by_weekday', {0: 1}),
        ('Sinch', 'sinch_nonveg_by_weekday', {2: 1}),
        ('Plum', 'plum_nonveg_by_weekday', {4: 1}),
    ])
    def test_weekday_pattern_is_configured(self, client, rule_name, expected):
        rules = self._rules(client)
        assert rule_name in rules, sorted(rules)
        r = rules[rule_name]
        assert r.validate_config(), r.validation_errors()
        got = {k: len(v) for k, v in r.components_by_weekday.items()}
        assert got == expected, got

    def test_kongsberg_leaves_thursday_to_its_chinese_theme(self):
        """Thursday is configured as a chinese theme day, not pinned by weekday."""
        r = self._rules('Konsberg')['konsberg_nonveg_by_weekday']
        assert 3 not in r.components_by_weekday
        thu = MON + dt.timedelta(days=3)
        # Falls through to the theme map rather than composing nothing.
        assert r._components_for(thu, 'chinese') is r.components_by_theme.get(
            'chinese', r.components)

    def test_thales_has_exactly_three_egg_days(self):
        r = self._rules('Thales')['thales_nonveg_by_weekday']
        egg_days = [
            i for i, comps in r.components_by_weekday.items()
            if any(m == ('flag', 'is_egg_dish') for m, _c in comps)
        ]
        assert sorted(egg_days) == [0, 1, 3], egg_days


class TestResolvedSampleConflicts:
    """The three sample-vs-rulebook conflicts, as decided by the client."""

    def _entry(self, client):
        import json
        return json.load(open('data/configs/client_rules.json'))[client]

    def test_astrazeneca_serves_curd_not_raita(self):
        e = self._entry('Astrazeneca')
        assert e['constant_items']['curd_side'] == 'Curd'
        assert 'curd_raita_logic' in e['disable'], (
            'the city curd/raita split must be off, or it would put raita on '
            'the biryani day'
        )

    def test_astrazeneca_bread_is_plain_chapati_daily(self):
        assert self._entry('Astrazeneca')['constant_items']['bread'] == \
            'plain chapati'

    def test_cloudera_keeps_curd_rice_daily(self):
        assert self._entry('Cloudera')['constant_items']['healthy_rice'] == \
            'curd rice'


class TestFiveDishRolesAreDistinct:
    """The 5-dish station's components must land on five DISTINCT dishes.

    Components are `>=` bounds, so one dish satisfying two of them frees a cell
    for a duplicate. The kebab (`tandoori_murgh_lababdar`) also carries
    `is_nonveg_gravy`, and egg curries carry it too, so L&T's station came back
    with two eggs and no chicken gravy. The gravy and dry components exclude both
    egg and the tandoor flags so each covers one role only.
    """

    def _rule(self):
        rules = MenuRuleLoader('data/configs/city_rules/bangalore.json').load_from_file()
        return next(r for r in rules if r.name == 'nonveg_main_five_dish')

    def test_five_components(self):
        assert len(self._rule().components) == 5

    def test_gravy_and_dry_exclude_egg_and_kebab(self):
        from src.menu_rules.slot_composition_rule import _component_matches
        comps = {}
        for matcher, _c in self._rule().components:
            kind, val = matcher
            inc = val[0] if kind == '_and_not' else matcher
            comps[str(inc[1])] = matcher

        kebab = {'item': 'tandoori_murgh_lababdar', 'is_tandoor': 1,
                 'is_nonveg_gravy': 1, 'is_egg_dish': 0}
        egg_gravy = {'item': 'anda_mirch_masala', 'is_egg_dish': 1,
                     'is_nonveg_gravy': 1, 'is_tandoor': 0}
        chicken_gravy = {'item': 'murgh_korma', 'is_nonveg_gravy': 1,
                         'is_egg_dish': 0, 'is_tandoor': 0}

        gravy = comps['is_nonveg_gravy']
        assert not _component_matches(kebab, gravy), 'kebab must not fill gravy'
        assert not _component_matches(egg_gravy, gravy), 'egg must not fill gravy'
        assert _component_matches(chicken_gravy, gravy)

    def test_egg_component_still_accepts_egg(self):
        from src.menu_rules.slot_composition_rule import _component_matches
        egg_matcher = next(
            m for m, _c in self._rule().components
            if m[0] == 'flag' and m[1] == 'is_egg_dish')
        assert _component_matches({'item': 'anda_tarriwala', 'is_egg_dish': 1},
                                  egg_matcher)

    def test_every_component_covers_a_distinct_role(self):
        """No two components may be satisfiable by the same single dish."""
        from src.menu_rules.slot_composition_rule import _component_matches
        matchers = [m for m, _c in self._rule().components]
        kebab = {'item': 'k', 'is_tandoor': 1, 'is_nonveg_gravy': 1,
                 'is_nonveg_dry': 1, 'is_egg_dish': 0, 'is_nonveg_biryani': 0}
        hits = [i for i, m in enumerate(matchers) if _component_matches(kebab, m)]
        assert len(hits) == 1, (
            f'the kebab satisfies {len(hits)} components; it must satisfy only '
            f'its own or it frees a cell for a duplicate dish'
        )


class TestFixedDailyItem:
    """One slot's dish is the SAME every day (L&T's egg, like its kebab).

    Exempting egg from `unique_items` only *permits* a repeat; with 21 eligible
    egg dishes the solver would still serve five different ones. This rule makes
    it deliberate, and declares its items repeatable so uniqueness does not
    forbid the repetition it creates.
    """

    def _rule(self, **extra):
        from src.menu_rules.fixed_daily_item_rule import FixedDailyItemRule
        cfg = {'type': 'fixed_daily_item', 'name': 'egg_fixed',
               'base_slot': 'nonveg_main', 'selector': {'flag': 'is_egg_dish'}}
        cfg.update(extra)
        return FixedDailyItemRule(cfg)

    def test_declares_its_items_repeatable(self):
        decl = self._rule().repeatable_item_flags()
        assert 'nonveg_main' in decl
        include, exclude = decl['nonveg_main']
        assert include == ('flag', 'is_egg_dish')
        assert exclude is None

    def test_requires_slot_and_selector(self):
        from src.menu_rules.fixed_daily_item_rule import FixedDailyItemRule
        bad = FixedDailyItemRule({'type': 'fixed_daily_item', 'name': 'x'})
        errs = bad.validation_errors()
        assert any('base_slot' in e for e in errs)
        assert any('selector' in e for e in errs)
        assert bad.repeatable_item_flags() == {}

    def test_forces_one_item_across_all_days(self):
        """Two eggs available on all days -> the same one must fill every day."""
        m = cp_model.CpModel()
        cells = _build(m, 3, 'nonveg_main', ['egg_a', 'egg_b'])
        for c in cells:
            for r in c.cand_rows:
                r['is_egg_dish'] = 1
        rule = self._rule()
        rule.apply(m, {}, None, {'cells': cells,
                                 'dates': [MON + dt.timedelta(days=i) for i in range(3)]})
        # Force day 0 to egg_a and day 1 to egg_b -> must be rejected.
        m.Add(cells[0].x_vars[0] == 1)
        m.Add(cells[1].x_vars[1] == 1)
        assert _status(m) == 'INFEASIBLE'

    def test_a_consistent_choice_is_feasible(self):
        m = cp_model.CpModel()
        cells = _build(m, 3, 'nonveg_main', ['egg_a', 'egg_b'])
        for c in cells:
            for r in c.cand_rows:
                r['is_egg_dish'] = 1
        rule = self._rule()
        rule.apply(m, {}, None, {'cells': cells,
                                 'dates': [MON + dt.timedelta(days=i) for i in range(3)]})
        for c in cells:
            m.Add(c.x_vars[0] == 1)          # egg_a everywhere
        assert _status(m) in ('OPTIMAL', 'FEASIBLE')

    def test_non_matching_items_are_untouched(self):
        """A rule on egg must not constrain the chicken dishes."""
        m = cp_model.CpModel()
        cells = _build(m, 2, 'nonveg_main', ['chicken_a', 'chicken_b'])
        for c in cells:
            for r in c.cand_rows:
                r['is_egg_dish'] = 0
        self._rule().apply(m, {}, None, {
            'cells': cells, 'dates': [MON, MON + dt.timedelta(days=1)]})
        m.Add(cells[0].x_vars[0] == 1)
        m.Add(cells[1].x_vars[1] == 1)       # different chicken each day
        assert _status(m) in ('OPTIMAL', 'FEASIBLE')

    def test_item_missing_on_some_day_is_excluded_not_infeasible(self):
        """An item that cannot appear every day is dropped, not fatal."""
        m = cp_model.CpModel()
        cells = _build(m, 2, 'nonveg_main', ['egg_a', 'egg_b'])
        for c in cells:
            for r in c.cand_rows:
                r['is_egg_dish'] = 1
        # Remove egg_b from day 1 entirely.
        cells[1].cand_rows = cells[1].cand_rows[:1]
        cells[1].x_vars = cells[1].x_vars[:1]
        self._rule().apply(m, {}, None, {
            'cells': cells, 'dates': [MON, MON + dt.timedelta(days=1)]})
        assert _status(m) in ('OPTIMAL', 'FEASIBLE')

    def test_lt_egg_rule_is_configured_on_the_right_counter(self):
        from src.menu_rules.fixed_daily_item_rule import FixedDailyItemRule
        loader = MenuRuleLoader()
        city = loader.load_for_city('bangalore')
        nonveg = loader.load_for_client('L&T', city, 'Non Veg Lunch')
        assert any(isinstance(r, FixedDailyItemRule) for r in nonveg), \
            'L&T Non Veg Lunch should hold the fixed-egg rule'
        # And it must NOT leak to the client's other counters.
        south = loader.load_for_client('L&T', city, 'South Lunch')
        assert not any(isinstance(r, FixedDailyItemRule) for r in south)


# --------------------------------------------------------------------------
# cross-counter shared categories: _merge_shared_items (pure)
# --------------------------------------------------------------------------

class TestMergeSharedItems:
    """`shared_items` from the planner fold into forced_items as (date, slot_id)
    pins, lowercased, without overriding an explicit client constant."""

    def _fn(self):
        flask = pytest.importorskip("flask")  # noqa: F841
        from api.app import _merge_shared_items
        return _merge_shared_items

    DATES = [dt.date(2026, 8, 3), dt.date(2026, 8, 4)]

    def test_entries_become_forced_pins_lowercased(self):
        out = self._fn()({}, [["2026-08-03", "rice", "Masala_Khuska"]], self.DATES)
        assert out == {(dt.date(2026, 8, 3), "rice"): "masala_khuska"}

    def test_out_of_horizon_date_is_dropped(self):
        out = self._fn()({}, [["2026-08-31", "rice", "x"]], self.DATES)
        assert out == {}

    def test_explicit_pin_wins_over_shared(self):
        forced = {(dt.date(2026, 8, 3), "rice"): "biryani_pin"}
        out = self._fn()(forced, [["2026-08-03", "rice", "other"]], self.DATES)
        assert out[(dt.date(2026, 8, 3), "rice")] == "biryani_pin"

    def test_malformed_entries_are_skipped_not_raised(self):
        bad = [None, [], ["2026-08-03"], ["2026-08-03", "rice"],
               ["2026-08-03", "", "x"], ["2026-08-03", "rice", ""]]
        assert self._fn()({}, bad, self.DATES) == {}

    def test_none_shared_items_is_a_noop(self):
        forced = {(dt.date(2026, 8, 3), "rice"): "x"}
        assert self._fn()(forced, None, self.DATES) == forced
