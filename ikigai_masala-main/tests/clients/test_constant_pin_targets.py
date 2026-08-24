"""A `constant_items` pin that was MEANT to name a real dish must name it.

Note 9 gives the pin two readings. One naming a dish in the slot's pool narrows
that cell's candidates, so every other rule still sees it — its colour counts
toward colour variety, its cuisine toward cuisine variety, and `unique_items`
stops a duplicate elsewhere. One naming a dish the city does not carry has
nothing to narrow to, so the cell is skipped and the text is stamped verbatim.

Both are wanted. Siemens Technology's "Hyd Mutton Biryani" and "Fish Tikka
Masala" are stamped on purpose (Bangalore's non-veg is chicken and egg only),
and World Bank's dessert really is printed as "Sweet/Fruit".

This file checks ONE thing, and deliberately not the branch: **does the pin name
a dish its city has?** That question is independent of which mechanism ends up
honouring it — `_rules_and_skip_for_client` stamps a *whole-slot* pin even when
the dish is real, because a bare string replaces the slot for the entire horizon
and its base slot is dropped from the model. A name that matches nothing,
though, is a bug wherever it lands.

The trap is that a **typo of a real dish** is indistinguishable from a
deliberate off-ontology stamp. It fails silently and in the expensive direction:
the menu still reads correctly to a diner while the dish quietly stops being a
candidate. Two were live —

  * Ather's salad pinned `mix veg salad`; Bangalore's dish is `mixed_veg_salad`.
  * Booking.com's second starter pinned `veg kati roll`; the dish is
    `veg_kathi_roll`, and it came from Booking's own menu import.

Booking's is an indexed slot, so correcting it makes the roll a real narrowed
candidate. Ather's is a whole-slot pin and stays stamped either way — the fix
there buys a printed menu that names a dish which exists.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.application.constant_items import _canonical_item_name
from src.ontology.paths import city_excel_path
from tests.client_fixtures import CLIENTS as CLIENT_ROWS

ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT / "data" / "configs" / "clients"

#: Pins that name no dish in their city ON PURPOSE, with the reason. Anything
#: else that matches nothing is treated as a typo if it resembles a real dish.
OFF_ONTOLOGY_ON_PURPOSE = {
    # The ontology's non-veg is chicken and egg; note 9's worked example.
    ("Siemens Technology", "Hyd Mutton Biryani"),
    ("Siemens Technology", "Fish Tikka Masala"),
    # The client prints the words, not a rotating sweet (an open question in
    # docs/pending_config_changes.md).
    ("World Bank", "Sweet/Fruit"),
    # Bangalore has no plain `boiled_egg` row — only `boiled_egg_with_pepper_
    # masala`, which is a different dish. Chennai gained one for World Bank and
    # ICON; Bangalore has not, so these two print the words. A pool gap, not a
    # typo, and not one to close by pointing the pin at a spiced dish.
    ("F5", "boiled egg"),
    ("Plan View", "boiled egg"),
}

#: How alike two names must be before a stamped pin looks like a typo. 0.86
#: catches `mix veg salad`/`mixed_veg_salad` and `veg kati roll`/`veg_kathi_roll`
#: without flagging `boiled egg`/`boiled_egg_with_pepper_masala`.
NEAR_MISS = 0.86


def _city_of(name: str):
    for row in CLIENT_ROWS:
        if row.get("name") == name:
            return (row.get("city") or "bangalore").strip().lower()
    return None


def _leaves(spec):
    """Every literal dish string a `constant_items` value can resolve to.

    A value may be a bare string, a weekday map, or a list that alternates
    across ISO weeks — and a weekday map's values may themselves be lists.
    """
    if isinstance(spec, str):
        yield spec
    elif isinstance(spec, list):
        for item in spec:
            yield from _leaves(item)
    elif isinstance(spec, dict):
        for key, value in spec.items():
            if not str(key).startswith("_"):
                yield from _leaves(value)


@pytest.fixture(scope="module")
def item_names():
    cache = {}

    def names(city: str):
        if city not in cache:
            df = pd.read_excel(city_excel_path(city))
            df.columns = [c.strip() for c in df.columns]
            cache[city] = {str(x).strip().lower() for x in df["item"].astype(str)}
        return cache[city]

    return names


def _pins():
    """(client, counter label, slot, dish string) for every pin in the tree."""
    for path in sorted(CLIENT_DIR.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for client, blk in blob.items():
            if client.startswith("_") or not isinstance(blk, dict):
                continue
            blocks = [("", blk)] + [
                (f" / {c}", b) for c, b in (blk.get("counters") or {}).items()
                if isinstance(b, dict)]
            for label, block in blocks:
                for slot, spec in (block.get("constant_items") or {}).items():
                    if str(slot).startswith("_"):
                        continue
                    for dish in _leaves(spec):
                        yield client, label, str(slot), dish


class TestStampedPins:
    def test_no_stamped_pin_resembles_a_real_dish(self, item_names):
        typos = []
        for client, label, slot, dish in _pins():
            city = _city_of(client)
            if city is None:
                continue                       # its own test elsewhere
            pool = item_names(city)
            if _canonical_item_name(dish, pool) is not None:
                continue                       # names a real dish
            if (client, dish) in OFF_ONTOLOGY_ON_PURPOSE:
                continue
            probe = dish.strip().lower().replace(" ", "_")
            near = difflib.get_close_matches(probe, pool, n=1, cutoff=NEAR_MISS)
            if near:
                typos.append(
                    f"{client}{label} [{slot}] pins {dish!r}, which {city} does "
                    f"not carry, so it is stamped as text — but {city} has "
                    f"{near[0]!r}. Correct the pin, or add it to "
                    f"OFF_ONTOLOGY_ON_PURPOSE with a reason.")
        assert typos == [], "\n".join(typos)

    def test_the_two_corrected_pins_name_a_real_dish(self, item_names):
        """The regression this file exists for."""
        pool = item_names("bangalore")
        assert _canonical_item_name("mixed veg salad", pool) == "mixed_veg_salad"
        assert _canonical_item_name("veg kathi roll", pool) == "veg_kathi_roll"
        assert _canonical_item_name("mix veg salad", pool) is None
        assert _canonical_item_name("veg kati roll", pool) is None

    def test_every_off_ontology_pin_is_still_off_ontology(self, item_names):
        """If a dish gets added to the ontology, the entry is stale — the reason
        beside it no longer applies, and for an indexed slot the pin starts
        narrowing a cell. Note 9 says adding the dish switches the pin over with
        no config change, so this is the line that notices."""
        for client, dish in sorted(OFF_ONTOLOGY_ON_PURPOSE):
            city = _city_of(client)
            if city is None:
                continue
            assert _canonical_item_name(dish, item_names(city)) is None, (
                f"{client} pins {dish!r} and {city} now carries it — the pin "
                f"narrows a cell, so drop it from OFF_ONTOLOGY_ON_PURPOSE")

    def test_the_guard_catches_a_planted_typo(self, item_names):
        """Otherwise it passes whether or not it is comparing anything."""
        pool = item_names("bangalore")
        assert difflib.get_close_matches(
            "plain_chapatti", pool, n=1, cutoff=NEAR_MISS) == ["plain_chapati"]
        assert difflib.get_close_matches(
            "boiled_egg", pool, n=1, cutoff=NEAR_MISS) == []

    def test_most_pins_name_a_real_dish(self, item_names):
        """A sanity floor: if a refactor broke the name matching, every pin
        would read as off-ontology and the near-miss check would go quiet."""
        real = sum(
            1 for client, _l, _s, dish in _pins()
            if _city_of(client)
            and _canonical_item_name(dish, item_names(_city_of(client))) is not None
        )
        assert real >= 40, real
