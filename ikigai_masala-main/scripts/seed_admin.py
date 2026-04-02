#!/usr/bin/env python3
"""Seed the default super_admin user.

Usage:
    export SUPABASE_URL="https://xxx.supabase.co"
    export SUPABASE_KEY="your-anon-key"
    python scripts/seed_admin.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from user_authentication.auth_manager import AuthManager

DEFAULT_EMAIL = "Darshan.Pawar@thesmartq.com"
DEFAULT_NAME = "Darshan"
DEFAULT_PASSWORD = "Menu@123"
DEFAULT_ROLE = "super_admin"


def main():
    auth = AuthManager()
    try:
        user = auth.create_user(DEFAULT_EMAIL, DEFAULT_NAME, DEFAULT_PASSWORD, DEFAULT_ROLE)
        print(f"Created {user.role} user: {user.email} ({user.profile_name})")
        print(f"Login with: {DEFAULT_EMAIL} / {DEFAULT_PASSWORD}")
    except ValueError as e:
        print(f"Skipped: {e}")


if __name__ == "__main__":
    main()
