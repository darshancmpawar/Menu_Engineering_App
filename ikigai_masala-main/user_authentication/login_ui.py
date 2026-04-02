"""Login form UI component."""

from __future__ import annotations

import streamlit as st

from user_authentication.auth_manager import AuthManager
from user_authentication.session import login_user


def render_login_form():
    """Render a centered login form. Returns True if user just logged in."""
    st.markdown("""
    <style>
        .login-container {
            max-width: 400px; margin: 6rem auto; padding: 2rem;
            background: #171717; border: 1px solid #262626; border-radius: 12px;
        }
        .login-title {
            font-size: 1.3rem; font-weight: 700; color: #f5f5f5;
            text-align: center; margin-bottom: 0.25rem;
        }
        .login-subtitle {
            font-size: 0.8rem; color: #737373; text-align: center;
            margin-bottom: 1.5rem;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            '<p class="login-title">Ikigai Masala</p>'
            '<p class="login-subtitle">Sign in to continue</p>',
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
                return False
            try:
                auth = AuthManager()
                user = auth.authenticate(email, password)
                if user:
                    login_user(user)
                    st.rerun()
                else:
                    st.error("Invalid email or password.")
            except Exception as e:
                st.error(f"Login error: {e}")
            return False
    return False
