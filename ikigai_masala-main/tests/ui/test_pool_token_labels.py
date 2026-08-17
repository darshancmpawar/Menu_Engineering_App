"""The Item Pools picker labels ontology pool tokens by the app client they name.

The `client` column tags dishes with short tokens ('stryker'); the app knows the
client as 'Stryker NCR'. `pool_token_client_labels` maps token -> client name,
scoped to the selected city so a namesake in another city is not picked.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit", reason="editor helper imports streamlit")

from customisation.main import pool_token_client_labels


class _FakeApi:
    def __init__(self, clients):
        self._clients = clients

    def list_clients_with_city(self):
        return self._clients


_NCR = _FakeApi([
    {'name': 'Stryker NCR', 'city': 'NCR'},
    {'name': 'Junglee Games', 'city': 'NCR'},
    {'name': 'Sinch NCR', 'city': 'NCR'},
    {'name': 'Siemens', 'city': 'NCR'},
    {'name': 'Airtel Noida', 'city': 'NCR'},
    {'name': 'SAEL', 'city': 'NCR'},
    {'name': 'Siemens Technology', 'city': 'Bangalore'},
])


def test_token_maps_to_the_city_client():
    labels = pool_token_client_labels(
        _NCR, 'NCR', ['stryker', 'junglee games', 'sinch', 'airtel noida'])
    assert labels['stryker'] == 'Stryker NCR'
    assert labels['junglee games'] == 'Junglee Games'
    assert labels['sinch'] == 'Sinch NCR'
    assert labels['airtel noida'] == 'Airtel Noida'


def test_match_is_scoped_to_the_selected_city():
    # 'siemens' must resolve to the NCR Siemens, never the Bangalore namesake.
    labels = pool_token_client_labels(_NCR, 'NCR', ['siemens'])
    assert labels['siemens'] == 'Siemens'


def test_unmatched_token_keeps_titled_form():
    labels = pool_token_client_labels(_NCR, 'NCR', ['corning'])
    assert labels['corning'] == 'Corning'


def test_api_failure_degrades_to_titled_tokens():
    class _Boom:
        def list_clients_with_city(self):
            raise RuntimeError("api down")
    labels = pool_token_client_labels(_Boom(), 'NCR', ['stryker'])
    assert labels['stryker'] == 'Stryker'
