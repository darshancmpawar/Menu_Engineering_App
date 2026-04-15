"""Shared Supabase client — one connection per process.

Consumers (client_config, auth_manager, api.app) import ``get_supabase``
from this module so they all reuse the same ``supabase.Client`` instance
rather than each maintaining their own singleton.
"""

from __future__ import annotations

import os
import threading

_sb_client = None
_sb_lock = threading.Lock()


def get_supabase():
    """Return a process-wide Supabase client, created lazily on first use."""
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
