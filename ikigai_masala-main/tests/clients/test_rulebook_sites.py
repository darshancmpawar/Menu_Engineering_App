"""The five rulebook sites, against real solves on the LIVE client rows.

Carelon, Corning and SAEL (NCR) and PhonePe and ChrysCapital Advisors (Pune)
were wired from the client's rulebook. The config-validity guards already check
that every rule names a real target and every pin a real slot, and the fleet
sweep checks each counter still generates. Neither catches the failure this file
exists for: **a rule that loads, solves and reports satisfied while selecting
something other than what the client meant.**

Both of PhonePe's did, on the first plan its config produced:

* "3 days rice 2 day pulao" was written against `is_pulao`, which Pune sets on
  10 of its 110 rices while 47 of them are pulaos — so the menu served three and
  the rule was satisfied.
* "Welcome drink 1 is non dairy" was left out as trivially true, and a
  `masala_milk` promptly turned up in a drink cell. Pune files it
  `drink_rule_group: fruit_drink`.

So these assert the OUTCOME on the plate, by the same reading the client used,
rather than that a rule object exists. Read against the live `clients` rows, not
a hand-built counter, because a rule is only as configured as the row it runs on.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tests.client_fixtures import APP_SETTINGS, CLIENTS
from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'          # a Monday, so Mon-Fri needs no weekend logic
TIME_LIMIT = 60


@pytest.fixture
def api(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS],
        'app_settings': [dict(s) for s in APP_SETTINGS],
        'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _plan(api, name, days=5):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api.app.test_client().post('/api/v1/plan', json={
        'client_name': name, 'counter_index': 0, 'start_date': MONDAY,
        'num_days': days, 'time_limit_seconds': TIME_LIMIT})
    body = resp.get_json() or {}
    assert resp.status_code == 200, body.get('error') or body.get('message')
    return body['solution']


def _by_weekday(solution, slot):
    """``{'mon': item, ...}`` for *slot*, absent days left out."""
    out = {}
    for date, day in sorted(solution.items()):
        entry = day['items'].get(slot)
        if entry:
            key = dt.date.fromisoformat(date).strftime('%a').lower()
            out[key] = str(entry['item_base']).strip().lower()
    return out


def _matches(city, slot, names, selector):
    """How many of *names* in *slot* match *selector*, by the rule's own code."""
    from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
    from src.ontology.repository import OntologyRepository
    _df, pools = OntologyRepository().filtered_menu_data(city, [])
    rows = {str(r['item']).strip().lower(): r for _i, r in pools[slot].iterrows()}
    matcher = SelectorFrequencyRule._parse_matcher(selector)
    return [n for n in names if n in rows
            and SelectorFrequencyRule._matches(rows[n], matcher)]


# --- the two that were measured wrong -------------------------------------

def test_phonepe_serves_exactly_two_pulaos(api):
    """'3 days rice 2 day pulao', counted the way a diner would: by what is
    actually a pulao, not by the flag. This is the assertion that failed when
    the rule selected on `is_pulao` alone."""
    rice = list(_by_weekday(_plan(api, 'PhonePe'), 'rice').values())
    pulao = _matches('Pune', 'rice', rice,
                     {'any_of': [{'flag': 'is_pulao'},
                                 {'name_contains': ['pulao']}]})
    assert len(pulao) == 2, (pulao, rice)


def test_phonepe_never_serves_two_dairy_drinks_in_a_day(api):
    """'Welcome drink 1 is non dairy' on a two-drink counter. Dairy by flag OR
    name: `drink_rule_group` files `masala_milk` and `badam_milk` as
    `fruit_drink`, so it cannot answer this."""
    solution = _plan(api, 'PhonePe')
    dairy = {'any_of': [{'flag': 'is_buttermilk'}, {'flag': 'is_lassi'},
                        {'name_contains': ['milk', 'lassi', 'shake', 'badam',
                                           'taak', 'chaas']}]}
    for date, day in solution.items():
        drinks = [str(e['item_base']).strip().lower()
                  for s, e in day['items'].items()
                  if s.startswith('welcome_drink') and e]
        assert len(_matches('Pune', 'welcome_drink', drinks, dairy)) <= 1, \
            (date, drinks)


# --- the weekday splits, which are the rest of the rulebook ----------------

def test_phonepe_nonveg_is_chicken_gravy_or_egg_gravy_by_weekday(api):
    """'noveg 1 will serve chicken gravy on mon,wed,frid and egg gravy on tue
    and tursday.' Cell 1 only — 2 and 3 are the boiled staples."""
    first = _by_weekday(_plan(api, 'PhonePe'), 'nonveg_main__1')
    chicken = {'all_of': [{'primary_protein': 'chicken'},
                          {'flag': 'is_nonveg_gravy'}]}
    egg = {'all_of': [{'flag': 'is_egg_dish'}, {'flag': 'is_nonveg_gravy'}]}
    for day in ('mon', 'wed', 'fri'):
        assert _matches('Pune', 'nonveg_main', [first[day]], chicken), \
            (day, first[day])
    for day in ('tue', 'thu'):
        assert _matches('Pune', 'nonveg_main', [first[day]], egg), \
            (day, first[day])


