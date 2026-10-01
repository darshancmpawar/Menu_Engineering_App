"""`MenuApiClient.explain(chef_read=True)`: what the "Ask the chef" button sends."""
import pytest

import ui.api_client as client_mod
from ui.api_client import MenuApiClient


class _Resp:
    status_code = 200
    ok = True
    headers = {'content-type': 'application/json'}

    def json(self):
        return {'success': True, 'days': []}


@pytest.fixture
def sent(monkeypatch):
    seen = {}

    def fake_retry(fn, retryable=True):
        seen['retryable'] = retryable
        return fn()

    monkeypatch.setattr(client_mod, '_with_one_retry', fake_retry)
    api = MenuApiClient('http://api.test')

    def fake_post(url, json=None, timeout=None, **kw):
        seen.update(url=url, payload=json, timeout=timeout)
        return _Resp()

    monkeypatch.setattr(api.session, 'post', fake_post)
    return api, seen


def _explain(api, **kw):
    return api.explain(client_name='Eli Lilly', start_date='2026-09-07', solution={'x': 1}, num_days=5, **kw)


def test_a_plain_explain_does_not_ask_the_chef(sent):
    api, seen = sent
    _explain(api)
    assert 'chef_read' not in seen['payload'] and 'region_days' not in seen['payload']
    assert seen['timeout'] == 45 and seen['retryable'] is True


def test_ask_the_chef_sends_the_flag_and_waits_long_enough(sent):
    api, seen = sent
    _explain(api, chef_read=True, region_days={'2026-09-08': 'Tamil Nadu'})
    assert seen['payload']['chef_read'] is True
    assert seen['payload']['region_days'] == {'2026-09-08': 'Tamil Nadu'}
    assert seen['timeout'] == 360          # 60 + 60 per day for 5 days
    assert seen['retryable'] is False      # a blind retry would spend the quota twice


def test_the_timeout_is_capped(sent):
    api, seen = sent
    api.explain(client_name='X', start_date='2026-09-07', solution={}, num_days=20, chef_read=True)
    assert seen['timeout'] == 600
