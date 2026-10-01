"""`POST /api/v1/explain` with and without `chef_read`: the button is the only trigger."""
import json

import pytest

import api.explain_llm as llm
from api.app import app

PLAN_BODY = {'client_name': 'Rippling', 'start_date': '2026-03-23', 'num_days': 2, 'time_limit_seconds': 30}


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def planned(client, fake_supabase):
    resp = client.post('/api/v1/plan', json=PLAN_BODY)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


@pytest.fixture
def model(monkeypatch):
    """A scripted model that writes a minimal, valid read from whatever facts it gets."""
    llm.reset_chef_read_cache_for_tests()
    monkeypatch.setattr(llm, 'API_KEY', 'test-key')
    calls = []

    def fake(system_prompt, contents, **kw):
        facts = json.loads(contents[0]['parts'][0]['text'])
        calls.append(facts['date'])
        problems = [p.replace('_', ' ') for p in facts.get('known_problems') or []]
        # A day with a known problem must face it, or the checks send it back;
        # a real model is told the same in the prompt.
        internal = ('Watch this: ' + problems[0] + '.') if problems else 'Nothing to fix.'
        weak = [{'kind': 'other', 'text': problems[0]}] if problems else []
        return json.dumps({'client_read': f"{facts['weekday']}: an easy day.",
                           'internal_read': internal,
                           'claims': {'plates': [], 'star': None, 'comebacks': [],
                                      'weak_spots': weak, 'data_doubts': []}})

    monkeypatch.setattr(llm, '_post_model', fake)
    return calls


def test_a_plain_explain_never_calls_the_chef(client, planned, model):
    body = client.post('/api/v1/explain', json={**PLAN_BODY, 'solution': planned['solution']}).get_json()
    assert body['success'] is True
    assert all(d['chef_read'] is None for d in body['days'])
    assert model == []


def test_asking_the_chef_returns_a_read_for_every_day(client, planned, model):
    body = client.post('/api/v1/explain', json={**PLAN_BODY, 'solution': planned['solution'],
                                                 'chef_read': True}).get_json()
    assert body['success'] is True
    reads = [d['chef_read'] for d in body['days']]
    assert reads and all(r['source'] == 'model' for r in reads)
    assert sorted(model) == sorted(d['date'] for d in body['days'])
    # the overview is still there either way
    assert all(d['overview'] for d in body['days'])
