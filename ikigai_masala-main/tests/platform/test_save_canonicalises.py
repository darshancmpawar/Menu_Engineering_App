"""`/save` stores the ontology's spelling, or says it could not.

`menu_history` is not a write-only log. Every subsequent plan reads it back —
the item cooldown (`banned_items_by_date`), the freshness objective
(`days_since_last_served`), the cross-week cadence rules
(`selector_banned_by_date`) and the week signatures — and each one compares the
STORED STRING against the ontology's `item` column. `ItemCooldownMenuRule` is
literally ``pool['item'].isin(banned)``.

`/save` used to store whatever it was handed. A plan produced by this client's
own `/plan` round-trips fine, because `item_base` IS the ontology spelling, so
nothing ever showed on the normal path. Anything else failed silently and in
the worst direction: a display name ("Dal Tadka") stored as `dal tadka` matches
no pool row, so the dish is never banned and never ages — the cooldown quietly
stops working for it, with no log line, no diagnostic, and a plausible menu
every week.

The tests split into the three claims that makes:

* a name that CAN be resolved is stored resolved, so the cooldown fires,
* a name that cannot is reported rather than swallowed,
* and neither case ever loses the plan.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tests.fake_supabase import FakeSupabase

CLIENT = 'Amadeus Pune'
MONDAY = '2026-08-03'


@pytest.fixture
def api(monkeypatch):
    import src.db as db_mod
    import api.app as api_app
    from tests.client_fixtures import CLIENTS

    row = next(dict(c) for c in CLIENTS if c['name'] == CLIENT)
    fake = FakeSupabase(seed={
        'clients': [row], 'app_settings': [],
        'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _post(api, path, body):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api.app.test_client().post(path, json=body)


def _a_real_pune_dish():
    """A dish the Pune list actually carries, read from the workbook."""
    import pandas as pd
    from src.ontology.paths import city_excel_path
    df = pd.read_excel(city_excel_path('Pune'))
    veg = df[df['course_type'].astype(str).str.strip().str.lower() == 'veg_dry']
    return str(veg['item'].iloc[0]).strip().lower()


def _saved_menu(api):
    """Every {slot: item} map `/save` actually wrote."""
    import src.db as db_mod
    rows = db_mod._sb_client._tables['menu_history']
    return [r['menu'] for r in rows]


def _save(api, plan, **extra):
    body = {'client_name': CLIENT, 'week_start': MONDAY, 'week_plan': plan}
    body.update(extra)
    return _post(api, '/api/v1/save', body)


class TestAResolvableNameIsStoredResolved:
    def test_a_display_name_is_stored_as_the_ontology_spells_it(self, api):
        """The fix. `"Bhindi Fry"` and `bhindi_fry` are the same dish, and only
        one of the two spellings will ever match a pool row."""
        dish = _a_real_pune_dish()
        display = dish.replace('_', ' ').title()
        assert display != dish

        r = _save(api, {MONDAY: {'veg_dry__1': display}})
        assert r.status_code == 200, r.get_json()
        assert _saved_menu(api) == [{'veg_dry__1': dish}]

    def test_the_solver_s_own_spelling_is_unchanged(self, api):
        """The normal path must be byte-for-byte what it was."""
        dish = _a_real_pune_dish()
        r = _save(api, {MONDAY: {'veg_dry__1': dish}})
        assert r.status_code == 200
        assert _saved_menu(api) == [{'veg_dry__1': dish}]

    def test_a_colour_suffix_is_still_stripped(self, api):
        """`strip_color_suffix` ran on the way in before and still has to —
        the resolution happens on the stripped name, not instead of it."""
        dish = _a_real_pune_dish()
        r = _save(api, {MONDAY: {'veg_dry__1': f'{dish} (R)'}})
        assert r.status_code == 200
        assert _saved_menu(api) == [{'veg_dry__1': dish}]

    def test_a_clean_save_says_nothing_extra(self, api):
        """A body that grew a warning key on every save would train the caller
        to ignore it."""
        body = _save(api, {MONDAY: {'veg_dry__1': _a_real_pune_dish()}}).get_json()
        assert body == {'success': True, 'message': 'Plan saved to history'}


class TestTheConsequenceItActuallyFixes:
    def test_a_display_name_save_now_bans_the_dish_next_week(self, api):
        """The whole point, asserted through the cooldown rather than through
        the stored string: save a dish under a display name, then check the
        item cooldown recognises it.

        Before the fix `banned_items_by_date` came back holding `bhindi fry`,
        which `pool['item'].isin(...)` never matches, so the dish stayed
        servable the next day and every day after."""
        from src.history.history_manager import HistoryManager

        dish = _a_real_pune_dish()
        _save(api, {MONDAY: {'veg_dry__1': dish.replace('_', ' ').title()}})

        # Read history back exactly as `_build_history_context` does.
        import src.db as db_mod
        rows = db_mod._sb_client._tables['menu_history']
        hm = HistoryManager().load_from_dataframes(
            HistoryManager.explode_history_rows(rows), None)
        banned = hm.banned_items_by_date(
            [dt.date.fromisoformat(MONDAY) + dt.timedelta(days=1)],
            cooldown_days=20,
        )
        got = set().union(*banned.values()) if banned else set()
        assert dish in got, sorted(got)[:5]

    def test_the_unresolved_name_is_the_one_that_would_not_have_banned(self):
        """Why the resolution matters, stated as arithmetic rather than as a
        solve: the cooldown compares the stored string against the ontology's
        `item` column, and a display name is not that string."""
        dish = _a_real_pune_dish()
        display = dish.replace('_', ' ').title()
        stored_unresolved = display.strip().lower()
        assert stored_unresolved != dish
        # `pool['item'].isin(banned)` — the pool holds `dish`, so a `banned`
        # set holding the display form matches nothing at all.
        assert dish not in {stored_unresolved}


class TestAnUnresolvableNameIsReportedNotSwallowed:
    def test_it_is_named_in_the_response(self, api):
        r = _save(api, {MONDAY: {'veg_dry__1': 'Definitely Not A Dish'}})
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        assert any('Definitely Not A Dish' in u
                   for u in body['unknown_items']), body

    def test_the_plan_is_still_saved(self, api):
        """Never rejected. A wrong cooldown is recoverable; a plan the user has
        just spent a solve generating is not — and an off-ontology
        `constant_items` pin is a real feature, so a strict save would break
        every client that has one."""
        r = _save(api, {MONDAY: {'veg_dry__1': 'Definitely Not A Dish'}})
        assert r.status_code == 200
        assert _saved_menu(api) == [{'veg_dry__1': 'definitely not a dish'}]

    def test_a_declared_constant_is_not_reported(self, monkeypatch):
        """A pin naming a dish the city deliberately does NOT carry is stamped
        verbatim post-solve (note 9) and reaches `/save` like any other dish.
        Flagging it would put a warning on every save for five real clients.

        Plan View is the sharpest case: it pins `boiled egg`, and Bangalore
        carries only `boiled_egg_with_pepper_masala`, a different dish — a pool
        gap that `test_constant_pin_targets.OFF_ONTOLOGY_ON_PURPOSE` records as
        deliberate."""
        import src.db as db_mod
        import api.app as api_app
        from tests.client_fixtures import CLIENTS

        client = 'Plan View'
        row = next(dict(c) for c in CLIENTS if c['name'] == client)
        monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed={
            'clients': [row], 'app_settings': [],
            'menu_history': [], 'week_signatures': [],
        }), raising=False)
        monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
        api_app.reset_caches()
        api_app.app.config['TESTING'] = True

        pinned = api_app._declared_constant_values(client)
        assert 'boiled egg' in pinned, sorted(pinned)

        from api.rate_limit import reset_for_tests
        reset_for_tests()
        r = api_app.app.test_client().post('/api/v1/save', json={
            'client_name': client, 'week_start': MONDAY,
            'week_plan': {MONDAY: {'nonveg_main__1': 'Boiled Egg'}},
        })
        assert r.status_code == 200, r.get_json()
        assert not r.get_json().get('unknown_items'), r.get_json()

    def test_the_pin_lookup_skips_documentation_keys(self):
        """`constant_items` carries `_comment` prose beside the pins (keys
        starting with `_` are documentation everywhere). Folding a paragraph
        into the allow-list would silence real warnings that happen to quote a
        dish name."""
        import api.app as api_app
        for client in ('Ather', 'Siemens', 'Booking.com'):
            for value in api_app._declared_constant_values(client):
                assert len(value) < 80, (client, value[:60])

    def test_the_guard_is_looking_at_something(self, api):
        """A resolvable name and an unresolvable one must not both come back
        clean, or the check is inert."""
        clean = _save(api, {MONDAY: {'veg_dry__1': _a_real_pune_dish()}})
        dirty = _save(api, {MONDAY: {'veg_dry__1': 'Definitely Not A Dish'}})
        assert not clean.get_json().get('unknown_items')
        assert dirty.get_json().get('unknown_items')


class TestTheMultiCounterPath:
    def test_both_paths_canonicalise(self, api):
        """`/save` has two bodies — `week_plan` and `counters` — and a fix in
        one of them is not a fix."""
        dish = _a_real_pune_dish()
        r = _post(api, '/api/v1/save', {
            'client_name': CLIENT, 'week_start': MONDAY,
            'counters': [{'name': 'Main',
                          'week_plan': {MONDAY: {'veg_dry__1':
                                                 dish.replace('_', ' ').title()}}}],
        })
        assert r.status_code == 200, r.get_json()
        # The multi-counter row nests one menu per counter.
        stored = [v for m in _saved_menu(api) for v in m['Main'].values()]
        assert stored == [dish], _saved_menu(api)

    def test_the_counter_is_named_in_the_report(self, api):
        r = _post(api, '/api/v1/save', {
            'client_name': CLIENT, 'week_start': MONDAY,
            'counters': [{'name': 'Main',
                          'week_plan': {MONDAY: {'veg_dry__1': 'Not A Dish'}}}],
        })
        assert any(u.startswith('Main/') for u in
                   r.get_json()['unknown_items']), r.get_json()


class TestItNeverBlocksASave:
    def test_an_ontology_failure_leaves_the_save_working(self, api, monkeypatch):
        """Validation is a courtesy on a write path. If the item list cannot be
        read, the save still happens — the alternative is losing a plan to a
        check that exists only to improve a later one."""
        import api.app as api_app
        monkeypatch.setattr(
            api_app._ontology, 'item_names',
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('boom')))
        r = _save(api, {MONDAY: {'veg_dry__1': 'Anything At All'}})
        assert r.status_code == 200
        assert _saved_menu(api)
