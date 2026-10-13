"""The pinned set can be computed WITHOUT a solve, and it is the same set.

`pinned_cells_for_horizon` was lifted out of `_rows_to_week_plan`, which built
it while it stamped. `/pick` and `/regenerate` have to refuse a pinned cell
before there is any plan to read, so the walk had to be callable on config
alone — decision D3, which until now lived only in the table markup.

**The work order asks for a byte-identical `/plan` as the gate for this
extraction, and that gate cannot be met by anything.** This solver does not
reproduce its own output: the same client, the same date, the same config and
the same seed solved twice differ in ~40% of cells (measured during the
pairing work, `num_workers=1` no better than 4). A `/plan` diff would fail on
an unmodified checkout. So the invariant is checked directly instead, which is
the stronger test anyway: the function's answer, from config, equals what the
SOLVE produced.

The one thing the stamping loop knew that the function does not is which slots
the solver actually built cells for, which it used for the `s in day_out` test
on the forced-items line. The function recovers it as "expanded and not
skipped". `test_every_expanded_slot_gets_a_cell` pins that reading against
real solves rather than against my reading of `_build_cells`, because if it is
ever wrong the consequence is a pin silently dropping out of the set and a
staple cell becoming editable.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.constants import CONSTANT_ITEMS
from src.solver._helpers import cell_is_skipped
from src.solver.menu_solver import (
    MenuSolver, _resolve_client_constant, pinned_cells_for_horizon,
)

#: Clients chosen for what they exercise, not for coverage: a plain counter, a
#: client with `constant_items`, and one with a per-weekday pin. Named here so
#: a fixture change that drops one is visible.
CLIENTS = ['Rippling', 'Zscaler', 'Booking.com']
MONDAY = '2026-11-02'
DAYS = 5


@pytest.fixture
def solved(fake_supabase):
    """Run a real solve and keep the solver object and the cells it built."""
    from tests.client_fixtures import CLIENTS as FIXTURE_CLIENTS

    captured = {}
    original = MenuSolver._build_cells

    def _spy(self, dates, expanded_slots, *a, **kw):
        cells = original(self, dates, expanded_slots, *a, **kw)
        captured.setdefault('cells', cells)
        captured.setdefault('expanded_slots', list(expanded_slots))
        captured.setdefault('dates', list(dates))
        captured.setdefault('solver', self)
        return cells

    def _run(client):
        import api.app as app
        fake_supabase.seed('clients', [dict(next(
            c for c in FIXTURE_CLIENTS if c['name'] == client))])
        app.app.config['TESTING'] = True
        captured.clear()
        MenuSolver._build_cells = _spy
        try:
            with app.app.test_client() as c:
                resp = c.post('/api/v1/plan', json={
                    'client_name': client, 'start_date': MONDAY,
                    'num_days': DAYS, 'time_limit_seconds': 20})
        finally:
            MenuSolver._build_cells = original
        assert resp.status_code == 200, resp.get_json()
        assert captured, 'the solve never reached _build_cells'
        return captured

    return _run


def _pinned_the_old_way(solver, dates, expanded_slots, cells):
    """`_rows_to_week_plan`'s inline accumulation, from the REAL cells.

    Deliberately a copy of the deleted code rather than a call to the new
    function — a test that called the thing it is checking would pass on any
    implementation at all.
    """
    cfg = solver.cfg
    forced = cfg.forced_items or {}
    client_consts = getattr(cfg, 'client_constant_items', None) or {}
    const_keys = (list(CONSTANT_ITEMS) if cfg.const_slots is None
                  else list(cfg.const_slots))
    solved_by_date = {}
    for cell in cells:
        solved_by_date.setdefault(cell.date, set()).add(cell.slot_id)

    pinned = set()
    for d in dates:
        day_out = set(solved_by_date.get(d, ()))
        for k in const_keys:
            if k not in CONSTANT_ITEMS or cell_is_skipped(solver.skip_cells, d, k):
                continue
            day_out.add(k)
            pinned.add((d, k))
        pinned.update((d, s) for (fd, s) in forced if fd == d and s in day_out)
        if client_consts:
            from src.solver._helpers import weekday_name
            weekday = weekday_name(d)
            for slot, spec in client_consts.items():
                if (d, slot) in forced:
                    continue
                if _resolve_client_constant(
                        spec, weekday, d.isocalendar()[1]) is not None:
                    pinned.add((d, slot))
    return pinned


@pytest.mark.parametrize('client', CLIENTS)
def test_the_function_matches_what_the_solve_produced(solved, client):
    got = solved(client)
    solver = got['solver']
    expected = _pinned_the_old_way(
        solver, got['dates'], got['expanded_slots'], got['cells'])
    assert solver.pinned_cells == expected, (
        f'{client}: the extracted walk and the stamping loop disagree about '
        f'which cells are pinned. Only in the function: '
        f'{sorted(solver.pinned_cells - expected)}; only in the loop: '
        f'{sorted(expected - solver.pinned_cells)}')


@pytest.mark.parametrize('client', CLIENTS)
def test_every_expanded_slot_gets_a_cell(solved, client):
    """The assumption the extraction rests on.

    `_build_cells` raises on an empty pool rather than dropping the slot, so
    "the solver chose it" is exactly "expanded and not skipped". If that ever
    stops holding, a `forced_items` pin on the dropped slot silently leaves
    the pinned set and the cell becomes editable in the table.
    """
    got = solved(client)
    solver = got['solver']
    by_date = {}
    for cell in got['cells']:
        by_date.setdefault(cell.date, set()).add(cell.slot_id)
    for d in got['dates']:
        from_config = {s for s in got['expanded_slots']
                       if not cell_is_skipped(solver.skip_cells, d, s)}
        assert by_date.get(d, set()) == from_config, (
            f'{client} on {d}: the solver built cells for '
            f'{sorted(by_date.get(d, set()))} but config says '
            f'{sorted(from_config)}')


def test_it_needs_no_solver_and_no_database():
    """The whole point: config in, pinned cells out.

    A plain horizon with one global staple slot, one forced pin, one client
    constant on Fridays and one skipped cell — enough that each branch is
    exercised and a wrong answer in any of them shows here rather than in a
    solve.
    """
    dates = [dt.date(2026, 11, 2) + dt.timedelta(days=i) for i in range(5)]
    friday = dates[4]
    out = pinned_cells_for_horizon(
        dates, ['rice', 'veg_gravy', 'bread'],
        const_slots=['papad'],
        skip_cells={(dates[1], 'bread')},
        forced_items={(dates[0], 'rice'): 'jeera_rice',
                      (dates[1], 'bread'): 'plain_chapati'},
        client_constant_items={'curd_side': {'friday': 'raita'}},
    )
    assert (dates[0], 'papad') in out, 'a global staple is pinned'
    assert (dates[0], 'rice') in out, 'a forced pin on a solved slot is pinned'
    assert (dates[1], 'bread') not in out, (
        'a forced pin on a SKIPPED cell is not pinned: there is no cell to '
        'pin, and the stamping loop never added one either')
    assert (friday, 'curd_side') in out, 'a weekday client constant is pinned'
    assert (dates[0], 'curd_side') not in out, (
        'a Friday-only constant does not pin Monday')
    assert (dates[0], 'veg_gravy') not in out, 'a freely solved cell is not pinned'


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
