"""`POST /api/v1/pick`: what it refuses, what it stamps, what it reports.

A pick is the one place in this system where a human overrules the solver, so
the failure that matters is not "the pick was rejected" — the planner sees
that and argues. It is a pick that is QUIETLY not what was asked for: a
different dish stamped, a blocking repeat reported as a mild warning, an
Exceptions list that looks complete and is not. Each test below is aimed at
one of those.

The audit half runs against a seeded history, because the detectors read the
same `banned_by_date` / `recency_by_item` maps the solver reads and those are
empty on a fresh fixture — a cooldown test with no history passes without
checking anything.
"""

from __future__ import annotations

import pytest

from tests.client_fixtures import CLIENTS

#: Booking.com has pinned cells (20 over five days, measured) and a wide
#: counter. Rippling, the conftest default, has none — a pinned-cell test
#: written against it skips and reads as a pass.
CLIENT = 'Booking.com'
MONDAY = '2026-11-02'
DAYS = 5
#: Inside the 21-day cooldown window but in the PREVIOUS ISO week, so it is a
#: cooldown warning and not a D5 block. The two are easy to confuse — a dish
#: served earlier this week is inside the window too — and getting it wrong
#: turns a block into a warning, which is the direction that reaches a plate.
LAST_WEEK = '2026-10-28'
COOLDOWN_DISH = 'gujarati_kadhi'


def _client_row():
    return dict(next(c for c in CLIENTS if c['name'] == CLIENT))


@pytest.fixture
def api(fake_supabase):
    import api.app as app
    fake_supabase.seed('clients', [_client_row()])
    app.app.config['TESTING'] = True
    return app.app


@pytest.fixture
def api_with_history(fake_supabase):
    import api.app as app
    fake_supabase.seed('clients', [_client_row()])
    fake_supabase.seed('menu_history', [
        {'client_name': CLIENT, 'service_date': LAST_WEEK,
         'menu': {'veg_gravy': COOLDOWN_DISH}}])
    app.app.config['TESTING'] = True
    return app.app


def _plan(api):
    with api.test_client() as c:
        r = c.post('/api/v1/plan', json={
            'client_name': CLIENT, 'start_date': MONDAY,
            'num_days': DAYS, 'time_limit_seconds': 20})
    assert r.status_code == 200, r.get_json()
    sol = r.get_json()['solution']
    week = {d: {s: v['item_base'] for s, v in day['items'].items()}
            for d, day in sol.items() if day.get('items')}
    return week, sol


def _free_cell(sol, base='veg_gravy'):
    for d, day in sol.items():
        for slot_id, v in (day.get('items') or {}).items():
            if slot_id.split('__')[0] == base and not v.get('is_pinned'):
                return d, slot_id
    raise AssertionError(f'no free {base} cell in the plan')


def _pinned_cell(sol):
    for d, day in sol.items():
        for slot_id, v in (day.get('items') or {}).items():
            if v.get('is_pinned'):
                return d, slot_id
    raise AssertionError(f'{CLIENT} produced no pinned cell — this test would '
                         f'otherwise skip and read as a pass')


def _unused_dish(week, base='veg_gravy', city='Bangalore'):
    from src.ontology import repository
    _df, pools = repository.menu_data(city)
    used = {v.strip().lower() for day in week.values() for v in day.values()}
    for name in pools[base]['item'].astype(str).tolist():
        if name.strip().lower() not in used:
            return name
    raise AssertionError(f'every {base} dish in {city} is already on the plan')


def _pick(api, week, date, slot_id, item):
    with api.test_client() as c:
        return c.post('/api/v1/pick', json={
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': DAYS,
            'base_plan': week, 'picks': {date: {slot_id: item}}})


# --- the stamp ------------------------------------------------------------


