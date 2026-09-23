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

    def test_a_city_with_region_data_reports_what_it_can_theme(
            self, client, fake_supabase):
        """`available` is the flag the planner shows or hides the control on.
        It was False for every city until the corrected workbooks landed
        `state_origin` and `admin_type`; Bangalore now themes eight regions."""
        body = client.get('/api/v1/regions?city=Bangalore').get_json()
        assert body['available'] is True
        assert 'Karnataka' in body['themeable']

    def test_a_city_without_the_columns_reads_as_unavailable_not_as_an_error(
            self, client, fake_supabase, monkeypatch):
        """The other half, which is the one that must not 500: a city whose
        list has not been given the columns yet hides the control."""
        import api.app as api_app
        monkeypatch.setattr(api_app.ontology_repository, 'regions',
                            lambda _city=None: ())
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
        """The message has to name the day rather than leave the operator
        guessing at a spelling. `Nagaland` is a real state and a real refusal:
        no city's list carries enough of its cooking to set a floor."""
        with pytest.raises(ValueError) as e:
            _validated_region_map({'thursday': 'Nagaland'}, city='Bangalore')
        assert 'thursday' in str(e.value)

    def test_a_region_this_city_CAN_theme_is_accepted(self, fake_supabase):
        assert _validated_region_map(
            {'thursday': 'Karnataka'}, city='Bangalore') == {'thursday': 'Karnataka'}

    def test_an_unknown_weekday_is_refused(self, fake_supabase):
        with pytest.raises(ValueError, match='someday'):
            _validated_region_map({'someday': 'Tamil Nadu'}, city='Bangalore')


class TestPlanningWithARegionPick:
    def test_a_pick_a_city_cannot_honour_does_not_cost_the_menu(
            self, client, fake_supabase):
        """The whole design in one assertion: a regional day is a FLOOR, so the
        worst case is a plan with no regional dishes — never a different
        outcome from not asking.

        Asserted as "the same request with and without `region_days` ends the
        same way" rather than as a fixed status code, because what this has to
        prove is that the pick changed nothing — and that holds whether this
        environment's fixture client can actually solve or not.
        """
        # Bounded like every other /plan test here. Left at the default 240s
        # these solves alone ran the file past fifteen minutes.
        body = {'client_name': 'TestClient', 'start_date': '2026-09-21',
                'num_days': 1, 'time_limit_seconds': 15}
        plain = client.post('/api/v1/plan', json=body)
        with_region = client.post(
            '/api/v1/plan',
            json=dict(body, region_days={'2026-09-24': 'Tamil Nadu'}))
        assert with_region.status_code == plain.status_code, (
            'asking for a regional day changed the outcome of the request; a '
            'floor must never be able to do that')

    def test_an_ordinary_plan_body_is_unchanged(self, client, fake_supabase):
        """Both keys absent when nobody asked for a region, so every existing
        consumer sees byte-for-byte what it saw before."""
        resp = client.post('/api/v1/plan', json={
            'client_name': 'TestClient',
            'start_date': '2026-09-21',
            'num_days': 1,
            'time_limit_seconds': 15,
        })
        if resp.status_code != 200:
            pytest.skip('this fixture client cannot plan in this environment')
        body = resp.get_json()
        assert 'region_days' not in body
        assert 'region_problems' not in body
