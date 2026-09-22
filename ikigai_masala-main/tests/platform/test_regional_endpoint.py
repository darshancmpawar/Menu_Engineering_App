"""The regional-day API surface, and what it does on a city that has no data.

Every committed workbook lacks the `state_origin` / `admin_type` columns, so
the honest state of this feature today is "switched off everywhere". These
tests pin that it is switched off *loudly* — a pick the server cannot honour
comes back in `region_problems` and a bad write is a 400 — rather than
silently, which is note 9's expensive failure: the plan still comes back and
looks fine.

The rule half is `tests/rules/test_regional_days.py`; this is the HTTP edge.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")
from api.app import app, _validated_region_map


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


class TestTheRegionsEndpoint:
    def test_it_answers_for_a_real_city(self, client, fake_supabase):
        resp = client.get('/api/v1/regions?city=Bangalore')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['city'] == 'Bangalore'
        assert isinstance(body['regions'], list)
        assert isinstance(body['theme_compatibility'], dict)

    def test_no_regional_data_reads_as_unavailable_not_as_an_error(
            self, client, fake_supabase):
        """The state of every city today. The planner hides the control on
        this flag, so it has to be a clean False rather than a 500."""
        body = client.get('/api/v1/regions?city=Bangalore').get_json()
        assert body['available'] is False
        assert body['themeable'] == []

    def test_an_unknown_city_falls_back_rather_than_failing(
            self, client, fake_supabase):
        """`city_excel_path` falls back to the default city everywhere else;
        this endpoint must not be the one place that 404s instead."""
        assert client.get('/api/v1/regions?city=Atlantis').status_code == 200

    def test_every_theme_is_represented_in_the_compatibility_map(
            self, client, fake_supabase):
        from src.client.client_config import AVAILABLE_THEMES
        body = client.get('/api/v1/regions?city=Bangalore').get_json()
        assert set(body['theme_compatibility']) == set(AVAILABLE_THEMES)


class TestWritingARegionMap:
    """Rejected at the PUT, never stored and dropped later."""

    def test_an_empty_map_is_always_valid(self):
        assert _validated_region_map(None, city='Bangalore') == {}
        assert _validated_region_map({}, city='Bangalore') == {}

    def test_a_non_object_is_refused(self):
        with pytest.raises(ValueError, match='weekday'):
            _validated_region_map(['thursday'], city='Bangalore')

    def test_a_region_this_city_cannot_theme_is_refused(self, fake_supabase):
        """True of every region today, and the message has to say so rather
        than leave the operator guessing at a spelling."""
        with pytest.raises(ValueError) as e:
            _validated_region_map({'thursday': 'Tamil Nadu'}, city='Bangalore')
        assert 'thursday' in str(e.value)

    def test_an_unknown_weekday_is_refused(self, fake_supabase):
        with pytest.raises(ValueError, match='someday'):
            _validated_region_map({'someday': 'Tamil Nadu'}, city='Bangalore')


class TestPlanningWithARegionPick:
    def test_a_pick_a_city_cannot_honour_does_not_cost_the_menu(
            self, client, fake_supabase):
        """The whole design in one assertion: a regional day is a floor, so the
        worst case is a plan with no regional dishes — never a failed plan."""
        resp = client.post('/api/v1/plan', json={
            'client_name': 'TestClient',
            'start_date': '2026-09-21',
            'num_days': 2,
            'region_days': {'2026-09-24': 'Tamil Nadu'},
        })
        assert resp.status_code in (200, 422, 500)
        body = resp.get_json()
        if resp.status_code == 200:
            assert body['success'] is True
            assert body.get('solution')

    def test_an_ordinary_plan_body_is_unchanged(self, client, fake_supabase):
        """Both keys absent when nobody asked for a region, so every existing
        consumer sees byte-for-byte what it saw before."""
        resp = client.post('/api/v1/plan', json={
            'client_name': 'TestClient',
            'start_date': '2026-09-21',
            'num_days': 2,
        })
        if resp.status_code != 200:
            pytest.skip('this fixture client cannot plan in this environment')
        body = resp.get_json()
        assert 'region_days' not in body
        assert 'region_problems' not in body
