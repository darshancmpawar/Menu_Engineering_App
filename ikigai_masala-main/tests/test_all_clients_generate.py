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
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


@pytest.fixture
def live_clients_lt_five(monkeypatch):
    """Like ``live_clients`` but with L&T's non-veg counter set to five dishes.

    The live row still says 1, so the five-dish station is the client's stated
    requirement rather than its current config. The test raises the count itself
    instead of baking it into the snapshot, so ``client_fixtures`` stays a true
    mirror of the database and this test does not silently start passing (or
    failing) when the live row changes.
    """
    import copy
    import src.db as db_mod

    clients = copy.deepcopy(CLIENTS)
    for c in clients:
        if c['name'] == 'L&T':
            for ctr in c['counters']:
                if ctr['name'] == 'Non Veg Lunch':
                    ctr['slot_counts']['nonveg_main'] = 5
    fake = FakeSupabase(seed={
        'clients': clients,
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
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


# Start dates that exercise the theme resolution, not just one happy Monday.
# `chinese_continental` resolves per ISO-week parity, so a counter can be
# satisfiable on an even week and INFEASIBLE on an odd one; a mid-week start
# spans two ISO weeks and flips the theme inside a single horizon. Sweeping only
# MONDAY of an even week hid Amadeus's Chinese counter failing on 9 of 14 start
# dates.
ALT_STARTS = [
    '2026-07-27',   # Monday, ISO week 31 (odd)  -> all-continental horizon
    '2026-07-29',   # Wednesday                  -> horizon spans weeks 31/32
]


@pytest.mark.slow
@pytest.mark.parametrize('start', ALT_STARTS)
@pytest.mark.parametrize(
    'client_name,idx,counter_name',
    list(_all_counters()),
    ids=[f"{c}-{n}" for c, _i, n in _all_counters()],
)
def test_every_counter_generates_on_other_start_dates(
    live_clients, client_name, idx, counter_name, start,
):
    """The fleet must generate whatever weekday and ISO week it is asked for.

    A 422 is an acceptable outcome here and a 500 is not: 422 means the
    pre-flight named a real config contradiction with a fix, which is the
    designed behaviour for an over-constrained counter. An unexplained
    INFEASIBLE is the failure this test exists to catch.
    """
    resp, body = _plan(live_clients, client_name, idx, start_date=start)
    assert resp.status_code in (200, 422), (
        f"{client_name}/{counter_name} start={start} returned "
        f"{resp.status_code}: {body.get('error') or body.get('message')}"
    )
    if resp.status_code == 422:
        errors = [d for d in body.get('rule_diagnostics', [])
                  if d.get('severity') == 'error']
        assert errors, (
            f"{client_name}/{counter_name} start={start} was blocked with no "
            f"error diagnostic explaining why"
        )
        for d in errors:
            assert d.get('suggestion'), (
                f"{d['rule']} blocked the plan without suggesting a fix"
            )


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


@pytest.mark.slow
def test_biryani_lands_on_biryani_days_for_a_three_slot_counter(live_clients):
    """A 3-nonveg counter must still get its themed composition.

    ``nonveg_main_daily_pair`` used to gate on ``requires_slot_count: 2`` — an
    exact match — so Computa Centre's 3-dish non-veg counter got no composition
    at all: its biryani-theme day came back with no biryani while non-biryani
    days got two. The gate is now a minimum.
    """
    resp, body = _plan(live_clients, 'Computa Centre', 0, start_date='2026-07-29')
    assert resp.status_code == 200, body.get('error') or body.get('message')

    def biryanis(day):
        return [
            v['item_base'] for k, v in day['items'].items()
            if k.startswith('nonveg_main') and 'biryani' in v['item_base']
        ]

    biryani_days = [(k, d) for k, d in body['solution'].items()
                    if d['day_type'] == 'biryani']
    assert biryani_days, 'fixture no longer has a biryani-theme day'
    for key, day in biryani_days:
        assert biryanis(day), (
            f"{key} is a biryani day but no nonveg_main is a biryani: "
            f"{ {k: v['item_base'] for k, v in day['items'].items() if k.startswith('nonveg_main')} }"
        )
    # And no day may stack two biryanis (the weekly cap counts days, so the
    # per-day cap is what stops a pair of biryanis sharing one).
    for key, day in body['solution'].items():
        assert len(biryanis(day)) <= 1, f"{key} has {biryanis(day)}"


@pytest.mark.slow
def test_five_dish_station_serves_a_kebab_every_day(live_clients_lt_five):
    """L&T's 5-dish non-veg station: 5 dishes daily, kebab included.

    Only one kebab is eligible for a common-only client, so a variety dish would
    make "a kebab daily" need five distinct ones. The kebab is a staple — the
    same dish every day, like steamed rice — so it recurs, while the rest of the
    counter still varies.
    """
    resp, body = _plan(live_clients_lt_five, 'L&T', 2, start_date='2026-07-29',
                       time_limit_seconds=120)
    assert resp.status_code == 200, body.get('error') or body.get('message')

    _name, cfg = _counters(live_clients_lt_five, 'L&T')[2]
    assert int(cfg.slot_counts.get('nonveg_main', 1)) == 5

    df = live_clients_lt_five._get_menu_data()[0]
    truthy = df['is_tandoor'].fillna(0).astype(str).str.strip().str.lower()
    staples = {
        str(v).strip().lower()
        for v in df[truthy.isin(('1', 'true', 'yes', 'y'))]['item'].tolist()
    }

    for key, day in body['solution'].items():
        nonveg = [v['item_base'] for k, v in day['items'].items()
                  if k.startswith('nonveg_main')]
        assert len(nonveg) == 5, f"{key} served {len(nonveg)} dishes: {nonveg}"
        assert any(n in staples for n in nonveg), (
            f"{key} has no kebab among {nonveg}"
        )

    # The staple exemption is slot-scoped: bread must still vary. `is_tandoor`
    # also marks tandoor breads, and a flat flag list would have let butter naan
    # repeat all week here.
    breads = [d['items']['bread']['item_base']
              for d in body['solution'].values() if 'bread' in d['items']]
    assert len(set(breads)) == len(breads), f"bread repeated: {breads}"


@pytest.mark.slow
def test_theme_forced_cap_conflict_is_explained_not_infeasible(live_clients):
    """A cap the themes force past must 422 with the rule named and a fix given.

    Neither rule alone can see this contradiction — the cap does not know the
    theme map, and the composition does not know the cap — so the solve used to
    come back as a bare INFEASIBLE 500 with nothing to act on. Provoked here by
    re-enabling the weekly biryani cap on a counter themed biryani twice, which
    is the shape the shipped config resolves with a per-counter disable.
    """
    import src.menu_rules.menu_rule_loader as loader_mod

    real = loader_mod.MenuRuleLoader.load_for_client

    def without_the_disable(self, client, generic=None, counter_name=None):
        rules = real(self, client, generic, counter_name)
        if any(r.name == 'nonveg_biryani_once_per_week' for r in rules):
            return rules
        from src.menu_rules.nonveg_rules import NonvegBiryaniWeeklyRule
        return rules + [NonvegBiryaniWeeklyRule({
            'type': 'nonveg_biryani_weekly',
            'name': 'nonveg_biryani_once_per_week', 'max_per_week': 1,
        })]

    loader_mod.MenuRuleLoader.load_for_client = without_the_disable
    try:
        resp, body = _plan(live_clients, 'Siemens Technology', 2,
                           start_date='2026-07-29')
    finally:
        loader_mod.MenuRuleLoader.load_for_client = real

    assert resp.status_code == 422, (
        f"expected a pre-flight block, got {resp.status_code}: "
        f"{body.get('error') or body.get('message')}"
    )
    errs = [d for d in body['rule_diagnostics'] if d['severity'] == 'error']
    conflict = next(
        (d for d in errs if d['rule'] == 'nonveg_biryani_once_per_week'), None,
    )
    assert conflict is not None, [d['rule'] for d in errs]
    # Two biryani-theme weekdays, each mandating a biryani via the composition.
    assert conflict['affected']['forced_biryani_days'] == 2
    assert 'disable' in conflict['suggestion']


@pytest.mark.slow
def test_configured_counters_no_longer_hit_that_conflict(live_clients):
    """The shipped config resolves it: both biryani days get a biryani."""
    resp, body = _plan(live_clients, 'Siemens Technology', 2,
                       start_date='2026-07-29')
    assert resp.status_code == 200, body.get('error') or body.get('message')
    for key, day in body['solution'].items():
        nonveg = [v['item_base'] for k, v in day['items'].items()
                  if k.startswith('nonveg_main')]
        has_biryani = any('biryani' in n for n in nonveg)
        if day['day_type'] == 'biryani':
            assert has_biryani, f"{key} is a biryani day but got {nonveg}"
        else:
            assert not has_biryani, (
                f"{key} is a {day['day_type']} day but got a biryani: {nonveg}"
            )


@pytest.mark.slow
def test_diagnose_reports_the_counter_it_was_asked_about(live_clients):
    """/diagnose must honour counter_index like /plan does.

    It used to build its inputs from the primary counter regardless, so every
    multi-counter client got a clean bill of health for counter 0 while the
    counter being planned was unsatisfiable.
    """
    from api.rate_limit import reset_for_tests
    seen = {}
    for idx in (0, 2):
        reset_for_tests()
        resp = live_clients.app.test_client().post('/api/v1/diagnose', json={
            'client_name': 'Amadeus', 'counter_index': idx,
            'start_date': '2026-07-27', 'num_days': 5,
        })
        body = resp.get_json()
        assert resp.status_code == 200, body
        seen[idx] = body['counter_name']
    assert seen[0] != seen[2], (
        f"/diagnose returned the same counter for both indexes: {seen}"
    )
    assert seen[2] == 'Chinese', seen
