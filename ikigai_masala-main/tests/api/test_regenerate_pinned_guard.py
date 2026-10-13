"""`/regenerate` refuses a pinned cell, server side (decision D3).

Until now the only thing stopping a staple or a client pin being regenerated
was the table markup: `ui/menu_table/index.html` gives a pinned cell no
`data-cell`, so it cannot be ticked. That is a UI convenience, not a rule — a
stale tab, a replayed request, a second client or the Pulse migration could
all ask for one and be served, and the answer would be a plan with a different
dish in a cell the client's own configuration says is fixed.

Two halves, both needed:

* the pinned cell is rejected, with `code` and the offending cells named, and
* an ordinary regenerate is **untouched**, because a guard that rejects
  everything would also pass the first half.
"""

from __future__ import annotations

import pytest

from tests.client_fixtures import CLIENTS

#: Booking.com, because it is the fixture client that actually HAS pinned
#: cells: measured, 20 over a five-day horizon (`white_rice` staples plus
#: `bread__2`, `starter__2`, `curd` and `curd_side` pins). Rippling — the
#: obvious first choice and the conftest default — has **none**, so this file
#: originally skipped both halves of the guard and reported itself green.
CLIENT = 'Booking.com'
MONDAY = '2026-11-02'
DAYS = 5


@pytest.fixture
def api(fake_supabase):
    import api.app as app
    fake_supabase.seed('clients', [dict(next(
        c for c in CLIENTS if c['name'] == CLIENT))])
    app.app.config['TESTING'] = True
    return app.app


def _plan(api):
    with api.test_client() as c:
        r = c.post('/api/v1/plan', json={
            'client_name': CLIENT, 'start_date': MONDAY,
            'num_days': DAYS, 'time_limit_seconds': 20})
    assert r.status_code == 200, r.get_json()
    sol = r.get_json()['solution']
    return {d: {s: v['item_base'] for s, v in day['items'].items()}
            for d, day in sol.items() if day.get('items')}, sol


def _a_pinned_cell(solution):
    for d, day in solution.items():
        for slot_id, v in (day.get('items') or {}).items():
            if v.get('is_pinned'):
                return d, slot_id
    raise AssertionError(
        f'{CLIENT} produced no pinned cell in this horizon, so neither half '
        f'of this guard was exercised. A skip here would read as a pass — '
        f'pick a client with staples or `constant_items`.')


def _a_free_cell(solution):
    for d, day in solution.items():
        for slot_id, v in (day.get('items') or {}).items():
            if not v.get('is_pinned') and slot_id.split('__')[0] == 'veg_gravy':
                return d, slot_id
    raise AssertionError('no free veg_gravy cell to regenerate')


def test_a_pinned_cell_is_rejected_and_nothing_is_solved(api):
    week, solution = _plan(api)
    date, slot_id = _a_pinned_cell(solution)
    with api.test_client() as c:
        r = c.post('/api/v1/regenerate', json={
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': DAYS,
            'time_limit_seconds': 20, 'base_plan': week,
            'replace_slots': {date: [slot_id]}})
    assert r.status_code == 400, r.get_json()
    body = r.get_json()
    assert body['code'] == 'pinned_cell', body
    assert {'date': date, 'slot_id': slot_id} in body['details']['cells'], body
    # No `solution` key at all: the guard runs before the regenerator, so
    # there is nothing half-solved to hand back.
    assert 'solution' not in body


def test_one_pinned_cell_rejects_the_whole_request(api):
    """A mixed request is refused outright rather than partly honoured.

    Serving the free cell and silently dropping the pinned one would be the
    worse answer: the planner asked for two cells and would get one back with
    nothing saying which, or why.
    """
    week, solution = _plan(api)
    pinned_date, pinned_slot = _a_pinned_cell(solution)
    free_date, free_slot = _a_free_cell(solution)
    before = dict(week[free_date])
    # Merged per date, not a dict literal with two keys: the two cells are
    # usually on the SAME day, and `{d: [pinned], d: [free]}` keeps only the
    # last one — the pinned cell silently left the request and the guard was
    # being asked to reject something that was not there. The 200 that
    # produced said "Regenerated 1 cells", which is what gave it away.
    replace_slots = {}
    replace_slots.setdefault(pinned_date, []).append(pinned_slot)
    replace_slots.setdefault(free_date, []).append(free_slot)
    with api.test_client() as c:
        r = c.post('/api/v1/regenerate', json={
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': DAYS,
            'time_limit_seconds': 20, 'base_plan': week,
            'replace_slots': replace_slots})
    assert r.status_code == 400, r.get_json()
    assert r.get_json()['code'] == 'pinned_cell'
    assert week[free_date] == before, 'the request must not mutate the plan'


def test_an_ordinary_regenerate_still_works(api):
    """The negative half. Without it the guard could reject everything.

    Asserts the request is SERVED, not that the dish changed. A regenerate
    whose hard block comes back INFEASIBLE retries with the old dish merely
    penalised rather than forbidden (`regenerator.py`, "retrying with
    penalty"), so returning the same dish is a legitimate outcome and an
    assertion against it fails on an unmodified checkout — measured, on this
    client's `veg_gravy`.
    """
    week, solution = _plan(api)
    date, slot_id = _a_free_cell(solution)
    with api.test_client() as c:
        r = c.post('/api/v1/regenerate', json={
            'client_name': CLIENT, 'start_date': MONDAY, 'num_days': DAYS,
            'time_limit_seconds': 20, 'base_plan': week,
            'replace_slots': {date: [slot_id]}})
    assert r.status_code == 200, r.get_json()
    out = r.get_json()['solution']
    assert out[date]['items'][slot_id]['item_base'], (
        'the cell came back empty')


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
