"""
API Configuration
"""

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Optional, Set

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover — Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[misc,assignment]

BASE_DIR = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Per-city item ontology
# ---------------------------------------------------------------------------
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

# Base/reference ruleset (Bangalore). City-aware loading lives in
# src.menu_rules.menu_rule_loader (load_for_city + CITY_RULES_DIR); this
# constant is kept as the single-file default for any non-city caller.
MENU_RULES_CONFIG_PATH = os.getenv(
    'MENU_RULES_CONFIG_PATH',
    str(BASE_DIR / 'data/configs/city_rules/bangalore.json')
)

# CLIENT_RULES_CONFIG_PATH now lives in src.menu_rules.menu_rule_loader so the
# loader has no import dependency on the api package (it still honours the
# CLIENT_RULES_CONFIG_PATH env var).

MIN_TIME_LIMIT_SECONDS = 10
MAX_TIME_LIMIT_SECONDS = 600

MIN_NUM_DAYS = 1
MAX_NUM_DAYS = 30

# Max number of ranked alternate menus a single /plan request may ask for
# (in addition to the primary). Bounds solver work per request.
MAX_ALTERNATES = 4

# Largest request body the API will read, in bytes. Without a cap, /save and
# /regenerate parse an unbounded `week_plan` / `base_plan` straight into memory,
# so a single large POST is a cheap memory-pressure lever. 2 MB is far above a
# real payload (a 30-day multi-counter plan is a few tens of KB).
MAX_CONTENT_LENGTH_BYTES = int(
    os.getenv('MAX_CONTENT_LENGTH_BYTES', str(2 * 1024 * 1024))
)

# Optional shared-secret gate for the mutating endpoints. Unset (the default)
# leaves the API exactly as it is today — open — so nothing breaks for an
# existing deployment. Set it and every write must present a matching
# `X-API-Key` header (or `Authorization: Bearer <token>`), which is enough to
# stop an accidentally-exposed port from being writable by anyone who finds it.
API_WRITE_TOKEN = os.getenv('API_WRITE_TOKEN', '').strip()

API_HOST = os.getenv('API_HOST', '127.0.0.1')
API_PORT = int(os.getenv('API_PORT', '5000'))
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# Version string surfaced via /api/v1/health and /. Set by CI / container
# build (e.g. APP_VERSION=$(git rev-parse --short HEAD)); falls back to a
# sentinel so operators know the deployment didn't pass one through.
APP_VERSION = os.getenv('APP_VERSION', 'dev')


# Bound the time we wait on a Supabase response. Without this the
# httpx client used by supabase-py defaults to no timeout in some
# versions, which means a slow / unhealthy Supabase pins a Flask
# thread indefinitely and eventually the threadpool starves. 5
# seconds covers normal operation (the slowest reads we make are
# ~200ms) while still failing fast when something is genuinely wrong.
SUPABASE_TIMEOUT_SECONDS = float(os.getenv('SUPABASE_TIMEOUT_SECONDS', '5'))


# Timezone used to resolve "today" when the client doesn't pass an
# explicit start_date. Default is Asia/Kolkata because the product ships
# for Indian restaurants; set APP_TIMEZONE to any IANA name (e.g. UTC,
# America/New_York) for other deployments. A missing zoneinfo database
# (uncommon — containers sometimes strip it) falls back to UTC with a
# clear log line rather than silently using the process local TZ.
APP_TIMEZONE = os.getenv('APP_TIMEZONE', 'Asia/Kolkata')


def _resolve_tz():
    if ZoneInfo is None:
        import logging
        logging.getLogger(__name__).warning(
            "zoneinfo unavailable on this Python build; "
            "falling back to UTC for APP_TIMEZONE=%s",
            APP_TIMEZONE,
        )
        return dt.timezone.utc
    try:
        return ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        import logging
        logging.getLogger(__name__).warning(
            "APP_TIMEZONE=%r not found in zoneinfo database; falling back to UTC",
            APP_TIMEZONE,
        )
        return dt.timezone.utc


APP_TZ = _resolve_tz()


def today_in_app_tz() -> dt.date:
    """Return the current date in APP_TZ.

    Centralises the "what does today mean" decision so endpoints don't
    each call dt.date.today(), which would silently depend on the
    server's local timezone — catastrophic for cooldown windows and
    weekday-based theme dispatch when the container runs in UTC but
    the restaurant operates in IST.
    """
    return dt.datetime.now(APP_TZ).date()

# Vars that the API and solver cannot operate without. Validated at
# api.app import time so the process fails with a clear message instead
# of crashing on the first request that needs Supabase.
REQUIRED_ENV_VARS = ("SUPABASE_URL", "SUPABASE_KEY")


def validate_required_env() -> None:
    """Raise RuntimeError listing every required env var that is unset
    or empty. Reads os.environ live so test fixtures that set env in
    conftest.py before importing api.app are honoured.
    """
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Set them (e.g. in .streamlit/secrets.toml or the process env) "
              "before starting the API."
        )
