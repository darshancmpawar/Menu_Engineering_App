"""DXC's client-specific logics, against real solves.

DXC is a Bangalore launch site with two counters (Veg Lunch, Non Veg Lunch)
that share the flavoured-rice / bread / curd rules, so those live at the
client level in `data/configs/client_rules.json`. The encoded logics:

* flavoured rice: biryani >= 3 days/week (even on non-biryani days), pulao >= 1,
  and no South-cuisine flavoured rice;
* Indian bread is plain chapati (`plain_chapatti` / `plain_phulka`) every day;
* curd side is raita Mon/Tue/Thu/Fri and plain curd on Wednesday.

Two Bangalore base rules had to be *disabled* for DXC, not overridden:
`mixedveg_pulao_biryani_weekly` (caps biryani+pulao at 1/week — contradicts the
3x+1x) and `curd_raita_logic` (forces raita on biryani/pulao days — collides
with the explicit weekday curd schedule). This test proves both counters plan
and every logic bites, and that week 2 stays feasible after week 1 is saved
(the plain-chapati staple would otherwise cool down to nothing).
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'      # ISO week 32, Monday
NEXT_MONDAY = '2026-08-10'
TIME_LIMIT = 30
WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri']

_THEME = {'monday': 'north', 'tuesday': 'north', 'wednesday': 'mix',
          'thursday': 'north', 'friday': 'mix'}

DXC = {
    'name': 'DXC', 'version': 1, 'city': 'Bangalore', 'serve_weekends': False,
    'item_cooldown_days': 20, 'source_pools': [], 'working_days': None,
    'is_launch_site': True,
    'counters': [
        {'name': 'Veg Lunch', 'theme_map': dict(_THEME),
         'categories': ['bread', 'rice', 'veg_dry', 'veg_gravy', 'sambar',
                        'rasam', 'dessert', 'curd_side', 'white_rice'],
         'slot_counts': {'rice': 1, 'bread': 1, 'rasam': 1, 'sambar': 1,
                         'dessert': 1, 'veg_dry': 1, 'curd_side': 1,
                         'veg_gravy': 1}},
        {'name': 'Non Veg Lunch', 'theme_map': dict(_THEME),
         'categories': ['bread', 'rice', 'sambar', 'rasam', 'dessert',
                        'curd_side', 'nonveg_main', 'white_rice'],
         'slot_counts': {'rice': 1, 'bread': 1, 'rasam': 1, 'sambar': 1,
                         'dessert': 1, 'curd_side': 1, 'nonveg_main': 1}},
    ],
}


@pytest.fixture(scope='module')
def _blr_df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Bangalore'))


@pytest.fixture
def api(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(DXC)],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _post(api, path, body):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api.app.test_client().post(path, json=body)


def _plan(api, counter_index, start=MONDAY):
    resp = _post(api, '/api/v1/plan', {
        'client_name': 'DXC', 'start_date': start, 'num_days': 5,
        'time_limit_sec': TIME_LIMIT, 'counter_index': counter_index})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['solution']


# --- attribute helpers, read straight off the ontology row ------------------

def _row(df, base):
    r = df[df['item'].astype(str).str.strip() == base]
    return None if r.empty else r.iloc[0]


def _flag(df, base, col):
    r = _row(df, base)
    return r is not None and pd.to_numeric(r.get(col), errors='coerce') == 1


def _attr(df, base, col):
    r = _row(df, base)
    return None if r is None else str(r.get(col)).strip()


def _by_slot(solution, base_slot):
    """weekday -> item_base for the (single) cell of base_slot that day."""
    out = {}
    for i, day in enumerate(solution.values()):
        items = day.get('items') or {}
        vals = [c['item_base'] for s, c in items.items()
                if s.split('__')[0] == base_slot]
        out[WEEKDAYS[i]] = vals[0] if vals else None
    return out


# --- both counters plan -----------------------------------------------------

@pytest.mark.parametrize('ci', [0, 1])
def test_counter_generates(api, ci):
    sol = _plan(api, ci)
    assert len(sol) == 5


@pytest.mark.parametrize('ci', [0, 1])
def test_diagnose_has_no_blocking_errors(api, ci):
    resp = _post(api, '/api/v1/diagnose', {
        'client_name': 'DXC', 'start_date': MONDAY, 'num_days': 5,
        'counter_index': ci})
    assert resp.status_code == 200
    errs = [d for d in (resp.get_json().get('rule_diagnostics') or [])
            if str(d.get('severity')).lower() == 'error']
    assert errs == [], errs


# --- flavoured-rice logic (both counters carry it) --------------------------

@pytest.mark.parametrize('ci', [0, 1])
def test_biryani_at_least_three_days(api, _blr_df, ci):
    rice = _by_slot(_plan(api, ci), 'rice')
    biryani = sum(1 for b in rice.values()
                  if b and _flag(_blr_df, b, 'is_mixedveg_biryani'))
    assert biryani >= 3, rice


@pytest.mark.parametrize('ci', [0, 1])
def test_pulao_at_least_once(api, _blr_df, ci):
    rice = _by_slot(_plan(api, ci), 'rice')
    pulao = sum(1 for b in rice.values()
                if b and _flag(_blr_df, b, 'is_pulao'))
    assert pulao >= 1, rice


@pytest.mark.parametrize('ci', [0, 1])
def test_no_south_flavoured_rice(api, _blr_df, ci):
    rice = _by_slot(_plan(api, ci), 'rice')
    south = [b for b in rice.values()
             if b and _attr(_blr_df, b, 'cuisine_family') == 'south_indian']
    assert south == [], south


# --- bread: plain chapati every day -----------------------------------------

@pytest.mark.parametrize('ci', [0, 1])
def test_plain_chapati_every_day(api, _blr_df, ci):
    bread = _by_slot(_plan(api, ci), 'bread')
    for wd, b in bread.items():
        assert b is not None, (wd, bread)
        assert _attr(_blr_df, b, 'sub_category') == 'plain_chapatti/phulka', \
            (wd, b)


# --- curd side: raita except Wednesday (plain curd) -------------------------

@pytest.mark.parametrize('ci', [0, 1])
def test_curd_side_raita_except_wednesday(api, _blr_df, ci):
    curd = _by_slot(_plan(api, ci), 'curd_side')
    for wd in ('mon', 'tue', 'thu', 'fri'):
        assert _flag(_blr_df, curd[wd], 'is_raita'), (wd, curd[wd])
    assert _flag(_blr_df, curd['wed'], 'is_plain_curd'), curd['wed']


# --- the plain-chapati staple survives into week 2 --------------------------

# --- cross-counter common categories (shared_items) -------------------------

SHARED = ['bread', 'rice', 'sambar', 'rasam', 'curd_side', 'dessert', 'white_rice']


def test_shared_categories_are_configured():
    from src.menu_rules import MenuRuleLoader
    assert MenuRuleLoader().get_shared_categories('DXC') == SHARED


def test_client_config_exposes_shared_categories(api):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    body = api.app.test_client().get('/api/v1/client-config/DXC').get_json()
    assert body['shared_categories'] == SHARED


def _by_slot_all(sol):
    """date -> {slot_id: item_base} for every cell."""
    out = {}
    for ds, day in sol.items():
        out[ds] = {sid: m['item_base'] for sid, m in day['items'].items()}
    return out


def test_common_categories_identical_across_counters(api):
    from ui.formatters import shared_items_from_solution
    sol0 = _plan(api, 0)
    shared = shared_items_from_solution(sol0, SHARED)
    assert shared, "primary counter produced no shared-category items"

    resp = _post(api, '/api/v1/plan', {
        'client_name': 'DXC', 'start_date': MONDAY, 'num_days': 5,
        'time_limit_sec': TIME_LIMIT, 'counter_index': 1,
        'shared_items': shared})
    assert resp.status_code == 200, resp.get_json()
    sol1 = resp.get_json()['solution']

    a, b = _by_slot_all(sol0), _by_slot_all(sol1)
    for ds in a:
        for sid, item in a[ds].items():
            if sid.split('__')[0] in SHARED and sid in b.get(ds, {}):
                assert b[ds][sid] == item, (ds, sid, item, b[ds][sid])


def test_sync_leaves_non_shared_slots_independent(api):
    """The non-veg counter still solves its own nonveg_main — the sync pins
    only the shared categories, not the whole counter."""
    from ui.formatters import shared_items_from_solution
    sol0 = _plan(api, 0)
    shared = shared_items_from_solution(sol0, SHARED)
    resp = _post(api, '/api/v1/plan', {
        'client_name': 'DXC', 'start_date': MONDAY, 'num_days': 5,
        'time_limit_sec': TIME_LIMIT, 'counter_index': 1,
        'shared_items': shared})
    sol1 = resp.get_json()['solution']
    nonveg = [m['item_base'] for day in sol1.values()
              for sid, m in day['items'].items()
              if sid.split('__')[0] == 'nonveg_main']
    assert len(nonveg) == 5  # one non-veg main each day, solved independently


def test_bread_still_feasible_in_week_two(api, _blr_df):
    sol1 = _plan(api, 0, start=MONDAY)
    week_plan = {ds: {sid: c['item'] for sid, c in day['items'].items()}
                 for ds, day in sol1.items()}
    saved = _post(api, '/api/v1/save', {
        'client_name': 'DXC', 'week_start': MONDAY, 'counter_index': 0,
        'week_plan': week_plan})
    assert saved.status_code == 200, saved.get_json()

    sol2 = _plan(api, 0, start=NEXT_MONDAY)
    bread = _by_slot(sol2, 'bread')
    for wd, b in bread.items():
        assert _attr(_blr_df, b, 'sub_category') == 'plain_chapatti/phulka', \
            (wd, b)
