"""Breakfast as a session of the city list (owner, 2026-11-17).

Every row carries a `session` ("lunch,dinner" or "breakfast"); a solve sees
only its session's rows; the editor offers a breakfast service breakfast rows
only; a snacks service is refused with a message, since no row serves it yet.
"""

import json

import pandas as pd
import pytest

from src.constants import BREAKFAST_ONLY_SLOTS, BREAKFAST_SLOTS, SNACKS_NOT_READY
from src.ontology.repository import OntologyRepository, _session_rows
from tests.fake_supabase import FakeSupabase


def test_session_rows_read_the_comma_list():
    df = pd.DataFrame({'item': ['a', 'b', 'c'],
                       'session': ['lunch,dinner', 'breakfast', ' Lunch , dinner ']})
    assert list(_session_rows(df, 'lunch')['item']) == ['a', 'c']
    assert list(_session_rows(df, 'dinner')['item']) == ['a', 'c']
    assert list(_session_rows(df, 'breakfast')['item']) == ['b']
    assert _session_rows(df, 'snacks').empty
    assert len(_session_rows(df.drop(columns='session'), 'breakfast')) == 3


@pytest.fixture(scope='module')
def repo():
    return OntologyRepository()


def test_bangalore_sessions_split_the_list(repo):
    full = repo.all_rows('Bangalore')
    lunch, _ = repo.menu_data('Bangalore', 'lunch')
    breakfast, pools = repo.menu_data('Bangalore', 'breakfast')
    assert set(full['session']) == {'lunch,dinner', 'breakfast'}
    assert len(lunch) + len(breakfast) == len(full)
    assert set(breakfast['session']) == {'breakfast'}
    for slot in BREAKFAST_ONLY_SLOTS:
        assert len(pools[slot]), slot
    # The Sandwich row is veg; the non-veg half is its own row.
    nonveg = repo.nonveg_items('Bangalore')
    assert not set(pools['sandwich']['item']) & nonveg
    assert set(pools['nonveg_sandwich']['item']) <= nonveg
    every = set(breakfast.loc[breakfast['course_type'] == 'sandwich', 'item'])
    assert set(pools['sandwich']['item']) | set(pools['nonveg_sandwich']['item']) == every
    # Lunch never sees a breakfast-only course.
    _, lunch_pools = repo.menu_data('Bangalore')
    assert not len(lunch_pools['breakfast_main'])


@pytest.mark.parametrize('city', ['Chennai', 'Hyderabad', 'NCR', 'Pune'])
def test_other_cities_serve_lunch_and_dinner(repo, city):
    assert set(repo.all_rows(city)['session']) == {'lunch,dinner'}


def test_editor_offers_each_service_its_own_rows():
    from customisation.main import categories_for_meal
    from src.constants import BASE_SLOT_NAMES, CONST_SLOTS
    base, const = categories_for_meal('breakfast', BASE_SLOT_NAMES, CONST_SLOTS)
    assert set(base) == BREAKFAST_SLOTS and const == []
    base, const = categories_for_meal('dinner', BASE_SLOT_NAMES, CONST_SLOTS)
    assert not set(base) & set(BREAKFAST_ONLY_SLOTS) and const == CONST_SLOTS


CLIENT = {
    'name': 'Breakfast Test', 'version': 1, 'city': 'Bangalore',
    'serve_weekends': False, 'item_cooldown_days': 21, 'source_pools': [],
    'working_days': None, 'is_launch_site': False, 'shared_categories': [],
    'meals': ['breakfast'],
    'counters': [{
        'name': 'Counter 1',
        'theme_map': {d: 'mix' for d in
                      ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')},
        'categories': ['beverage', 'breakfast_main', 'breakfast_chutney',
                       'sandwich', 'nonveg_sandwich', 'fruit', 'side'],
        'slot_counts': {}}],
}


def _post(meal):
    mp = pytest.MonkeyPatch()
    import src.db as db_mod
    mp.setattr(db_mod, '_sb_client', FakeSupabase(seed={
        'clients': [json.loads(json.dumps(CLIENT))], 'app_settings': [],
        'menu_history': [], 'week_signatures': []}), raising=False)
    import api.app as api_app
    mp.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    try:
        return api_app.app.test_client().post('/api/v1/plan', json={
            'client_name': CLIENT['name'], 'start_date': '2026-08-03',
            'num_days': 5, 'time_limit_sec': 30, 'meal': meal})
    finally:
        mp.undo()


def test_a_breakfast_plan_serves_breakfast_dishes_only(repo):
    resp = _post('breakfast')
    assert resp.status_code == 200, resp.get_json()
    breakfast = set(repo.menu_data('Bangalore', 'breakfast')[0]['item'])
    served = [c['item_base'] for d in resp.get_json()['solution'].values()
              for c in (d.get('items') or {}).values()]
    assert len(served) == 5 * 7
    assert set(served) <= breakfast


def test_a_snacks_plan_is_refused_with_the_message():
    resp = _post('snacks')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == SNACKS_NOT_READY
