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
