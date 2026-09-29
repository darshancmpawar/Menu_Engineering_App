"""Guardrails for hand-curated ontology classifications.

These items were re-classified by hand after a dataset import got them wrong.
A future re-import of the master xlsx must not silently revert them, so we
assert the intended classification here. Fast (just reads the sheet).
"""

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ontology(ensure_sample_data_exists):
    return pd.read_excel(ensure_sample_data_exists)


def test_all_kadhi_items_are_veg_gravy(ontology):
    """Kadhi (pakora / mor kuzhambu / majjige huli) serves in the gravy slot,
    not as an everyday lentil dal.

    All `is_kadhi_dal` items must be veg_gravy so `kadhi_weekly`, which is
    scoped to that slot, binds consistently.

    This carried a strict xfail while `is_kadhi_dal` was 0 on every row of all
    five workbooks, which left three rules silently inert — Pune's
    `kadhi_weekly` and `kadhi_15d_window`, and one Bangalore rule. The
    corrected item lists restore the flag (26 rows in Bangalore and Hyderabad,
    10 in Pune, 1 in Chennai), so the marker is gone, as its own note said to
    do. NCR still reads 0 and is the workbook still to come.

    NB Pune files its 10 flagged rows across BOTH `dal` and `veg_gravy`, so a
    Pune fixture would fail this. The fixture is Bangalore, where all 26 are
    veg_gravy; the Pune split is recorded in docs/pending_config_changes.md."""
    kadhi = ontology[ontology["is_kadhi_dal"].fillna(0).astype(float) == 1]
    assert len(kadhi) > 0, "expected some is_kadhi_dal items"
    course = set(kadhi["course_type"].dropna())
    assert course == {"veg_gravy"}, f"kadhi items not all veg_gravy: {course}"
    # gujarati_kadhi was the lone dal-classified outlier.
    guj = ontology.loc[ontology["item_id"] == "MENU000061"]
    assert (guj["course_type"] == "veg_gravy").all()
    assert (guj["is_dal"].fillna(0).astype(float) == 0).all()


def test_mango_pachadi_is_veg_gravy_not_raita(ontology):
    """mango_pachadi is a sweet-sour veg gravy, not a yogurt raita side."""
    mp = ontology.loc[ontology["item_id"] == "MENU002784"]
    assert len(mp) == 1
    assert (mp["course_type"] == "veg_gravy").all()
    assert (mp["is_raita"].fillna(0).astype(float) == 0).all()
