"""
Client Editor — Create new clients or select existing ones.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
from ui.api_client import MenuApiClient
from ui.formatters import prettify_slot_name


def render_client_editor(api: MenuApiClient, metadata: dict) -> Optional[str]:
    """Render the client management section. Returns the selected client name."""

    clients = metadata.get('clients', [])
    categories = metadata.get('menu_categories', {})
    cat_names = sorted(categories.keys())

    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#f5f5f5;margin:0 0 0.75rem;">'
        'Client Management</p>',
        unsafe_allow_html=True,
    )

    # --- Tabs: Select / Create ---
    tab_select, tab_create = st.tabs(["Select Existing", "Create New"])

    with tab_select:
        if not clients:
            st.info("No clients found.")
            return None

        selected = st.selectbox(
            "Client",
            clients,
            key="editor_client_select",
            label_visibility="collapsed",
        )
        return selected

    with tab_create:
        new_name = st.text_input("Client Name", key="editor_new_client_name",
                                 placeholder="e.g. Acme Corp")

        cat_labels = {k: f"{k} ({len(v)} slots)" for k, v in categories.items()}
        new_cat = st.selectbox(
            "Menu Category",
            cat_names,
            format_func=lambda k: cat_labels.get(k, k),
            key="editor_new_client_cat",
        )

        if new_cat:
            slots = categories.get(new_cat, [])
            st.caption(f"Slots: {', '.join(prettify_slot_name(s) for s in slots)}")

        if st.button("Create Client", type="primary", key="editor_create_client_btn",
                     use_container_width=True):
            name = (new_name or '').strip()
            if not name:
                st.error("Enter a client name.")
            elif name in clients:
                st.error(f"Client '{name}' already exists.")
            else:
                try:
                    api.create_client(name, new_cat)
                    st.toast(f"Created {name}", icon="✓")
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")

        return None
