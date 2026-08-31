"""`item_id` is one format everywhere, and the allocators can compute a maximum.

`item_id` is the ontology's primary key: `filter_eligible` dedupes on it and
every script that adds a dish allocates "one past the city's highest". Two of
those allocators computed that maximum with `pd.to_numeric`, which coerces
`MENU004360` to NaN — so the max of an all-NaN column was nothing, they fell
back to 1, and they stamped bare integers onto sixty-four rows.

The bug is worth a test rather than just a fix because it is silently
self-perpetuating: the same bad maximum is recomputed on every run, so each
future addition to those cities would restart at 1 and eventually collide with a
row already numbered 1. Nothing had broken yet — which is exactly why nothing
would have noticed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.city_list import CITIES, city_path
from scripts.normalize_item_ids import ID_RE, mk_id, numeric_part, renumber


@pytest.fixture(scope="module")
def frames():
    out = {}
    for city in CITIES:
        d = pd.read_excel(city_path(city))
        d.columns = [c.strip() for c in d.columns]
        out[city] = d
    return out


class TestTheCommittedWorkbooks:
    @pytest.mark.parametrize("city", CITIES)
    def test_every_id_is_the_house_format(self, frames, city):
        bad = [v for v in frames[city]["item_id"]
               if not ID_RE.match(str(v).strip())]
        assert not bad, bad[:10]

    @pytest.mark.parametrize("city", CITIES)
    def test_ids_are_unique_within_a_city(self, frames, city):
        ids = frames[city]["item_id"].astype(str)
        assert not ids.duplicated().any(), sorted(ids[ids.duplicated()])[:10]

    def test_uniqueness_is_only_promised_within_a_city(self, frames):
        """Stated so nobody builds on the opposite. Chennai's `MENU004360` and
        Bangalore's are different dishes and always have been — the ranges
        overlap by construction, which is why the Hyderabad importer's `HYD`
        prefix bought nothing and was dropped."""
        blr = set(frames["bangalore"]["item_id"].astype(str))
        chn = set(frames["chennai"]["item_id"].astype(str))
        assert blr & chn


class TestTheAllocators:
    def test_a_prefixed_id_yields_its_number(self):
        assert numeric_part("MENU004360") == 4360
        assert numeric_part(7) == 7
        assert numeric_part("no digits here") is None

    def test_pd_to_numeric_is_why_this_broke(self):
        """The specific mistake, pinned: coercing the whole id gives NaN, so a
        max over it is nothing and the caller falls back to 1."""
        ids = pd.Series(["MENU000001", "MENU004360"])
        assert pd.to_numeric(ids, errors="coerce").notna().sum() == 0
        assert max(numeric_part(v) for v in ids) == 4360

    @pytest.mark.parametrize("script", ["chennai_client_pools",
                                        "deepen_thin_pools",
                                        "expand_side_pools"])
    def test_every_allocator_reads_a_prefixed_id(self, script):
        """All three add rows to a city list; all three must agree on what the
        highest existing id is."""
        import importlib
        mod = importlib.import_module(f"scripts.{script}")
        df = pd.DataFrame({"item_id": ["MENU000001", "MENU004360"],
                           "item": ["a", "b"]})
        assert mod._next_id(df) == 4361

    @pytest.mark.parametrize("script", ["chennai_client_pools",
                                        "deepen_thin_pools"])
    def test_the_fixed_allocators_emit_the_house_format(self, script):
        import importlib
        mod = importlib.import_module(f"scripts.{script}")
        assert ID_RE.match(mod._mk_id(4361))


class TestTheRepair:
    def test_it_renumbers_past_the_highest_existing_id(self):
        df = pd.DataFrame({"item_id": ["MENU000009", 1, 2],
                           "item": ["a", "b", "c"]})
        out, changed = renumber(df)
        assert [c[1] for c in changed] == [mk_id(10), mk_id(11)]
        assert not out["item_id"].duplicated().any()

    def test_a_clean_frame_is_left_alone(self):
        df = pd.DataFrame({"item_id": ["MENU000001"], "item": ["a"]})
        out, changed = renumber(df)
        assert changed == []
        assert list(out["item_id"]) == ["MENU000001"]

    def test_a_new_id_can_never_land_on_an_existing_row(self):
        """The one thing a renumber must not do. The highest number in the file
        is taken whatever prefix carries it, so an `HYD006227` row is counted
        even though it is not the house format."""
        df = pd.DataFrame({"item_id": ["HYD000500", 1], "item": ["a", "b"]})
        out, _changed = renumber(df)
        assert list(out["item_id"]) == [mk_id(501), mk_id(502)]

    def test_it_is_idempotent(self):
        df = pd.DataFrame({"item_id": [1, 2], "item": ["a", "b"]})
        once, _ = renumber(df)
        twice, changed = renumber(once)
        assert changed == []
        assert list(once["item_id"]) == list(twice["item_id"])
