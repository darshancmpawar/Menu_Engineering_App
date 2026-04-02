"""Authentication manager — handles login, user CRUD against Supabase users table.

Password storage: SHA-256 with a random 16-byte hex salt, stored as "salt:hash".
"""

from __future__ import annotations

import hashlib
import os
import threading
from typing import List, Optional

from user_authentication.models import User, ALL_ROLES

# ---------------------------------------------------------------------------
# Supabase client (shared singleton, same pattern as client_config.py)
# ---------------------------------------------------------------------------
_sb_client = None
_sb_lock = threading.Lock()


def _get_supabase():
    global _sb_client
    if _sb_client is None:
        with _sb_lock:
            if _sb_client is None:
                from supabase import create_client
                try:
                    import streamlit as st
                    url = st.secrets["SUPABASE_URL"]
                    key = st.secrets["SUPABASE_KEY"]
                except Exception:
                    url = os.environ["SUPABASE_URL"]
                    key = os.environ["SUPABASE_KEY"]
                _sb_client = create_client(url, key)
    return _sb_client


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str | None = None) -> str:
    """Return 'salt:hash' string. Generates a random salt if not provided."""
    if salt is None:
        salt = os.urandom(16).hex()
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a 'salt:hash' string."""
    if ":" not in stored:
        return False
    salt, _ = stored.split(":", 1)
    return _hash_password(password, salt) == stored


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------

class AuthManager:
    """Handles authentication and user management via Supabase."""

    def __init__(self):
        self._sb = _get_supabase()

    # ---- authentication ---------------------------------------------------

    def authenticate(self, email: str, password: str) -> Optional[User]:
        """Verify credentials and return a User on success, None on failure."""
        row = (
            self._sb.table("users")
            .select("email, profile_name, password_hash, role")
            .eq("email", email.strip().lower())
            .maybe_single()
            .execute()
        )
        if not row.data:
            return None
        if not _verify_password(password, row.data["password_hash"]):
            return None
        return User(
            email=row.data["email"],
            profile_name=row.data["profile_name"],
            role=row.data["role"],
        )

    # ---- user CRUD --------------------------------------------------------

    def create_user(
        self,
        email: str,
        profile_name: str,
        password: str,
        role: str,
    ) -> User:
        """Create a new user. Raises ValueError on validation failure."""
        email = email.strip().lower()
        profile_name = profile_name.strip()

        if not email or not profile_name or not password:
            raise ValueError("Email, profile name, and password are required.")
        if role not in ALL_ROLES:
            raise ValueError(f"Invalid role: {role}")

        # Check duplicate
        existing = (
            self._sb.table("users")
            .select("email")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        if existing.data:
            raise ValueError(f"User with email '{email}' already exists.")

        password_hash = _hash_password(password)
        self._sb.table("users").insert({
            "email": email,
            "profile_name": profile_name,
            "password_hash": password_hash,
            "role": role,
        }).execute()

        return User(email=email, profile_name=profile_name, role=role)

    def list_users(self) -> List[User]:
        """Return all users (no password hashes)."""
        rows = (
            self._sb.table("users")
            .select("email, profile_name, role")
            .order("profile_name")
            .execute()
        )
        return [
            User(email=r["email"], profile_name=r["profile_name"], role=r["role"])
            for r in rows.data
        ]

    def delete_user(self, email: str) -> None:
        """Delete a user by email. Raises ValueError if not found."""
        row = (
            self._sb.table("users")
            .select("email")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"User '{email}' not found.")
        self._sb.table("users").delete().eq("email", email).execute()

    def update_password(self, email: str, new_password: str) -> None:
        """Update a user's password."""
        email = email.strip().lower()
        if not new_password:
            raise ValueError("Password cannot be empty.")
        password_hash = _hash_password(new_password)
        self._sb.table("users").update({
            "password_hash": password_hash,
        }).eq("email", email).execute()
