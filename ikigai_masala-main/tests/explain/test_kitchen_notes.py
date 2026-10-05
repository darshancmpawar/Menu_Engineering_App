"""Kitchen notes for the seasonal list, the endpoint behind the panel, and its helpers.

The notes are model-written but must stay true: dishes from this week's menu,
swaps from the safe alternatives, red-list vegetables only ever "left out", the
sheet's instructions kept, every clashing pin covered. When the model is off,
unreachable or keeps failing, the kitchen gets the sheet's notes instead.
"""
import datetime as dt
import json

import pytest

import api.explain_llm as llm
import api.kitchen_notes_llm as kn
from src.seasonal.bans import bans_for
from ui.formatters import seasonal_dishes_by_date, seasonal_label

OCT = bans_for('Bangalore', dt.date(2026, 10, 26))
PINNED = [{'dish': 'green_salad', 'slot': 'salad', 'vegetables': ['Lettuce']}]
DAYS = [{'day': 'Mon 26 Oct', 'dishes': [{'name': 'avial', 'slot': 'veg_gravy', 'key_ingredient': 'mixed_vegetables'},
                                         {'name': 'green_salad', 'slot': 'salad', 'key_ingredient': 'lettuce'}]},
        {'day': 'Wed 28 Oct', 'dishes': [{'name': 'tomato_rice', 'slot': 'rice', 'key_ingredient': 'tomato'}]}]
MENU = ['avial', 'green_salad', 'tomato_rice']
CITY = ['avial', 'green_salad', 'tomato_rice', 'dal_makhani', 'subz_jalfrezi']

GOOD = {'notes': [
    {'when': 'Mon', 'dish': 'avial', 'text': 'Avial: no cucumber or brinjal this month. Raw banana, ash gourd and carrot carry it.'},
    {'when': 'Wed', 'dish': 'tomato rice', 'text': 'Tomato rice: make it with tomato purée, not whole tomatoes.'},
    {'when': 'All week', 'dish': None, 'text': 'Salads: English cucumber only, never Indian cucumber.'},
    {'when': 'Pinned', 'dish': 'green salad', 'text': 'Green salad: build it on carrot, radish and beetroot instead of lettuce.'}],
    'swaps': [{'dish': 'avial', 'leave_out': ['cucumber', 'brinjal'], 'use': ['raw banana', 'ash gourd', 'carrots']},
              {'dish': 'green salad', 'leave_out': ['lettuce'], 'use': ['carrots', 'radish', 'beetroot']}]}


def _with(**changes):
    reply = json.loads(json.dumps(GOOD))
    reply.update(changes)
    return reply


def _problems(reply):
    facts = kn.build_facts(OCT, DAYS, PINNED)
    return kn.check(reply, facts, OCT, MENU, CITY)


class TestChecks:
    def test_the_good_draft_passes(self):
        assert _problems(GOOD) == []

    def test_a_swap_from_the_yellow_list_is_rejected(self):
        bad = _with(swaps=GOOD['swaps'] + [{'dish': 'avial', 'use': ['beans']}])
        assert any('red or yellow list' in p for p in _problems(bad))

    def test_a_swap_outside_the_alternatives_is_rejected(self):
        bad = _with(swaps=[{'dish': 'avial', 'use': ['zucchini']}])
        assert any('not in the safe alternatives' in p for p in _problems(bad))

    def test_a_red_vegetable_mentioned_as_an_ingredient_is_rejected(self):
        notes = GOOD['notes'][1:] + [{'when': 'Mon', 'dish': 'avial', 'text': 'Avial: add cabbage for crunch.'}]
        assert any('without saying to leave it out' in p for p in _problems(_with(notes=notes)))

    def test_english_cucumber_follows_the_sheet(self):
        """Cucumber is red in October, but the sheet itself says to use English cucumber."""
        assert not any('cucumber' in p and 'leave it out' in p for p in _problems(GOOD))

    def test_an_off_menu_dish_is_rejected_in_any_casing(self):
        notes = GOOD['notes'] + [{'when': 'Tue', 'dish': None, 'text': 'Serve dal makhani with the rice.'}]
        assert any('dal makhani' in p for p in _problems(_with(notes=notes)))

    def test_the_sheet_instruction_must_survive(self):
        notes = [n for n in GOOD['notes'] if 'purée' not in n['text']]
        assert any('tomato purée' in p for p in _problems(_with(notes=notes)))

    def test_a_clashing_pin_must_get_a_note(self):
        notes = [n for n in GOOD['notes'] if n['when'] != 'Pinned']
        swaps = [s for s in GOOD['swaps'] if s['dish'] != 'green salad']
        assert any('Pinned dish' in p for p in _problems(_with(notes=notes, swaps=swaps)))

    def test_health_claims_are_rejected(self):
        notes = GOOD['notes'] + [{'when': 'All week', 'dish': None, 'text': 'Keeps the menu healthy.'}]
        assert any('health' in p for p in _problems(_with(notes=notes)))


class TestDeterministic:
    def test_without_a_model_the_kitchen_gets_the_sheet(self):
        notes = kn.deterministic_notes(OCT, PINNED)
        texts = [n['text'] for n in notes]
        assert texts[:2] == list(OCT.notes)
        assert kn.MIXED_VEG_LINE in texts
        assert any(n['pinned'] and 'without lettuce' in n['text'] for n in notes)


