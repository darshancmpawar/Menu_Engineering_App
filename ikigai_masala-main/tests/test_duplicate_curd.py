"""`plain_curd` and `curd` are one dish (scripts/merge_duplicate_curd.py).

Both rows were course_type=curd_side, is_plain_curd=1, item_color=white — the
same bowl of curd competing with itself for a slot and counting twice toward
"distinct dishes available".
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path
from scripts.merge_duplicate_curd import KEEP, DROP, merge

CITIES = ['Bangalore', 'Pune', 'Chennai', 'NCR']


def _norm(s):
    return str(s).strip().lower()


@pytest.fixture(scope='module')
def dfs():
    out = {}
    for city in CITIES:
        df = pd.read_excel(city_excel_path(city))
        df.columns = [c.strip() for c in df.columns]
        out[city] = df
    return out


@pytest.mark.parametrize('city', CITIES)
def test_only_one_plain_curd_row(city, dfs):
    names = dfs[city]['item'].map(_norm)
    assert (names == DROP).sum() == 0, f'{city} still carries {DROP}'
    assert (names == KEEP).sum() == 1, f'{city} should have exactly one {KEEP}'


def test_survivor_is_named_curd_so_the_staple_exemption_still_matches():
    """REPEATABLE_ITEM_BASES matches the literal name, so keeping `plain_curd`
    instead would have switched the daily-curd exemption off."""
    from src.constants import REPEATABLE_ITEM_BASES
    assert KEEP in REPEATABLE_ITEM_BASES


def test_ncr_merged_the_client_tokens_rather_than_dropping_them(dfs):
    """NCR's two rows carried different pools — `curd` for Junglee/Stryker and
    `plain_curd` for Airtel Noida. A plain delete would have taken Airtel
    Noida's curd away with it."""
    ncr = dfs['NCR']
    row = ncr[ncr['item'].map(_norm) == KEEP].iloc[0]
    tokens = {t.strip().lower() for t in str(row['client']).split(',') if t.strip()}
    assert 'airtel noida' in tokens, tokens
    assert 'junglee games' in tokens, tokens


@pytest.mark.parametrize('city', CITIES)
def test_rerun_is_a_noop(city, dfs):
    out = merge(dfs[city].copy())
    assert len(out) == len(dfs[city])
