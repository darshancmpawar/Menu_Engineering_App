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

PROCESSED_DATA_DIR = os.getenv(
    'PROCESSED_DATA_DIR',
    str(BASE_DIR / 'data/processed')
)

OUTPUT_DIR = os.getenv(
    'OUTPUT_DIR',
    str(BASE_DIR / 'data/outputs')
)

CLIENTS_CONFIG_PATH = os.getenv(
    'CLIENTS_CONFIG_PATH',
    str(BASE_DIR / 'data/configs/clients.json')
)

MENU_RULES_CONFIG_PATH = os.getenv(
    'MENU_RULES_CONFIG_PATH',
    str(BASE_DIR / 'data/configs/indian_menu_rules.json')
)

HISTORY_LONG_PATH = os.getenv(
    'HISTORY_LONG_PATH',
    str(BASE_DIR / 'data/history_long.csv')
)

HISTORY_WEEKS_PATH = os.getenv(
    'HISTORY_WEEKS_PATH',
    str(BASE_DIR / 'data/history_weeks.csv')
)

DEFAULT_TIME_LIMIT_SECONDS = 240
MIN_TIME_LIMIT_SECONDS = 10
MAX_TIME_LIMIT_SECONDS = 600

DEFAULT_NUM_DAYS = 5
MIN_NUM_DAYS = 1
MAX_NUM_DAYS = 30

API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', '5000'))
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
