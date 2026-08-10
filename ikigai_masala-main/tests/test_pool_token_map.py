"""The precomputed pool-token map must agree with the workbooks it derives from.

`/editor-metadata` answers one small question — which per-client pool tokens exist,
per city — and answering it from the workbooks cost **4.8 s of cold start**: three
files, 4,956 rows, fully parsed, to produce about eight short strings. Reading only
the `client` column does not help (openpyxl parses the whole sheet regardless,
measured at 1.1x), and the request cannot be scoped, because the editor fetches
metadata before the user has picked a city.

So the answer is committed to disk. That makes it a derived artefact, and derived
artefacts go stale — which is the entire risk of this optimisation. This test is
the mitigation: it recomputes from the workbooks and fails if the committed file
disagrees, so a re-import that changes a `client` column cannot silently leave the
editor offering tokens that no longer exist.
"""

from __future__ import annotations

import os

import pytest

from scripts.build_pool_token_map import OUTPUT, compute, load, tokens_for_city


class TestTheCommittedMapMatchesTheWorkbooks:
    def test_the_map_exists(self):
        assert os.path.exists(OUTPUT), (
            'run scripts/build_pool_token_map.py — without it the endpoint still '
            'works but pays the 4.8 s workbook parse')

    def test_it_is_not_stale(self):
        committed, fresh = load(), compute()
        assert committed == fresh, (
            'pool_tokens.json disagrees with the workbooks. Re-run '
            'scripts/build_pool_token_map.py (and note it belongs in the '
            'after-a-re-import checklist alongside the correction scripts).')

    def test_it_is_keyed_by_workbook_not_city(self):
        """Hyderabad resolves to bangalore.xlsx (NCR now has its own file). One
        entry per city would let two keys describing the same rows drift apart."""
        committed = load()
        assert committed
        assert all(k.endswith('.xlsx') for k in committed), list(committed)


class TestLookupBehaviour:
    @pytest.mark.parametrize('city,expected_nonempty', [
        ('Bangalore', True),   # 8 real client pools
        ('NCR', True),         # 8 real client pools of its own
        ('Chennai', False),    # every row is tagged `common`
        ('Pune', False),
    ])
    def test_tokens_for_city(self, city, expected_nonempty):
        toks = tokens_for_city(city)
        assert toks is not None, city
        assert bool(toks) is expected_nonempty, (city, toks)

    def test_ncr_has_its_own_tokens_not_bangalores(self):
        """NCR ships its own workbook, so its per-client pools are the 8 NCR
        clients — not Bangalore's, which keying by path would have handed it
        before the file existed."""
        assert tokens_for_city('NCR') != tokens_for_city('Bangalore')
        assert 'stryker' in tokens_for_city('NCR')

    def test_cities_sharing_a_workbook_share_tokens(self):
        """The payoff of keying by path: Hyderabad has no workbook of its own, so
        it must see exactly Bangalore's tokens rather than an empty list."""
        assert tokens_for_city('Hyderabad') == tokens_for_city('Bangalore')

    def test_a_missing_map_degrades_rather_than_raises(self, tmp_path, monkeypatch):
        """Absent map => None => the endpoint falls back to the workbooks. A fresh
        checkout that has not run the script is slow, never wrong."""
        import scripts.build_pool_token_map as mod
        monkeypatch.setattr(mod, 'OUTPUT', str(tmp_path / 'nope.json'))
        assert mod.load() is None
        assert mod.tokens_for_city('Bangalore') is None


class TestTheEndpointStillAnswersTheSame:
    def test_response_is_identical_with_and_without_the_map(self, monkeypatch):
        """The whole point: a pure speed change. If the map ever produced a
        different answer than the workbooks, this fails."""
        import api.app as api_app

        with_map = api_app._city_pool_tokens()
        monkeypatch.setattr(api_app, '_pool_tokens_from_map', lambda _city: None)
        from_workbooks = api_app._city_pool_tokens()
        assert with_map == from_workbooks
