"""Where each city's item workbook lives, and what it must cover.

Extracted from `api/config.py`. It was never web configuration: resolving a city
to a workbook path and to its declared category coverage is domain knowledge that
the ontology repository needs, and while it lived under `api/` the repository
could not read it without importing the web package — the exact inversion
`tests/test_architecture.py` forbids.

`api/config.py` re-exports every name below, so the ~10 call sites and tests that
import them from there keep working unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Set

#: Repo root — this file is src/ontology/paths.py, so up three.
BASE_DIR = Path(__file__).parent.parent.parent

# Each city serves a different item list, so the ontology is selected per client
# from ``clients.city`` — mirroring how the RULES are already resolved per city
# (src.menu_rules.menu_rule_loader.load_for_city + data/configs/city_rules/).
# Layout is the same convention: one file per city, named after the city slug.
CITY_ITEMS_DIR = Path(os.getenv(
    'CITY_ITEMS_DIR', str(BASE_DIR / 'data/raw/city_items')
))

# The city whose list is used for any city without its own file (and when a
# request carries no city at all). Same fallback role as menu_rule_loader's
# DEFAULT_CITY, and deliberately the same city.
DEFAULT_ONTOLOGY_CITY = 'bangalore'

# Declared coverage per city (see ontology_categories.json). A city absent from
# the file requires every mandatory base slot, which is what a whole-product
# ontology should carry.
CITY_ONTOLOGY_CATEGORIES_PATH = CITY_ITEMS_DIR / 'ontology_categories.json'

# An explicit MENU_EXCEL_PATH pins ONE workbook for every city — it is how a
# deployment (or a test) says "use this file, forget the per-city layout".
MENU_EXCEL_PATH_OVERRIDE = os.getenv('MENU_EXCEL_PATH', '').strip()

DEFAULT_EXCEL_PATH = (
    MENU_EXCEL_PATH_OVERRIDE
    or str(CITY_ITEMS_DIR / f'{DEFAULT_ONTOLOGY_CITY}.xlsx')
)


def city_slug(city) -> str:
    """Normalised city key: trimmed, lower-cased, spaces → underscores."""
    return str(city or '').strip().lower().replace(' ', '_')


def city_excel_path(city=None) -> str:
    """Path to the ontology workbook for *city*.

    Falls back to :data:`DEFAULT_EXCEL_PATH` when the city has no file of its
    own, so adding a city to ``AVAILABLE_CITIES`` never breaks planning — it
    just keeps using the default list until someone drops in
    ``city_items/<slug>.xlsx``. An explicit ``MENU_EXCEL_PATH`` wins outright.
    """
    if MENU_EXCEL_PATH_OVERRIDE:
        return MENU_EXCEL_PATH_OVERRIDE
    slug = city_slug(city)
    if slug:
        candidate = CITY_ITEMS_DIR / f'{slug}.xlsx'
        if candidate.is_file():
            return str(candidate)
    return DEFAULT_EXCEL_PATH


_city_categories_cache: Optional[dict] = None


def _city_ontology_categories() -> dict:
    global _city_categories_cache
    if _city_categories_cache is None:
        data = {}
        try:
            with open(CITY_ONTOLOGY_CATEGORIES_PATH, encoding='utf-8') as fh:
                raw = json.load(fh)
            data = {
                city_slug(k): {str(s).strip() for s in v}
                for k, v in raw.items()
                if not str(k).startswith('_') and isinstance(v, list)
            }
        except FileNotFoundError:
            pass
        except (ValueError, TypeError) as exc:
            # A malformed manifest must not take the API down: fall back to
            # "every city requires every mandatory slot", which is the strict
            # end of the range, and say so loudly.
            logging.getLogger(__name__).error(
                "Could not parse %s (%s); every city ontology will be held to "
                "the full mandatory-slot check.",
                CITY_ONTOLOGY_CATEGORIES_PATH, exc,
            )
        _city_categories_cache = data
    return _city_categories_cache


def city_required_slots(city=None) -> Optional[Set[str]]:
    """Base slots *city*'s ontology must cover, or ``None`` for "all mandatory".

    ``None`` is what an undeclared city gets, and it is the check that shipped
    before per-city ontologies — so Bangalore keeps failing loudly if a column
    mapping regression empties a slot.
    """
    declared = _city_ontology_categories()
    if MENU_EXCEL_PATH_OVERRIDE:
        # One pinned workbook for every city: the city name says nothing about
        # what the file contains, so don't hold it to a city's declaration.
        return None
    slug = city_slug(city)
    if slug in declared and city_excel_path(city) != DEFAULT_EXCEL_PATH:
        return declared[slug]
    return None
