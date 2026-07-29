"""Every production client / counter must generate a complete, rule-abiding menu.

This is the regression net for the class of bug that unit tests structurally
cannot catch: a rule interaction that only appears against a *real* client
config. Four counters shipped INFEASIBLE (ToastTab, Computa Centre, and both
of L&T's single-theme counters) while the whole unit suite was green, because
nothing exercised the live ``clients`` rows end-to-end.

Two levels of assertion, because "the solver returned something" was the wrong
bar — several counters returned plans that silently violated their own config:

* ``test_every_counter_generates`` — every counter solves and fills every
  active slot on every planned day.
* the adherence tests — the specific silent-wrongness classes: a pinned
  constant must appear (and be tagged non-veg in the non-veg slot), a
  day-restricted slot must be absent on the other days including CONST slots,
  ``working_days`` must shrink the horizon, and a composition rule must not
  silently switch off because a sibling cell was pinned.

Marked ``slow``: a full sweep is a real CP-SAT solve per counter.
"""

import datetime as dt

import pytest

from tests.client_fixtures import APP_SETTINGS, CLIENTS
from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'          # a Monday, so Mon-Fri needs no weekend logic
TIME_LIMIT = 40


@pytest.fixture
def live_clients(monkeypatch):
    """Install the production client set behind the app's Supabase singleton."""
    import src.db as db_mod

    fake = FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS],
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [],
        'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)

    import api.app as api_app
    for attr in ('_client_loader', '_pools', '_df', '_nonveg_items'):
        monkeypatch.setattr(api_app, attr, None, raising=False)
    monkeypatch.setattr(api_app, '_menu_rules_by_city', {}, raising=False)
    monkeypatch.setattr(api_app, '_filtered_cache', {}, raising=False)
    api_app.app.config['TESTING'] = True
    return api_app


def _counters(api_app, name):
    return api_app._get_client_loader().get_client_configs(name)


def _plan(api_app, name, idx, **overrides):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    body = {
        'client_name': name, 'counter_index': idx, 'start_date': MONDAY,
        'num_days': 5, 'time_limit_seconds': TIME_LIMIT,
    }
    body.update(overrides)
    resp = api_app.app.test_client().post('/api/v1/plan', json=body)
    return resp, (resp.get_json() or {})


def _all_counters():
    for client in CLIENTS:
        for idx, counter in enumerate(client['counters']):
            yield client['name'], idx, counter['name']


@pytest.mark.slow
@pytest.mark.parametrize(
    'client_name,idx,counter_name',
    list(_all_counters()),
    ids=[f"{c}-{n}" for c, _i, n in _all_counters()],
)
def test_every_counter_generates(live_clients, client_name, idx, counter_name):
    """No counter may fail, and no active slot may be left empty."""
    resp, body = _plan(live_clients, client_name, idx)
    assert resp.status_code == 200, (
        f"{client_name}/{counter_name} did not generate "
        f"({resp.status_code}): {body.get('error') or body.get('message')}"
    )

    _name, cfg = _counters(live_clients, client_name)[idx]
    solution = body['solution']
    assert solution, f"{client_name}/{counter_name} returned an empty plan"

    # A slot may legitimately be absent on a given day: slot_day_restriction
    # and a mutually-exclusive pinned constant both remove cells. Take the
    # expected set per day from the same skip_cells the planner used, so the
    # assertion stays "nothing is silently blank" rather than "every slot every
    # day" — which would fail Ikea's Tue/Thu-only white rice and Quince's
    # curd/raita split.
    from src.solver._helpers import cell_is_skipped
    inputs = live_clients._prepare_solver_inputs(
        {'client_name': client_name, 'counter_index': idx,
         'start_date': MONDAY, 'num_days': 5,
         'time_limit_seconds': TIME_LIMIT},
        client_cfg=cfg,
    )
    skip = inputs.skip_cells

    for day_key, day in solution.items():
        d = dt.date.fromisoformat(day_key)
        items = day['items']
        for slot_id in cfg.active_slots:
            if cell_is_skipped(skip, d, slot_id):
                continue
            value = items.get(slot_id, {})
            name = value.get('item') if isinstance(value, dict) else value
            assert name, (
                f"{client_name}/{counter_name} {day_key}: slot "
                f"{slot_id!r} is empty"
            )
        # Nothing that IS present may be blank.
        for slot_id, value in items.items():
            name = value.get('item') if isinstance(value, dict) else value
            assert str(name).strip(), (
                f"{client_name}/{counter_name} {day_key}: slot "
                f"{slot_id!r} present but blank"
            )