def test_the_dish_asked_for_is_the_dish_stamped(api):
    """Guarantee §6.5: never a silent substitution.

    The obvious implementation — pin the dish and regenerate — fails exactly
    here. `MenuSolver` logs an ineligible pin at INFO and solves the cell
    normally, so that route answers 200 with a different dish and a plausible
    menu. This asserts the dish by name, not merely that something changed.
    """
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    dish = _unused_dish(week)
    r = _pick(api, week, date, slot_id, dish)
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    item = out['solution'][date]['items'][slot_id]
    assert item['item_base'] == dish
    assert item['is_manual'] is True
    assert out['changed'] is True
    assert out['manual_cells'] == {date: [slot_id]}


def test_the_stamp_carries_the_colour_suffix(api):
    """Note 28, which is a data-integrity rule and not a cosmetic one.

    A plan saved with a spelling the ontology does not use matches no pool row
    on the way back: never banned by the cooldown, never aged by freshness,
    with no log line and a plausible menu every week. The solver writes
    `dish(Y)`; a pick must write the same.
    """
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    dish = _unused_dish(week)
    r = _pick(api, week, date, slot_id, dish)
    assert r.status_code == 200, r.get_json()
    stamped = r.get_json()['solution'][date]['items'][slot_id]['item']
    assert stamped.startswith(dish)
    assert stamped == dish or stamped[len(dish):].startswith('('), (
        f'{stamped!r} is neither the bare dish nor dish(Colour)')


def test_every_other_cell_comes_back_untouched(api):
    """Guarantee §6.2. A pick is not a solve, so nothing else may move."""
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    r = _pick(api, week, date, slot_id, _unused_dish(week))
    assert r.status_code == 200, r.get_json()
    out = r.get_json()['solution']
    moved = [(d, s) for d, slots in week.items() for s, v in slots.items()
             if (d, s) != (date, slot_id)
             and out[d]['items'][s]['item_base'] != v]
    assert not moved, f'cells changed that were not picked: {moved}'


def test_picking_the_dish_already_there_is_not_an_error(api):
    """Contract §2.2: a no-op, reported as `changed: false`, not a repeat.

    The cell must not count against itself in the week rule, which is the
    easiest D5 bug to write and the hardest to notice: it would make every
    second pick on a cell fail.
    """
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    r = _pick(api, week, date, slot_id, week[date][slot_id])
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['changed'] is False


# --- the blocks -----------------------------------------------------------


def test_a_pinned_cell_is_refused(api):
    week, sol = _plan(api)
    date, slot_id = _pinned_cell(sol)
    r = _pick(api, week, date, slot_id, _unused_dish(week))
    assert r.status_code == 400
    assert r.get_json()['code'] == 'pinned_cell'


def test_a_dish_from_another_slot_is_refused(api):
    """Decision D4 bounds the search to the cell's own category."""
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    r = _pick(api, week, date, slot_id, 'plain_chapati')
    assert r.status_code == 400
    body = r.get_json()
    assert body['code'] == 'not_a_slot_dish'
    assert body['details']['item'] == 'plain_chapati'


def test_a_dish_already_on_the_plan_this_week_is_blocked(api):
    """Decision D5, the one rule a pick cannot override."""
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    other = next(v for d, slots in week.items() for s, v in slots.items()
                 if s.split('__')[0] == 'veg_gravy' and (d, s) != (date, slot_id))
    r = _pick(api, week, date, slot_id, other)
    assert r.status_code == 400, r.get_json()
    body = r.get_json()
    assert body['code'] == 'week_repeat'
    assert body['details']['source'] == 'plan'
    assert "can't repeat in a week" in body['error']


def test_a_blocked_pick_changes_nothing(api):
    """Contract §2.4: on any 400 the plan the client holds is still correct."""
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    before = {d: dict(slots) for d, slots in week.items()}
    r = _pick(api, week, date, slot_id, 'plain_chapati')
    assert r.status_code == 400
    assert 'solution' not in r.get_json()
    assert week == before


def test_an_unknown_cell_is_refused(api):
    week, sol = _plan(api)
    date, _slot = _free_cell(sol)
    r = _pick(api, week, date, 'no_such_slot', _unused_dish(week))
    assert r.status_code == 400
    assert r.get_json()['code'] == 'unknown_cell'


