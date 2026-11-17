"""Four consecutive SAVED weeks, for every client, counter and meal.

`test_all_clients_generate.py` plans one week against an empty history. The
failure it cannot see is the one that grows with history: every saved week
tightens the item cooldown, the cross-week cadences and the week signature, so
a counter can solve week 1 and go INFEASIBLE in week 3 (2.07.04 recorded six
sites that could not plan a third consecutive saved week). This drives the
planner the way the screen does — lunch for every counter, save, then dinner
with lunch's dishes excluded, save — for four weeks running, and fails if any
week of any counter and meal does not come back as a menu.

Simplifications, all of which make it no easier to pass: the fixture rows carry
no `meals`, so every client plans lunch AND dinner (two live sites serve lunch
only); cross-counter shared items and meal-shared categories are not passed, so
each counter solves on its own. `time_limit` is 30 s — the question is whether a
menu exists, not how good it is. Run it on an otherwise idle machine: a solve
starved of CPU answers "no plan within the time limit" for a counter that is
perfectly plannable, which reads exactly like the failure this test hunts.

Marked ``slow``: about 700 real solves. Run with ``pytest -m slow``.
"""

from __future__ import annotations

import copy
import datetime as dt

import pytest

from src.history import DEFAULT_MEALS
from tests.client_fixtures import APP_SETTINGS, CLIENTS
from tests.fake_supabase import FakeSupabase

FIRST_MONDAY = dt.date(2026, 8, 3)
WEEKS = 4
TIME_LIMIT = 30


def _api(monkeypatch, client):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [copy.deepcopy(client)],
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _post(api_app, path, body):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api_app.app.test_client().post(path, json=body)
    return resp, (resp.get_json() or {})


def _week_plan(solution):
    return {ds: {sid: c['item'] for sid, c in (day.get('items') or {}).items()}
            for ds, day in solution.items()}


def _empty_served_days(solution):
    return [ds for ds, day in solution.items()
            if day.get('is_working_day') is not False and not day.get('items')]


@pytest.mark.slow
@pytest.mark.parametrize('client', CLIENTS, ids=[c['name'] for c in CLIENTS])
def test_four_saved_weeks_in_a_row(monkeypatch, client):
    from ui.formatters import dishes_from_solution

    api_app = _api(monkeypatch, client)
    loader = api_app._get_client_loader()
    name = client['name']
    meals = list(client.get('meals') or DEFAULT_MEALS)
    failures = []

    for week in range(WEEKS):
        start = (FIRST_MONDAY + dt.timedelta(weeks=week)).isoformat()
        earlier_meal_dishes: dict = {}
        for meal in meals:
            counters = loader.get_client_configs(name, meal)
            solved = []
            for idx, (counter, _cfg) in enumerate(counters):
                body = {'client_name': name, 'counter_index': idx,
                        'start_date': start, 'num_days': 5,
                        'time_limit_seconds': TIME_LIMIT, 'meal': meal}
                if earlier_meal_dishes:
                    body['exclude_items'] = earlier_meal_dishes
                resp, out = _post(api_app, '/api/v1/plan', body)
                where = f"week {week + 1} {meal} {counter!r}"
                if resp.status_code != 200:
                    failures.append(f"{where}: HTTP {resp.status_code} — "
                                    f"{out.get('error') or out.get('message')}")
                    continue
                sol = out.get('solution') or {}
                empty = _empty_served_days(sol)
                if not sol or empty:
                    failures.append(f"{where}: no dishes on {empty or 'any day'}")
                    continue
                solved.append((counter, sol))
            if not solved:
                continue
            # Save the way the planner does: one nested row per date for a
            # multi-counter client, the flat week for a single counter.
            save = {'client_name': name, 'week_start': start, 'meal': meal}
            if len(counters) > 1:
                save['counters'] = [{'name': c, 'week_plan': _week_plan(s)}
                                    for c, s in solved]
            else:
                save['week_plan'] = _week_plan(solved[0][1])
            resp, out = _post(api_app, '/api/v1/save', save)
            if resp.status_code != 200:
                failures.append(f"week {week + 1} {meal}: save failed — "
                                f"{out.get('error')}")
            for _c, sol in solved:
                for iso, dishes in dishes_from_solution(sol).items():
                    earlier_meal_dishes.setdefault(iso, []).extend(dishes)

    assert not failures, f"{name}:\n  " + "\n  ".join(failures)
