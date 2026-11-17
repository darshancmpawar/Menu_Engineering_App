"""Four consecutive SAVED weeks, for every client, counter and meal.

`test_all_clients_generate.py` plans one week against an empty history. The
failure it cannot see is the one that grows with history: every saved week
tightens the item cooldown, the cross-week cadences and the week signature, so
a counter can solve week 1 and go INFEASIBLE in week 3 (2.07.03 recorded six
sites that could not plan a third consecutive saved week).

This drives the planner the way Generate in `app.py` does, because a harsher
test reports failures the planner never meets:

- the services in the client's `meals` (lunch and dinner when unset), each
  counter told to avoid what THE SAME COUNTER served at the earlier sittings —
  per counter, not pooled across the site (`_exclusions_from`), and minus the
  `meal_shared_categories` slots, which are pinned instead;
- the primary counter's `shared_categories` dishes pinned into the others;
- the same time budget: 180 s split across counters x meals, at least 45 s.

It fails if any week of any counter and meal does not come back as a menu.
Run it on an otherwise idle machine: a solve starved of CPU answers "no plan
within the time limit" for a counter that is perfectly plannable, which reads
like the failure this test hunts. The error text tells them apart: "cannot all
be satisfied" is a proof, "within the time limit" is not.

Marked ``slow``: about 700 real solves. Run with ``pytest -m slow``.
"""

from __future__ import annotations

import copy
import datetime as dt
from urllib.parse import quote

import pytest

from src.history import DEFAULT_MEALS
from tests.client_fixtures import APP_SETTINGS, CLIENTS
from tests.fake_supabase import FakeSupabase

FIRST_MONDAY = dt.date(2026, 8, 3)
WEEKS = 4
PLANNING_TIME_LIMIT = 180   # app.py _PLANNING_TIME_LIMIT_SECONDS


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


def plan_four_weeks(api_app, name, stop_at_first=False):
    """Plan and save WEEKS weeks as app.py's Generate does; returns failure lines."""
    from ui.formatters import dishes_from_solution, shared_items_from_solution

    cfg = api_app.app.test_client().get(
        f'/api/v1/client-config/{quote(name)}').get_json() or {}
    assert cfg.get('success'), f'{name}: client-config read failed — {cfg}'
    counters = [c.get('name') or f'Counter {i + 1}'
                for i, c in enumerate(cfg.get('counters') or [])] or ['Counter 1']
    meals = list(cfg.get('meals') or DEFAULT_MEALS)
    shared = cfg.get('shared_categories') or []
    shared_off = set(cfg.get('shared_categories_excluded_counters') or [])
    meal_shared = cfg.get('meal_shared_categories') or []
    time_limit = max(45, PLANNING_TIME_LIMIT // (len(counters) * len(meals)))
    failures = []

    for week in range(WEEKS):
        start = (FIRST_MONDAY + dt.timedelta(weeks=week)).isoformat()
        served_so_far: dict = {}   # {counter_index: {iso: [dish, ...]}}
        carried_over: dict = {}    # {counter_index: [[iso, slot_id, dish], ...]}
        for m, meal in enumerate(meals):
            solved, shared_items = [], []
            for idx, counter in enumerate(counters):
                pins = list(carried_over.get(idx) or [])
                if idx > 0 and counter not in shared_off:
                    pins += shared_items
                body = {'client_name': name, 'counter_index': idx,
                        'start_date': start, 'num_days': 5,
                        'time_limit_seconds': time_limit, 'meal': meal}
                if pins:
                    body['shared_items'] = pins
                if served_so_far.get(idx):
                    body['exclude_items'] = served_so_far[idx]
                resp, out = _post(api_app, '/api/v1/plan', body)
                where = f"week {week + 1} {meal} {counter!r}"
                sol = out.get('solution') or {}
                if resp.status_code != 200:
                    failures.append(f"{where}: HTTP {resp.status_code} — "
                                    f"{out.get('error') or out.get('message')}")
                elif not sol or _empty_served_days(sol):
                    failures.append(f"{where}: no dishes on "
                                    f"{_empty_served_days(sol) or 'any day'}")
                else:
                    solved.append((idx, counter, sol))
                    if idx == 0 and shared:
                        shared_items = shared_items_from_solution(sol, shared)
                if failures and stop_at_first:
                    return failures
            if not solved:
                continue
            # Saved the way the planner does: one nested row per date for a
            # multi-counter client, the flat week for a single counter.
            save = {'client_name': name, 'week_start': start, 'meal': meal}
            if len(counters) > 1:
                save['counters'] = [{'name': c, 'week_plan': _week_plan(s)}
                                    for _i, c, s in solved]
            else:
                save['week_plan'] = _week_plan(solved[0][2])
            resp, out = _post(api_app, '/api/v1/save', save)
            if resp.status_code != 200:
                failures.append(f"week {week + 1} {meal}: save failed — "
                                f"{out.get('error')}")
            for idx, _c, sol in solved:
                if m == 0 and meal_shared:
                    carried_over[idx] = shared_items_from_solution(sol, meal_shared)
                for iso, dishes in dishes_from_solution(sol, keep_slots=meal_shared).items():
                    day = served_so_far.setdefault(idx, {}).setdefault(iso, [])
                    day[:] = sorted(set(day) | set(dishes))
    return failures


@pytest.mark.slow
@pytest.mark.parametrize('client', CLIENTS, ids=[c['name'] for c in CLIENTS])
def test_four_saved_weeks_in_a_row(monkeypatch, client):
    api_app = _api(monkeypatch, client)
    failures = plan_four_weeks(api_app, client['name'])
    assert not failures, f"{client['name']}:\n  " + "\n  ".join(failures)