def test_a_date_outside_the_horizon_is_refused(api):
    week, sol = _plan(api)
    _date, slot_id = _free_cell(sol)
    week = {**week, '2027-01-04': {slot_id: 'x'}}
    r = _pick(api, week, '2027-01-04', slot_id, _unused_dish(week))
    assert r.status_code == 400
    assert r.get_json()['code'] == 'bad_date'


def test_empty_picks_is_refused(api):
    week, _sol = _plan(api)
    with api.test_client() as c:
        r = c.post('/api/v1/pick', json={
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': DAYS,
            'base_plan': week, 'picks': {}})
    assert r.status_code == 400
    assert r.get_json()['code'] == 'bad_request'


# --- the audit ------------------------------------------------------------


def test_a_cooldown_dish_is_a_warning_and_not_a_block(api_with_history):
    """The distinction D5's ordering exists to protect.

    `gujarati_kadhi` was served 5 days before the plan starts: inside the
    21-day window, but in the PREVIOUS ISO week. So it is a warning the
    planner may overrule, not a block. Were the cooldown audited before the
    week rule, a same-week repeat would arrive here too and be waved through
    with the same gentle wording.
    """
    week, sol = _plan(api_with_history)
    date, slot_id = _free_cell(sol)
    r = _pick(api_with_history, week, date, slot_id, COOLDOWN_DISH)
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert len(out['exceptions']) == 1, out['exceptions']
    entry = out['exceptions'][0]
    assert entry['item'] == COOLDOWN_DISH
    assert entry['replaced'] == week[date][slot_id]
    codes = [v['code'] for v in entry['violations']]
    assert 'cooldown' in codes, codes
    cooldown = next(v for v in entry['violations'] if v['code'] == 'cooldown')
    assert cooldown['severity'] == 'warning'
    assert cooldown['details']['last_served'] == LAST_WEEK
    assert cooldown['details']['window_days'] == 21


def test_one_fact_is_reported_once(api_with_history):
    """Spec §5.1: prefer the specific code.

    The item cooldown has a named detector AND a loaded rule whose pre-filter
    removes the same row, so an unguarded audit tells the planner "served 5
    days ago" twice in different words — measured, before the re-probe went
    in. The de-duplication asks the rule whether the ban was its whole reason
    rather than matching a class name, so it keeps working for a client that
    ships its own cooldown rule under another name.
    """
    week, sol = _plan(api_with_history)
    date, slot_id = _free_cell(sol)
    r = _pick(api_with_history, week, date, slot_id, COOLDOWN_DISH)
    assert r.status_code == 200, r.get_json()
    violations = r.get_json()['exceptions'][0]['violations']
    cooldownish = [v for v in violations
                   if v['code'] == 'cooldown' or 'cooldown' in v['rule']]
    assert len(cooldownish) == 1, (
        f'the cooldown is reported {len(cooldownish)} times: '
        f'{[v["code"] for v in cooldownish]}')


def test_a_clean_pick_has_no_exceptions(api):
    """The negative half. Without it every audit test above passes on an
    audit that reports everything it is shown."""
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    r = _pick(api, week, date, slot_id, _unused_dish(week))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['exceptions'] == []


def test_coverage_is_always_declared(api):
    """Spec §6, and the reason this feature has a doc about honesty.

    Weekly caps, slot composition and colour constraints exist only inside the
    CP-SAT model. No reading of a finished plan reveals them, so a pick that
    breaks one will NOT appear in Exceptions — and the only acceptable version
    of that is one where the response says so every single time.
    """
    week, sol = _plan(api)
    date, slot_id = _free_cell(sol)
    r = _pick(api, week, date, slot_id, _unused_dish(week))
    out = r.get_json()
    assert out['checked'], 'checked must never be empty'
    for expected in ('cooldown', 'client_pool', 'pre_filter_rules',
                     'plate_checks'):
        assert expected in out['checked'], expected
    for expected in ('selector_frequency caps', 'slot_composition',
                     'colour constraints'):
        assert expected in out['not_checked'], expected


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