@pytest.mark.slow
def test_working_days_shrink_the_horizon(live_clients):
    """Quince runs Wed/Thu/Fri — the plan must contain only those days."""
    resp, body = _plan(live_clients, 'Quince', 0)
    assert resp.status_code == 200, body.get('error')
    days = {
        dt.date.fromisoformat(k).strftime('%A').lower()
        for k in body['solution']
    }
    assert days == {'wednesday', 'thursday', 'friday'}, days


@pytest.mark.slow
def test_pinned_constant_appears_and_is_tagged_nonveg(live_clients):
    """Plan View pins nonveg_main__2 daily; it must show and render non-veg.

    A pinned value is free text with no ontology row, so the non-veg lookup
    used to miss it and a non-veg dish rendered as vegetarian.
    """
    resp, body = _plan(live_clients, 'Plan View', 0)
    assert resp.status_code == 200, body.get('error')
    for day_key, day in body['solution'].items():
        pinned = day['items'].get('nonveg_main__2')
        assert pinned, f"{day_key}: pinned nonveg_main__2 missing"
        assert pinned['item_base'].lower() == 'boiled egg'
        assert pinned['is_nonveg'] is True, (
            f"{day_key}: pinned non-veg dish tagged vegetarian"
        )


@pytest.mark.slow
def test_pinned_sibling_does_not_disable_the_composition_rule(live_clients):
    """Plan View still gets its paired nonveg main on the unpinned cell.

    ``nonveg_main__2`` is pinned every day, leaving one solved cell. The
    composition rule self-gates on the *configured* slot count, so it must
    still constrain the surviving cell rather than switching off for the week.
    """
    resp, body = _plan(live_clients, 'Plan View', 0)
    assert resp.status_code == 200, body.get('error')
    for day_key, day in body['solution'].items():
        solved = day['items'].get('nonveg_main__1')
        assert solved and solved['item'], f"{day_key}: nonveg_main__1 empty"


@pytest.mark.slow
def test_day_restriction_applies_to_const_slots(live_clients):
    """A CONST slot honours slot_day_restriction.

    Constant slots are stamped rather than solved, so a day restriction on
    white_rice used to be a silent no-op and the staple appeared all week.
    """
    import json
    from pathlib import Path
    import src.menu_rules.menu_rule_loader as loader_mod

    rules_path = Path(loader_mod.CLIENT_RULES_CONFIG_PATH)
    blob = json.loads(rules_path.read_text())
    restriction = [
        r for r in (blob.get('Ikea', {}).get('rules') or [])
        if r.get('base_slot') == 'white_rice'
    ]
    if not restriction:
        pytest.skip("Ikea has no white_rice day restriction configured")
    allowed = {w[:3].lower() for w in restriction[0]['allowed_weekdays']}

    resp, body = _plan(live_clients, 'Ikea', 0)
    assert resp.status_code == 200, body.get('error')
    for day_key, day in body['solution'].items():
        wd = dt.date.fromisoformat(day_key).strftime('%a').lower()
        present = bool(day['items'].get('white_rice'))
        assert present == (wd in allowed), (
            f"{day_key} ({wd}): white_rice present={present}, "
            f"allowed weekdays={sorted(allowed)}"
        )


@pytest.mark.slow
def test_starved_slot_warns_instead_of_failing(live_clients):
    """A slot with too few items repeats *and* says so, rather than 500-ing.

    ToastTab's curd_rice pool holds 4 eligible items against a 5-day horizon.
    Strict uniqueness is arithmetically impossible, so the plan must still be
    produced with a diagnostic naming the slot.
    """
    resp, body = _plan(live_clients, 'ToastTab', 0)
    assert resp.status_code == 200, body.get('error')
    starved = [
        d for d in body.get('rule_diagnostics', [])
        if d.get('affected', {}).get('base_slot') == 'curd_rice'
        and d.get('severity') == 'warning'
    ]
    assert starved, (
        "expected a warning naming curd_rice as under-supplied; got "
        f"{[d.get('message') for d in body.get('rule_diagnostics', [])][:6]}"
    )
