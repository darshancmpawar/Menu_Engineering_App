#!/usr/bin/env python3
"""The cities that have an item workbook — read from the directory, not typed.

Eleven correction scripts each carried their own `CITIES = ("bangalore",
"pune", "chennai", "ncr")`. That literal was correct for as long as there were
exactly four cities, and it became a liability the moment there was a fifth:
adding `hyderabad.xlsx` without touching all eleven would leave the new city
outside every all-cities correction — no definitional flags, no colour fill, no
structural non-veg flags, no dead-column drop — and **nothing would say so**.
The workbook would still load, still build pools, still plan; it would simply
carry a different, older set of corrections than every other city, which is the
quiet kind of wrong this repo keeps finding in its data.

So the list is derived from `data/raw/city_items/*.xlsx`, the same place
`city_excel_path` resolves against. A new city is a new file and nothing else.

Ordering is `REFERENCE_CITY` first, then alphabetical. Bangalore leading is not
cosmetic: several scripts learn from the cities that already classify a dish and
apply the verdict to the rest, so the deepest list should be seen first, and a
few (`complete_ontology`'s cross-city channel) read city order as tie-break
evidence. Fixed order also keeps the scripts' output stable across machines,
which `glob()` alone does not promise.

`tests/data/test_city_coverage.py` fails if a script goes back to a hard-coded
tuple, or if a city workbook exists that the chain would skip.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent.parent
CITY_DIR = ROOT / "data" / "raw" / "city_items"

#: The city whose workbook is the master schema and the fallback for a city
#: with no file of its own (`src.ontology.paths.DEFAULT_ONTOLOGY_CITY`).
REFERENCE_CITY = "bangalore"


def city_slugs() -> Tuple[str, ...]:
    """Every city with a workbook, reference city first then alphabetical."""
    found = sorted(p.stem.lower() for p in CITY_DIR.glob("*.xlsx"))
    rest = [c for c in found if c != REFERENCE_CITY]
    return ((REFERENCE_CITY,) if REFERENCE_CITY in found else ()) + tuple(rest)


#: Module-level snapshot for the scripts that want a plain constant. Computed at
#: import, so a script run after a new workbook lands picks it up.
CITIES: Tuple[str, ...] = city_slugs()


def city_path(city: str) -> Path:
    return CITY_DIR / f"{city}.xlsx"


if __name__ == "__main__":
    for c in CITIES:
        print(c)
