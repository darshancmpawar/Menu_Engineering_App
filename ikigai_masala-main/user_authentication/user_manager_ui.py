"""User management UI — create, list, delete users (role-gated)."""

from __future__ import annotations

import streamlit as st

from user_authentication.auth_manager import AuthManager
from user_authentication.session import current_user
from user_authentication.models import ROLE_SUPER_ADMIN


def render_user_manager():
    """Render user management page. Only accessible to super_admin and admin."""
    user = current_user()
    if user is None:
        return

    auth = AuthManager()

    st.markdown(
        '<p style="font-size:1.2rem;font-weight:700;color:#f5f5f5;margin:0 0 0.5rem;">'
        'User Management</p>',
        unsafe_allow_html=True,
    )

    # --- Show success/error ---
    if st.session_state.get("user_mgmt_msg"):
        msg_type, msg_text = st.session_state.pop("user_mgmt_msg")
        if msg_type == "success":
            st.success(msg_text)
        else:
            st.error(msg_text)

    # ---- Create user form ----
    creatable = user.creatable_roles
    if creatable:
        st.markdown("**Create User**")
        with st.form("create_user_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_email = st.text_input("Email", placeholder="user@example.com")
                new_password = st.text_input("Password", type="password")
            with col2:
                new_name = st.text_input("Profile Name", placeholder="John Doe")
                new_role = st.selectbox("Role", creatable)
            create_submitted = st.form_submit_button(
                "Create User", use_container_width=True,
            )

        if create_submitted:
            try:
                auth.create_user(new_email, new_name, new_password, new_role)
                st.session_state["user_mgmt_msg"] = (
                    "success",
                    f"User '{new_email}' created as {new_role}.",
                )
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Failed to create user: {e}")

    # ---- User list ----
    st.divider()
    st.markdown("**Existing Users**")

    try:
        users = auth.list_users()
    except Exception as e:
        st.error(f"Failed to load users: {e}")
        return

    if not users:
        st.info("No users found.")
        return

    for u in users:
        col_info, col_action = st.columns([4, 1])
        with col_info:
            role_badge = {
                "super_admin": "🔴",
                "admin": "🟡",
                "user": "🟢",
            }.get(u.role, "⚪")
            st.markdown(
                f"{role_badge} **{u.profile_name}** — {u.email} "
                f'<span style="color:#737373;">({u.role})</span>',
                unsafe_allow_html=True,
            )
        with col_action:
            # Only super_admin can delete; can't delete yourself
            if user.role == ROLE_SUPER_ADMIN and u.email != user.email:
                if st.button("Delete", key=f"del_{u.email}"):
                    try:
                        auth.delete_user(u.email)
                        st.session_state["user_mgmt_msg"] = (
                            "success",
                            f"User '{u.email}' deleted.",
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")
