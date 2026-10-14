"""The committed pool-token map still matches the workbooks.

`/editor-metadata` reads `data/raw/city_items/pool_tokens.json` instead of
parsing every city workbook, so a stale map is served to the editor as fact —
a client pool that exists in the list but not in the map simply cannot be
chosen, and nothing says so.

This check used to live in CI as `python "Chain rules/build_pool_token_map.py"
--check`. That directory was deleted in v2.07.03 and the step has failed on
every run since, which means the guarantee had been gone for a week while the
red tick was read as "the usual CI noise". It belongs in pytest anyway: the
only reason it was outside was that the builder was not an importable package,
and the builder is what went away.

`available_pool_tokens` is the same function the app uses, so this cannot
drift from what the map is meant to hold.
"""

from __future__ import annotations

import pytest

from src.ontology.paths import pool_tokens_for_city
from src.ontology.repository import repository
from src.preprocessor.client_pool_filter import available_pool_tokens

CITIES = ['Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'NCR']


@pytest.mark.parametrize('city', CITIES)
def test_the_map_matches_the_workbook(city):
    df, _pools = repository.menu_data(city)
    live = available_pool_tokens(df)
    mapped = set(pool_tokens_for_city(city) or [])
    assert mapped == live, (
        f'{city}: pool_tokens.json is stale. In the map but not the workbook: '
        f'{sorted(mapped - live)}; in the workbook but not the map: '
        f'{sorted(live - mapped)}. Rebuild it — the editor offers exactly '
        f'what this file says, so a missing token is a pool nobody can pick.')


def test_pune_is_deliberately_empty():
    """Pune is full-pool: `source_pools` cannot narrow it, so an EMPTY token
    set is the correct answer and not a missing entry. Without this, the
    obvious "every city has tokens" reading of the test above would look like
    a bug in Pune's row."""
    assert set(pool_tokens_for_city('Pune') or []) == set()


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
