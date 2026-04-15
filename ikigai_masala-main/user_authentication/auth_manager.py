"""Authentication manager — handles login, user CRUD against Supabase users table.

Password storage: bcrypt hash (self-contained, includes salt + cost factor).
Legacy "salt:sha256_hex" hashes are still verified for backward compatibility
and are transparently rehashed to bcrypt on successful login.
"""

from __future__ import annotations

import hashlib
import os
import threading
from typing import List, Optional

import bcrypt

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
# bcrypt hashes always start with "$2" (e.g. "$2b$12$...").  Older SHA-256
# hashes in the DB use the shape "<32-hex-salt>:<64-hex-digest>".

_BCRYPT_ROUNDS = 12


def _hash_password(password: str) -> str:
    """Return a bcrypt hash string (includes salt + cost factor)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("utf-8")


def _is_legacy_sha256(stored: str) -> bool:
    """True if the stored hash is the old 'salt:sha256_hex' format."""
    if not stored or stored.startswith("$2"):
        return False
    if ":" not in stored:
        return False
    salt, digest = stored.split(":", 1)
    return len(salt) == 32 and len(digest) == 64


def _verify_legacy_sha256(password: str, stored: str) -> bool:
    salt, _ = stored.split(":", 1)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}" == stored


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored bcrypt or legacy SHA-256 hash."""
    if not stored:
        return False
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    if _is_legacy_sha256(stored):
        return _verify_legacy_sha256(password, stored)
    return False


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
        resp = (
            self._sb.table("users")
            .select("email, profile_name, password_hash, role")
            .eq("email", email.strip().lower())
            .maybe_single()
            .execute()
        )
        row = resp.data if resp else None
        if not row:
            return None
        stored = row["password_hash"]
        if not _verify_password(password, stored):
            return None
        # Transparent rehash: upgrade legacy SHA-256 records to bcrypt
        if _is_legacy_sha256(stored):
            try:
                new_hash = _hash_password(password)
                self._sb.table("users").update(
                    {"password_hash": new_hash}
                ).eq("email", row["email"]).execute()
            except Exception:
                pass
        return User(
            email=row["email"],
            profile_name=row["profile_name"],
            role=row["role"],
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
        if existing and existing.data:
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
        resp = (
            self._sb.table("users")
            .select("email")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        if not resp or not resp.data:
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
