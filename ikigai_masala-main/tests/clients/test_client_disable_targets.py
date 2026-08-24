"""A client's `disable` must name a rule that client's city actually has.

`load_for_client()` drops a city rule whose `name` appears in the client's
`disable` list. A name that matches nothing is dropped silently — same shape as
the `clients.name` mismatch note 9 describes, and it fails the same way: the
config reads as though a rule were switched off, `/diagnose` reports clean, and
a plausible plan comes back.

It bit once already. Tekion CHN was written by re-keying Tekion BLR's block to
the Chennai site, and BLR's `disable: ["deep_fried_coupling"]` came across with
it. `deep_fried_coupling` is a **Bangalore** rule; Chennai's ruleset is
standalone rather than an `extends`, so it has no coupling rule at all. That one
was inert in the harmless direction — nothing was left running that should have
been off — but the next copy need not be, and the file claimed something untrue
either way.

`use.ref` is checked here too, for the same reason: a ref naming no component in
`rule_library.json` contributes no rule and says nothing about it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.menu_rules.menu_rule_loader import MenuRuleLoader
from tests.client_fixtures import CLIENTS as CLIENT_ROWS

ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT / "data" / "configs" / "clients"
RULE_LIBRARY = ROOT / "data" / "configs" / "rule_library.json"

DEFAULT_CITY = "bangalore"


def _city_of(name: str):
    for row in CLIENT_ROWS:
        if row.get("name") == name:
            return (row.get("city") or DEFAULT_CITY).strip().lower()
    return None


def _blocks(blk):
    """(label, block) for the client-level entry and each per-counter one."""
    yield "", blk
    for cname, cblk in (blk.get("counters") or {}).items():
        if isinstance(cblk, dict):
            yield f" / {cname}", cblk


def _client_entries():
    for path in sorted(CLIENT_DIR.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for client, blk in blob.items():
            if client.startswith("_") or not isinstance(blk, dict):
                continue
            yield path.name, client, blk


@pytest.fixture(scope="module")
def city_rule_names():
    loader = MenuRuleLoader()
    cache = {}

    def names(city: str):
        if city not in cache:
            cache[city] = {r.name for r in loader.load_for_city(city)}
        return cache[city]

    return names


class TestEveryDisableNamesARealRule:
    def test_no_client_disables_a_rule_its_city_does_not_have(self, city_rule_names):
        dead = []
        for fname, client, blk in _client_entries():
            city = _city_of(client)
            if city is None:      # covered by its own test below
                continue
            known = city_rule_names(city)
            for label, block in _blocks(blk):
                for target in (block.get("disable") or []):
                    if target not in known:
                        dead.append(f"{fname}: {client}{label} disables "
                                    f"{target!r}, which no {city} rule is named")
        assert dead == [], "\n".join(dead)

    def test_every_client_file_key_matches_a_real_client(self):
        """The lookup is exact-match with no normalisation, so a key that names
        no row in `clients` loads every rule in the block as zero (note 9)."""
        unknown = [f"{fname}: {client!r}"
                   for fname, client, _blk in _client_entries()
                   if _city_of(client) is None]
        assert unknown == [], "\n".join(unknown)

    def test_the_guard_catches_a_planted_dead_disable(self, city_rule_names):
        """Otherwise this passes whether or not it is looking at anything."""
        known = city_rule_names("chennai")
        assert "deep_fried_coupling" not in known
        assert "no_such_rule_anywhere" not in known

    def test_it_still_recognises_a_real_one(self, city_rule_names):
        """The counter-case: the rule Tekion BLR disables does exist in its own
        city, so the check is not simply rejecting everything."""
        assert "deep_fried_coupling" in city_rule_names("bangalore")


class TestEveryUseRefNamesARealComponent:
    def test_no_client_references_a_missing_library_component(self):
        library = json.loads(RULE_LIBRARY.read_text(encoding="utf-8"))
        refs = set(library.get("components", library))
        assert refs, "rule_library.json has no components to check against"

        missing = []
        for fname, client, blk in _client_entries():
            for label, block in _blocks(blk):
                for spec in (block.get("use") or []):
                    ref = (spec or {}).get("ref")
                    if ref not in refs:
                        missing.append(f"{fname}: {client}{label} uses "
                                       f"{ref!r}, which rule_library.json "
                                       f"does not define")
        assert missing == [], "\n".join(missing)
