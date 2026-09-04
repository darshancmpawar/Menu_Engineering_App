"""`POST /api/v1/explain` — the explanation of a plan the caller already has.

Its own endpoint rather than part of `/plan` because `/plan` is the slow path
and this is optional. The tests below are mostly about what must NOT happen: an
explanation that fails, or that goes quiet, must never be why a menu is not
served or why a relaxed rule stops being reported.

Relaxations are the one thing `/explain` cannot recompute — they are only
observable while the solver runs — so `/plan` collects them and hands them
back, and this endpoint takes them as input. The round trip is pinned here.
"""

from __future__ import annotations

import json

import pytest

from api.app import app, _rule_notes


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


PLAN_BODY = {
    'client_name': 'Rippling',
    'start_date': '2026-03-23',
    'num_days': 2,
    'time_limit_seconds': 30,
}


@pytest.fixture
def planned(client, fake_supabase):
    resp = client.post('/api/v1/plan', json=PLAN_BODY)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


class TestTheRoundTrip:
    def test_a_plan_can_be_explained(self, client, fake_supabase, planned):
        resp = client.post('/api/v1/explain',
                           json={**PLAN_BODY, 'solution': planned['solution']})
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body['success'] is True
        assert [d['date'] for d in body['days']] == sorted(planned['solution'])

    def test_every_day_carries_bullets_and_six_checks(
            self, client, fake_supabase, planned):
        """Bullets are the product with the model off, which is the default."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        for day in body['days']:
            assert day['bullets'], day['date']
            assert len(day['checks']) == 6
            assert day['prose'] is None
            assert day['llm_used'] is False
        assert body['llm_used'] is False

    def test_the_response_is_serialisable(self, client, fake_supabase, planned):
        """The pack carries numpy scalars out of the ontology DataFrame."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        json.dumps(body)

    def test_dishes_are_described_from_the_client_s_own_city(
            self, client, fake_supabase, planned):
        """A pack whose attrs came from the wrong city would silently report
        every dish as unknown — the plate would look emptier than it is."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        described = [d for day in body['days']
                     for d in day['plate_profile']['colour_spread']]
        assert described, 'no dish resolved against the ontology'


class TestRelaxationsSurvivetheRoundTrip:
    def test_plan_reports_relaxations_only_when_there_are_some(self, planned):
        """Absent rather than empty, so a clean plan's body is unchanged."""
        if 'relaxations' in planned:
            assert planned['relaxations']
            assert all({'rule', 'detail'} <= set(r)
                       for r in planned['relaxations'])

    def test_explain_attaches_what_plan_hands_back(
            self, client, fake_supabase, planned):
        relaxations = [{'rule': 'liquid_desserts_twice',
                        'detail': 'min 2 capped to 1', 'occurrences': 1}]
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution'],
            'relaxations': relaxations}).get_json()
        assert all(d['relaxations'] == relaxations for d in body['days'])

    def test_a_relaxation_is_always_rendered(
            self, client, fake_supabase, planned):
        """The point of the channel: a rule that did not hold must reach the
        reader, not be filtered out with the passing checks."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution'],
            'relaxations': [{'rule': 'r', 'detail': 'capped to 1'}]}).get_json()
        assert any('relaxed: r' in line
                   for line in body['days'][0]['bullets'])

    def test_junk_in_the_relaxations_field_is_ignored_not_fatal(
            self, client, fake_supabase, planned):
        resp = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution'],
            'relaxations': ['not a dict', 7, None]})
        assert resp.status_code == 200
        assert resp.get_json()['days'][0]['relaxations'] == []


class TestTheRefusals:
    def test_an_unknown_client_is_a_400(self, client, fake_supabase):
        resp = client.post('/api/v1/explain', json={
            'client_name': 'NonexistentClient999', 'solution': {'x': {}}})
        assert resp.status_code == 400

    @pytest.mark.parametrize('solution', [None, {}, [], 'x'])
    def test_a_missing_solution_is_a_400_not_a_500(
            self, client, fake_supabase, solution):
        """There is nothing to explain and no server fault; say so plainly."""
        resp = client.post('/api/v1/explain',
                           json={**PLAN_BODY, 'solution': solution})
        assert resp.status_code == 400
        assert 'solution' in resp.get_json()['error']

    def test_a_non_working_day_is_not_explained(
            self, client, fake_supabase, planned):
        """A blank column has no plate. Describing it would invent a menu."""
        solution = dict(planned['solution'])
        blanked = sorted(solution)[0]
        solution[blanked] = {**solution[blanked],
                             'is_working_day': False, 'items': {}}
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': solution}).get_json()
        assert blanked not in [d['date'] for d in body['days']]


class TestRuleNotes:
    def test_a_comment_is_attributed_to_its_slot(self):
        class _R:
            config = {'base_slot': 'bread', '_comment': 'chapati only'}
        assert _rule_notes([_R()]) == {'bread': 'chapati only'}

    def test_a_rule_spanning_slots_explains_no_single_dish(self):
        """`base_slot` as a LIST means "somewhere on the plate" (a protein in
        the rice, gravy, dry, salad *or* dal). Pinning that sentence to one
        dish would be a claim the config does not make."""
        class _R:
            config = {'base_slot': ['rice', 'dal'], '_comment': 'a protein'}
        assert _rule_notes([_R()]) == {}

    def test_a_rule_without_a_comment_contributes_nothing(self):
        class _R:
            config = {'base_slot': 'bread'}
        assert _rule_notes([_R()]) == {}

    def test_the_first_rule_naming_a_slot_wins(self):
        """Deterministic in config order — two sentences about one slot must
        not reorder between requests."""
        class _A:
            config = {'base_slot': 'bread', '_comment': 'first'}

        class _B:
            config = {'base_slot': 'bread', '_comment': 'second'}
        assert _rule_notes([_A(), _B()])['bread'] == 'first'

    def test_a_rule_stub_without_a_config_is_survivable(self):
        class _R:
            config = None

        class _Legacy:
            config = [{'name': 'x'}]        # the bare-list rule form
        assert _rule_notes([_R(), _Legacy(), None]) == {}
