"""Every city workbook is reached by every all-cities correction script.

Eleven scripts carried their own `CITIES = ("bangalore", "pune", "chennai",
"ncr")`. That literal was right for exactly as long as there were four cities,
and its failure mode is the quiet one: drop in a fifth workbook and the new city
silently keeps an OLDER set of corrections than every other — no definitional
flags, no colour fill, no non-veg form flags — while loading fine, building
pools fine and planning fine. Nothing turns red. `hyderabad.xlsx` was the fifth.

So the list is derived from the directory (`scripts/city_list.py`) and this file
is the guard: a script that goes back to a hard-coded tuple fails here, and so
does a workbook the chain would skip.

Two things are deliberately NOT asserted. City-specific scripts
(`ncr_south_bread`, `chennai_client_pools`, `pune_flag_corrections`, …) name one
city on purpose — that is their scope, not an oversight. And `audit_course_types`
enumerates the directory itself rather than importing the list, which is the same
property by a different route.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from scripts.city_list import CITIES, REFERENCE_CITY, city_slugs

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CITY_DIR = ROOT / "data" / "raw" / "city_items"

#: The scripts that correct EVERY city. Each one's edits are part of what a city
#: workbook is; a city one of them has not seen is a different artefact.
#: `{script: {name: why}}` — a literal city list that is right to be one. Each
#: is a statement about which cities may do something, not about which cities
#: exist, so deriving it from the directory would be wrong.
INTENTIONAL_LITERALS = {
    "expand_side_pools": {
        "SHARE_DONORS":
            "lending a dish between cities is a menu decision. Hyderabad is "
            "absent because it was seeded from Bangalore — its own rows are "
            "Quest's Telugu cooking, which does not belong in Pune's all-veg "
            "list or NCR's North Indian one.",
    },
}

ALL_CITY_SCRIPTS = [
    "bread_form_flags",
    "canonical_dish_spellings",
    "complete_ontology",
    "course_type_corrections",
    "definitional_flags",
    "drop_dead_columns",
    "expand_side_pools",
    "fill_item_colours",
    "marathi_ingredient_names",
    "merge_duplicate_curd",
    "misspelled_protein_names",
    "nonveg_structural_flags",
]


class TestTheListIsDerived:
    def test_it_matches_the_workbooks_on_disk(self):
        assert set(CITIES) == {p.stem.lower() for p in CITY_DIR.glob("*.xlsx")}

    def test_the_reference_city_leads(self):
        """Several scripts learn from the cities seen first, and a few read city
        order as tie-break evidence, so the deepest list has to come first."""
        assert CITIES[0] == REFERENCE_CITY

    def test_the_order_is_stable(self):
        """`glob()` alone does not promise an order, and an unstable one makes
        these scripts produce different output on different machines."""
        assert city_slugs() == CITIES
        assert list(CITIES[1:]) == sorted(CITIES[1:])

    def test_every_city_in_the_app_has_a_workbook_or_falls_back(self):
        from src.client.client_config import AVAILABLE_CITIES
        from src.ontology.paths import city_excel_path
        for city in AVAILABLE_CITIES:
            assert Path(city_excel_path(city)).is_file(), city


@pytest.mark.parametrize("name", ALL_CITY_SCRIPTS)
class TestEveryCorrectionScriptSeesEveryCity:
    def test_it_uses_the_shared_list(self, name):
        mod = importlib.import_module(f"scripts.{name}")
        assert tuple(mod.CITIES) == CITIES, (
            f"scripts/{name}.py has its own city list. Import it from "
            f"scripts/city_list.py instead — a hard-coded tuple is how a new "
            f"city silently misses this script's corrections.")

    def test_it_does_not_hard_code_a_city_tuple(self, name):
        """Importing the shared list is not enough on its own: a script can
        import it and still branch on a literal further down. Caught by reading
        the source, because that is where the next one will appear."""
        tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
        others = set(CITIES) - {REFERENCE_CITY}
        allowed = INTENTIONAL_LITERALS.get(name, {})
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            target = next((t.id for t in node.targets if isinstance(t, ast.Name)),
                          None)
            if not isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
                continue
            values = {e.value.strip().lower() for e in node.value.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            # A collection naming two or more non-reference cities is a city
            # list. One city is a scoped exception (a per-city correction) and
            # stays legal.
            if len(values & others) < 2 or target in allowed:
                continue
            raise AssertionError(
                f"scripts/{name}.py assigns a literal city list to {target!r} "
                f"({sorted(values & others)}). Use scripts.city_list.CITIES, or "
                f"— if it is deliberately not 'every city' — add it to "
                f"INTENTIONAL_LITERALS here with the reason.")

    def test_the_recorded_exceptions_still_exist(self, name):
        """An exception whose symbol has been renamed or deleted is a note that
        has stopped describing the code, and it would silence a NEW literal that
        happened to take the old name."""
        mod = importlib.import_module(f"scripts.{name}")
        for symbol in INTENTIONAL_LITERALS.get(name, {}):
            assert hasattr(mod, symbol), (
                f"INTENTIONAL_LITERALS names scripts/{name}.py::{symbol}, "
                f"which no longer exists")
