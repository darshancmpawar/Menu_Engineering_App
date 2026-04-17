"""Bearer-token auth for the Flask API.

Tokens are URL-safe signed payloads issued by ``POST /api/v1/auth/login``
and verified by ``require_api_auth``. Tokens are self-contained and
time-limited; the server keeps no session state.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Callable, Optional

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.config import API_SECRET_KEY, API_TOKEN_TTL_SECONDS
from user_authentication.auth_manager import AuthManager
from user_authentication.models import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER

logger = logging.getLogger(__name__)

_SALT = "menu-api-auth-v1"
_DEV_FALLBACK_KEY = "dev-insecure-do-not-use-in-production"

# Role hierarchy: higher rank implies all lower privileges.
_ROLE_RANK = {ROLE_USER: 1, ROLE_ADMIN: 2, ROLE_SUPER_ADMIN: 3}


def _secret_key() -> str:
    if API_SECRET_KEY:
        return API_SECRET_KEY
    logger.warning(
        "API_SECRET_KEY not set; using an insecure dev fallback. "
        "Set API_SECRET_KEY before deploying."
    )
    return _DEV_FALLBACK_KEY


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret_key(), salt=_SALT)


def issue_token(email: str, role: str) -> str:
    return _serializer().dumps({"email": email, "role": role})


def decode_token(token: str) -> dict:
    return _serializer().loads(token, max_age=API_TOKEN_TTL_SECONDS)


def _extract_bearer_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header[len("Bearer "):].strip() or None


def require_api_auth(*, min_role: str = ROLE_USER) -> Callable:
    """Decorator: require a valid bearer token with at least ``min_role``.

    Decoded payload is attached to ``flask.g.api_user``.
    """
    if min_role not in _ROLE_RANK:
        raise ValueError(f"Unknown role: {min_role}")
    required_rank = _ROLE_RANK[min_role]

    def wrap(fn: Callable) -> Callable:
        @wraps(fn)
        def inner(*args, **kwargs):
            token = _extract_bearer_token()
            if not token:
                return jsonify({"success": False, "error": "Missing bearer token"}), 401
            try:
                payload = decode_token(token)
            except SignatureExpired:
                return jsonify({"success": False, "error": "Token expired"}), 401
            except BadSignature:
                return jsonify({"success": False, "error": "Invalid token"}), 401
            user_role = payload.get("role")
            if user_role not in _ROLE_RANK:
                return jsonify({"success": False, "error": "Invalid role in token"}), 403
            if _ROLE_RANK[user_role] < required_rank:
                return jsonify({"success": False, "error": "Insufficient role"}), 403
            g.api_user = payload
            return fn(*args, **kwargs)

        return inner

    return wrap


def api_login():
    """POST /api/v1/auth/login — exchange credentials for a bearer token."""
    try:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        if not email or not password:
            return jsonify({"success": False, "error": "email and password required"}), 400

        user = AuthManager().authenticate(email, password)
        if user is None:
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        return jsonify({
            "success": True,
            "token": issue_token(user.email, user.role),
            "email": user.email,
            "role": user.role,
            "profile_name": user.profile_name,
            "ttl_seconds": API_TOKEN_TTL_SECONDS,
        })
    except Exception:
        logger.exception("Login failed unexpectedly")
        return jsonify({"success": False, "error": "Login error"}), 500