@pytest.fixture
def model(monkeypatch):
    kn.reset_cache_for_tests()
    monkeypatch.setattr(llm, 'API_KEY', 'test-key')
    calls = []

    def script(replies):
        def fake(system, contents, **kw):
            calls.append(contents)
            r = replies[min(len(calls), len(replies)) - 1]
            return r if (r is None or isinstance(r, str)) else json.dumps(r)
        monkeypatch.setattr(llm, '_post_model', fake)
        return calls
    return script


class TestLoop:
    def test_no_menu_means_sheet_notes_and_no_call(self, model):
        calls = model([GOOD])
        out = kn.kitchen_notes(OCT, [{'day': 'Mon', 'dishes': []}], PINNED)
        assert out['source'] == 'sheet' and not calls

    def test_a_good_draft_is_used(self, model):
        model([GOOD])
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert out['source'] == 'model' and out['reason'] == 'ok'
        assert any(n['pinned'] for n in out['notes'])

    def test_problems_go_back_then_the_fix_is_used(self, model):
        calls = model([_with(swaps=[{'dish': 'avial', 'use': ['beans']}]), GOOD])
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert out['source'] == 'model' and out['attempts'] == 2
        assert 'beans' in calls[1][-1]['parts'][0]['text']

    def test_repeated_failure_falls_back_to_the_sheet(self, model):
        model([_with(swaps=[{'dish': 'avial', 'use': ['beans']}])])
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert out['source'] == 'sheet' and out['reason'].startswith('rejected after')
        assert [n['text'] for n in out['notes']][:2] == list(OCT.notes)

    def test_a_transport_blip_spends_an_attempt_instead_of_the_notes(self, model):
        """Same rule as the chef's read, for the same measured reason: about
        1 call in 15 read-times-out, and returning on the first one threw away
        two unused attempts. The quota a retry would "waste" was already spent
        on the call that failed."""
        calls = model([None, GOOD])
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert out['source'] == 'model' and len(calls) == 2
        assert out['problems_by_attempt'][0] == ['no reply from the model (network)']

    def test_repeated_transport_failure_stays_inside_the_ceiling(self, model):
        calls = model([None])
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert len(calls) == kn.KITCHEN_NOTES_MAX_ATTEMPTS
        assert out['source'] == 'sheet' and out['reason'].startswith('model unavailable')
        assert [n['text'] for n in out['notes']][:2] == list(OCT.notes)

    def test_a_missing_key_does_not_retry(self, model, monkeypatch):
        """The one failure that repeats on purpose — along with a 429 — so it
        stops at once rather than spending the budget to learn the same thing."""
        monkeypatch.setattr(kn.llm, 'API_KEY', '')
        calls = model([GOOD])
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert out['source'] == 'sheet' and not calls

    def test_accepted_notes_are_cached(self, model):
        calls = model([GOOD])
        kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        out = kn.kitchen_notes(OCT, DAYS, PINNED, city_dish_names=CITY)
        assert out['reason'] == 'cache' and len(calls) == 1


class TestPanelHelpers:
    def test_dishes_are_pooled_across_blocks_once_per_slot(self):
        blocks = [{'solution': {'2026-10-26': {'items': {'salad': {'item_base': 'green_salad'},
                                                         'veg_gravy': {'item_base': 'avial'}}}}},
                  {'solution': {'2026-10-26': {'items': {'salad__1': {'item_base': 'green_salad'},
                                                         'rice': {'item_base': 'tomato_rice'}}}}}]
        out = seasonal_dishes_by_date(blocks)
        assert out == {'2026-10-26': [{'name': 'green_salad', 'slot': 'salad'},
                                      {'name': 'avial', 'slot': 'veg_gravy'},
                                      {'name': 'tomato_rice', 'slot': 'rice'}]}

    def test_label_names_the_months(self):
        assert seasonal_label(['2026-10-26', '2026-10-30']) == 'Seasonal vegetable list · October 2026'
        assert seasonal_label(['2026-10-30', '2026-11-02']) == 'Seasonal vegetable list · October and November 2026'


class TestEndpoint:
    @pytest.fixture
    def client(self, fake_supabase):
        # Amadeus: a Bangalore site that pins a lettuce green salad.
        from tests.client_fixtures import CLIENTS
        fake_supabase.seed('clients', [dict(next(c for c in CLIENTS if c['name'] == 'Amadeus'))])
        from api.app import app
        app.config['TESTING'] = True
        with app.test_client() as c:
            yield c

    BODY = {'client_name': 'Amadeus', 'start_date': '2026-10-26', 'num_days': 5}

    def test_lists_pins_and_sheet_notes_before_a_menu(self, client, model):
        calls = model([GOOD])
        body = client.post('/api/v1/seasonal-bans', json=self.BODY).get_json()
        assert body['success'] is True
        m = body['months'][0]
        assert m['label'] == 'October 2026' and m['region'] == 'Karnataka'
        assert m['red'][0]['label'] == 'Cabbage' and m['removed'] > 300
        assert any(p['dish'] == 'green_salad' and p['vegetables'] == ['Lettuce'] for p in m['pinned'])
        assert m['kitchen_notes']['source'] == 'sheet' and not calls

    def test_opened_with_a_menu_the_model_writes_the_notes(self, client, model):
        model([GOOD])
        dishes = {'2026-10-26': [{'name': 'avial', 'slot': 'veg_gravy'}, {'name': 'green_salad', 'slot': 'salad'}],
                  '2026-10-28': [{'name': 'tomato_rice', 'slot': 'rice'}]}
        body = client.post('/api/v1/seasonal-bans', json={**self.BODY, 'dishes_by_date': dishes,
                                                          'kitchen_notes': True}).get_json()
        notes = body['months'][0]['kitchen_notes']
        assert notes['source'] == 'model', notes
