"""
API Configuration
"""

import os
from pathlib import Path

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

API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', '5000'))
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# Auth — signed bearer tokens issued by POST /api/v1/auth/login.
# Set API_SECRET_KEY to a long random string in production.
API_SECRET_KEY = os.getenv('API_SECRET_KEY', '')
API_TOKEN_TTL_SECONDS = int(os.getenv('API_TOKEN_TTL_SECONDS', str(60 * 60 * 24)))


# Vars that the API and solver cannot operate without. Validated at
# api.app import time so the process fails with a clear message instead
# of crashing on the first request that needs Supabase or tries to sign
# a token.
REQUIRED_ENV_VARS = ("API_SECRET_KEY", "SUPABASE_URL", "SUPABASE_KEY")


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