def test_phonepe_boiled_staples_are_on_every_day(api):
    """'Non Veg 2 & 3 will serve Boiled egg and boiled chicken daily as
    staple.' Pune carries neither dish, so both are stamped verbatim — which is
    the right printed menu and the wrong thing for every other rule to see.
    Asserted so that adding the two rows (which turns these into solved cells)
    is a visible change rather than a silent one."""
    solution = _plan(api, 'PhonePe')
    assert set(_by_weekday(solution, 'nonveg_main__2').values()) == {'boiled egg'}
    assert set(_by_weekday(solution, 'nonveg_main__3').values()) == {'boiled chicken'}


def test_phonepe_bread_is_chapati_or_paratha_by_weekday(api):
    """'indian bread will serve chapati as staple on mon,wed and fri . Then tue
    and thur will serve paratas'."""
    bread = _by_weekday(_plan(api, 'PhonePe'), 'bread')
    plain = {'flag': 'is_plain_phulka_chapathi'}
    paratha = {'any_of': [{'sub_category': 'flavoured_paratha'},
                          {'sub_category': 'tandoor'},
                          {'sub_category': 'thepla'}]}
    for day in ('mon', 'wed', 'fri'):
        assert _matches('Pune', 'bread', [bread[day]], plain), (day, bread[day])
    for day in ('tue', 'thu'):
        assert _matches('Pune', 'bread', [bread[day]], paratha), (day, bread[day])


@pytest.mark.parametrize('client,city,white_days', [
    ('SAEL', 'NCR', {'wed'}),
    ('Corning', 'NCR', {'thu'}),
    ('ChrysCapital Advisors', 'Pune', {'tue'}),
    ('Carelon', 'NCR', {'mon', 'thu', 'sat'}),
])
def test_exactly_one_carb_a_day(api, client, city, white_days):
    """'when white rice is there there is not flavour rice and vice verse',
    which is in four of the five sheets. The DAYS are a choice (each config's
    `_comment` says which sample week they came from); what the client stated
    and this asserts is that the two never share a day and never both miss one.
    """
    days = 7 if client == 'Carelon' else 5
    solution = _plan(api, client, days=days)
    white = set(_by_weekday(solution, 'white_rice'))
    flavour = set(_by_weekday(solution, 'rice'))
    assert white == white_days, white
    assert not (white & flavour), white & flavour
    assert white | flavour == set(_by_weekday(solution, 'dal')), (
        'a day with neither carb')


@pytest.mark.parametrize('client', ['SAEL', 'Corning', 'Carelon'])
def test_the_curd_side_is_always_a_raita(api, client):
    """'only different types of raita will be served', in all three NCR sheets.
    NCR's two plain curds are what this keeps out; the item cooldown supplies
    the 'different types' half."""
    days = 7 if client == 'Carelon' else 5
    served = list(_by_weekday(_plan(api, client, days=days), 'curd_side').values())
    assert served
    assert len(_matches('NCR', 'curd_side', served, {'flag': 'is_raita'})) == \
        len(served), served


def test_sael_serves_one_veg_dish_a_day_on_the_stated_days(api):
    """'veg dry will be given on Mon,wed, Friday' + 'Veg Gravy on tue and
    thurday' + 'veg dry and Veg Gravy cant come together'. The counter's row
    declares both slots daily, so this is the pair of day restrictions doing the
    third rule's work."""
    solution = _plan(api, 'SAEL')
    assert set(_by_weekday(solution, 'veg_dry')) == {'mon', 'wed', 'fri'}
    assert set(_by_weekday(solution, 'veg_gravy')) == {'tue', 'thu'}


def test_carelon_serves_no_nonveg_on_tuesday_or_saturday(api):
    """'no non veg on Tue and sat' — the only weekday rule in the sheet that is
    about absence, and the counter runs seven days."""
    served = set(_by_weekday(_plan(api, 'Carelon', days=7), 'nonveg_main'))
    assert not (served & {'tue', 'sat'}), served
    assert served == {'mon', 'wed', 'thu', 'fri', 'sun'}


def test_carelon_serves_the_tawa_roti_and_a_flavoured_bread(api):
    """'2 indian breads. One will be tawa roti staple and other will be a
    flavour roti or parata.' The wide reading of "flavour roti or parata" is
    deliberate and measured — the narrow one carries only brown and green
    dishes and made the counter INFEASIBLE from six days on.

    The pin reads `tawa roti` and comes back `tawa_roti`, which is the point:
    NCR carries that row, so the pin NARROWS a real cell and every other rule
    still sees the dish. Contrast PhonePe's `boiled egg` above, which comes back
    exactly as written because Pune has no such row."""
    solution = _plan(api, 'Carelon', days=7)
    assert set(_by_weekday(solution, 'bread__1').values()) == {'tawa_roti'}
    second = list(_by_weekday(solution, 'bread__2').values())
    flavoured = {'any_of': [{'sub_category': s} for s in (
        'flavoured_paratha', 'layered_paratha', 'fat-enriched_chapatti',
        'leafy_/_herb_chapatti', 'tandoor', 'stuffed_veg_paratha',
        'spice_chapatti', 'veg_/_fruit_chapatti', 'thepla')]}
    assert len(_matches('NCR', 'bread', second, flavoured)) == len(second), second
