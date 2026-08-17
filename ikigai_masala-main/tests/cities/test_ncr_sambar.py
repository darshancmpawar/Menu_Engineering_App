"""The 10 sambar brought into NCR from the Bangalore master list.

`scripts/add_ncr_sambar.py` copies ten vegetable sambars into `ncr.xlsx` (NCR
had none). This pins that they are present, filed as sambar, carry fresh
non-colliding ids, and that re-running the script changes nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ontology.paths import city_excel_path
from scripts.add_ncr_sambar import SAMBAR_NAMES, add_sambar


@pytest.fixture(scope='module')
def ncr():
    df = pd.read_excel(city_excel_path('NCR'))
    df.columns = [c.strip() for c in df.columns]
    return df


def test_all_ten_present_and_filed_as_sambar(ncr):
    sb = ncr[ncr['course_type'] == 'sambar']
    names = set(sb['item'].astype(str).str.strip())
    assert set(SAMBAR_NAMES) <= names, set(SAMBAR_NAMES) - names
    assert len(sb) >= 10


def test_ids_and_names_unique(ncr):
    assert ncr['item_id'].duplicated().sum() == 0
    assert ncr['item'].duplicated().sum() == 0


def test_schema_is_unchanged(ncr):
    blr = pd.read_excel(city_excel_path('Bangalore'))
    blr.columns = [c.strip() for c in blr.columns]
    assert list(ncr.columns) == list(blr.columns)


def test_sambar_in_built_pool():
    from src.ontology.repository import repository
    _df, pools = repository.filtered_menu_data('NCR', [])
    assert len(pools.get('sambar', [])) >= 10


def test_rerun_is_a_noop(ncr):
    blr = pd.read_excel(city_excel_path('Bangalore'))
    out = add_sambar(blr, ncr)
    assert len(out) == len(ncr), "re-running add_sambar added rows"
