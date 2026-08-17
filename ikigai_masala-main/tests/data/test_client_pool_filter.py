"""Tests for client-based item-pool filtering (F5 core).

These mirror the eligibility table and validation rules in the feature spec:
exact comma-split matching (no substring), case-insensitive, common always
included, dedup by item_id.
"""

import pandas as pd
import pytest

from src.preprocessor.client_pool_filter import (
    normalize_name, parse_client_pools, get_active_pools, item_is_eligible,
    filter_eligible, add_client_pool_column, available_pool_tokens,
)


class TestParsing:
    def test_normalize_trims_and_casefolds(self):
        assert normalize_name("  Infineon ") == "infineon"
        assert normalize_name(None) == ""
        assert normalize_name("") == ""

    def test_parse_comma_split(self):
        assert parse_client_pools("Cloudera,Healthineers,Infineon") == {
            "cloudera", "healthineers", "infineon"}

    def test_parse_trims_each_token(self):
        assert parse_client_pools(" Infineon , Healthineers ") == {
            "infineon", "healthineers"}

    def test_parse_drops_empties(self):
        assert parse_client_pools("Infineon,,") == {"infineon"}
        assert parse_client_pools("") == set()
        assert parse_client_pools(None) == set()

    def test_parse_nan_is_not_a_token(self):
        # An empty `client` cell read from a workbook is a float NaN; it must
        # yield no tokens, never the spurious string 'nan' (which had leaked
        # into the pool-token map when untagged sambar rows were added to NCR).
        import math
        assert parse_client_pools(float("nan")) == set()
        assert normalize_name(float("nan")) == ""
        assert math.nan != math.nan  # sanity: NaN is why `value or ""` failed


class TestActivePools:
    def test_common_always_added(self):
        assert get_active_pools({"infineon"}) == {"infineon", "common"}

    def test_common_added_even_when_empty(self):
        assert get_active_pools([]) == {"common"}
        assert get_active_pools(None) == {"common"}

    def test_source_pools_normalized(self):
        assert get_active_pools(["Infineon", "Healthineers"]) == {
            "infineon", "healthineers", "common"}


class TestEligibility:
    """Spec table — target Infineon, active {common, infineon, healthineers}."""

    ACTIVE = {"common", "infineon", "healthineers"}

    @pytest.mark.parametrize("cell,expected", [
        ("common", True),
        ("Infineon", True),
        ("Healthineers", True),
        ("Infineon,Cloudera", True),
        ("Cloudera,Healthineers", True),
        ("Amadeus", False),
        ("Cloudera", False),
    ])
    def test_spec_eligibility_table(self, cell, expected):
        assert item_is_eligible(parse_client_pools(cell), self.ACTIVE) is expected

    def test_no_substring_matching(self):
        # "infineon labs" must NOT match "infineon" (exact token match only)
        assert item_is_eligible(parse_client_pools("Infineon Labs"), self.ACTIVE) is False


class TestFilterEligible:
    def _df(self):
        return pd.DataFrame({
            "item_id": ["1", "2", "3", "4", "5", "6"],
            "item": ["a", "b", "c", "d", "e", "f"],
            "client": ["common", "Infineon", "Healthineers",
                       "Amadeus", "Cloudera,Healthineers", "Amadeus,Cloudera"],
        })

    def test_filters_to_active_pools(self):
        active = get_active_pools({"infineon", "healthineers"})
        out = filter_eligible(self._df(), active)
        # common(1), Infineon(2), Healthineers(3), Cloudera,Healthineers(5)
        assert set(out["item_id"]) == {"1", "2", "3", "5"}

    def test_common_included_with_empty_source_pools(self):
        out = filter_eligible(self._df(), get_active_pools([]))
        assert set(out["item_id"]) == {"1"}  # only common

    def test_dedup_by_item_id(self):
        df = self._df()
        dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)  # duplicate item_id "1"
        out = filter_eligible(dup, get_active_pools({"infineon"}))
        assert list(out["item_id"]).count("1") == 1

    def test_precomputed_pool_column_used(self):
        df = add_client_pool_column(self._df())
        assert "client_pool_set" in df.columns
        out = filter_eligible(df, get_active_pools({"amadeus"}))
        assert set(out["item_id"]) == {"1", "4", "6"}  # common + Amadeus rows


class TestAvailableTokens:
    def test_lists_all_tokens_except_common(self):
        df = pd.DataFrame({"client": [
            "common", "Infineon", "Cloudera,Healthineers", "common,Amadeus"]})
        assert available_pool_tokens(df) == {
            "infineon", "cloudera", "healthineers", "amadeus"}
