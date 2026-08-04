"""
API Configuration
"""

import datetime as dt
import os
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover — Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[misc,assignment]

BASE_DIR = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Per-city item ontology
# ---------------------------------------------------------------------------
# Re-exported from src.ontology.paths, which is where these now live. They were
# never web configuration — resolving a city to its workbook and to its declared
# category coverage is domain knowledge the ontology repository needs, and while
# it sat in this module the repository could not read it without importing the
# web package. Kept as names here because ~10 modules and tests import them from
# api.config; there is one definition, in src/ontology/paths.py.
from src.ontology.paths import (  # noqa: E402,F401
    BASE_DIR as _ONTOLOGY_BASE_DIR,
    CITY_ITEMS_DIR,
    CITY_ONTOLOGY_CATEGORIES_PATH,
    DEFAULT_EXCEL_PATH,
    DEFAULT_ONTOLOGY_CITY,
    MENU_EXCEL_PATH_OVERRIDE,
    city_excel_path,
    city_required_slots,
    city_slug,
)

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


# Re-exported from src.settings, which is where settings the data layer needs
# now live. Defined there rather than here because src/db.py must not import
# from the web package to read it — it used to, via a lazy in-function import
# with a comment admitting the cycle it was dodging. Kept as a name on
# api.config so existing importers (and the health endpoint) are unchanged.
from src.settings import SUPABASE_TIMEOUT_SECONDS  # noqa: E402,F401


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
