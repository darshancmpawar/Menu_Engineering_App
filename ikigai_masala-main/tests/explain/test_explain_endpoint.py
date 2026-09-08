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

    def test_every_day_carries_bullets_and_the_calibrated_checks(
            self, client, fake_supabase, planned):
        """Bullets are the product with the model off, which is the default.

        Only the calibrated verdicts are rendered — an uncalibrated one spent
        on a chef's first look at the feature is the expensive kind of wrong.
        """
        from src.explain.checks import CALIBRATED

        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        for day in body['days']:
            assert day['bullets'], day['date']
            assert {c['name'] for c in day['checks']} == set(CALIBRATED)
            assert day['prose'] is None
            assert day['llm_used'] is False
        assert body['llm_used'] is False

    def test_all_checks_opts_back_in_to_the_uncalibrated_ones(
            self, client, fake_supabase, planned):
        """The calibration path still needs the numbers it is calibrating."""
        from src.explain.checks import ALL_CHECKS

        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution'],
            'all_checks': True}).get_json()
        assert len(body['days'][0]['checks']) == len(ALL_CHECKS)

    def test_colour_variety_is_judged_against_the_counter_s_own_target(
            self, client, fake_supabase, planned):
        """It mirrors a solver rule, so it must be handed the solver's number.

        Hardcoding 4 over a different dish set made it flag days that satisfied
        the rule which generated them — a false alarm the chef cannot act on,
        because acting would break that rule.
        """
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution'],
            'all_checks': True}).get_json()
        colour = [c for c in body['days'][0]['checks']
                  if c['name'] == 'colour_variety'][0]
        assert colour['evidence']['threshold'] <= colour['evidence']['configured_target']
        assert colour['evidence']['counted_dishes'] > 0

    def test_each_day_carries_the_plate_with_its_attributes(
            self, client, fake_supabase, planned):
        """The rendered menu table already has the dish NAMES. What the
        explanation adds is the colour and texture behind each verdict, so a
        reader can see why `texture_contrast` said what it said rather than
        taking it on trust — the UI's step 1 is empty without this."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        day = body['days'][0]
        assert day['dishes'], 'no plate in the response'
        described = [d for d in day['dishes'].values() if d.get('item_color')]
        assert described, 'no dish carries an attribute'
        for slot, dish in day['dishes'].items():
            assert dish['name']
            assert dish['slot'] == slot

    def test_every_day_says_what_complements_what(
            self, client, fake_supabase, planned):
        """The meal-level answer, which the per-dish `provenance` cannot give.

        Not gated by `calibrated_only`: a pairing is a statement about two
        recorded attribute values rather than a threshold verdict, so there is
        no threshold to be wrong about — and `gaps` is the honest half, which
        is exactly what must not be filtered away with the uncalibrated checks.
        """
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        for day in body['days']:
            pairings = day['pairings']
            assert pairings['summary'], day['date']
            assert isinstance(pairings['pairings'], list)
            assert isinstance(pairings['gaps'], list)
            on_plate = {d['name'] for d in day['dishes'].values()}
            for pair in pairings['pairings']:
                # Every dish named must be on this day's plate — that is what
                # lets the prose validator accept a paraphrase of these lines.
                assert set(pair['dishes']) <= on_plate, pair
                assert set(pair['slots']) <= set(day['dishes']), pair
                assert pair['detail'] and pair['kind']

    def test_the_pairings_reach_the_rendered_bullets(
            self, client, fake_supabase, planned):
        """The renderer is the permanent fallback with the model off, so a
        pairing that only exists in the JSON reaches nobody."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution']}).get_json()
        day = next(d for d in body['days'] if d['pairings']['pairings'])
        rendered = '\n'.join(day['bullets'])
        assert day['pairings']['pairings'][0]['detail'] in rendered

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

    def test_the_days_a_rule_was_relaxed_on_reach_the_reader(
            self, client, fake_supabase, planned):
        """A bare count is not actionable; the varying half is the point."""
        body = client.post('/api/v1/explain', json={
            **PLAN_BODY, 'solution': planned['solution'],
            'relaxations': [{'rule': 'r', 'detail': 'day 3 floor relaxed',
                             'occurrences': 3,
                             'samples': ['day 3 floor relaxed',
                                         'day 5 floor relaxed']}]}).get_json()
        rendered = '\n'.join(body['days'][0]['bullets'])
        assert 'day 5 floor relaxed' in rendered
        assert 'and 1 more like it' in rendered

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

    def test_a_long_developer_comment_is_cut_to_a_sentence(self):
        """`_comment` is not one kind of text. For `bread` it is the client's
        own sentence; for `nonveg_biryani_one_per_day` it is 400 characters of
        rationale about counting days versus dishes — true, useful to whoever
        edits the rule, and unreadable as the answer to "why is this biryani
        here". Cut on a sentence boundary so what a chef reads is a whole
        thought, and marked so nobody mistakes it for the full note."""
        from api.app import _NOTE_CHARS

        long = ('counts biryani DAYS rather than dishes, so a counter with two '
                'or more nonveg slots could otherwise satisfy the weekly cap by '
                'stacking two biryanis onto a single day and leaving the rest '
                'of the week without one at all. This caps the dishes per day. '
                'A third sentence nobody needs.')

        class _R:
            config = {'base_slot': 'nonveg_main', '_comment': long,
                      'name': 'nonveg_biryani_one_per_day'}
        note = _rule_notes([_R()])['nonveg_main']
        assert len(note) <= _NOTE_CHARS + 40      # + the rule-name prefix
        assert 'A third sentence' not in note
        assert note.endswith('…')

    def test_the_rule_name_leads_the_note(self):
        """Something short and identifiable first. "Biryani — nonveg biryani
        one per day" is actionable on its own; the rationale alone is not."""
        class _R:
            config = {'base_slot': 'bread', 'name': 'bread_chapati_only',
                      '_comment': 'client asks for chapati only'}
        assert _rule_notes([_R()])['bread'] == (
            'bread chapati only — client asks for chapati only')

    def test_a_short_client_sentence_is_left_whole(self):
        """The truncation must not chew the case it was written to protect."""
        class _R:
            config = {'base_slot': 'bread',
                      '_comment': 'client asks for a millet bread on south days'}
        assert (_rule_notes([_R()])['bread']
                == 'client asks for a millet bread on south days')

    def test_a_rule_stub_without_a_config_is_survivable(self):
        class _R:
            config = None

        class _Legacy:
            config = [{'name': 'x'}]        # the bare-list rule form
        assert _rule_notes([_R(), _Legacy(), None]) == {}
