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

DEFAULT_EXCEL_PATH = os.getenv(
    'MENU_EXCEL_PATH',
    str(BASE_DIR / 'data/raw/menu_items.xlsx')
)

MENU_RULES_CONFIG_PATH = os.getenv(
    'MENU_RULES_CONFIG_PATH',
    str(BASE_DIR / 'data/configs/indian_menu_rules.json')
)

CLIENT_RULES_CONFIG_PATH = os.getenv(
    'CLIENT_RULES_CONFIG_PATH',
    str(BASE_DIR / 'data/configs/client_rules.json')
)

MIN_TIME_LIMIT_SECONDS = 10
MAX_TIME_LIMIT_SECONDS = 600

MIN_NUM_DAYS = 1
MAX_NUM_DAYS = 30

# Max number of ranked alternate menus a single /plan request may ask for
# (in addition to the primary). Bounds solver work per request.
MAX_ALTERNATES = 4

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
