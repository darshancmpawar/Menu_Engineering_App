"""
Client Editor — Create new clients or select existing ones.

When creating a client, the user picks categories (slot types).
The system auto-assigns an existing menu_category if one matches,
or creates a new one transparently.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
from ui.api_client import MenuApiClient
from ui.formatters import prettify_slot_name


def render_client_editor(api: MenuApiClient, metadata: dict) -> Optional[str]:
    """Render the client management section. Returns the selected client name."""

    clients = metadata.get('clients', [])
    base_slot_names = metadata.get('base_slot_names', [])
    const_slots = set(metadata.get('const_slots', []))

    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#f5f5f5;margin:0 0 0.75rem;">'
        'Client Management</p>',
        unsafe_allow_html=True,
    )

    # --- Tabs: Select / Create ---
    tab_select, tab_create = st.tabs(["Select Existing", "Create New"])

    selected_client: Optional[str] = None

    with tab_select:
        if not clients:
            st.info("No clients found. Switch to the **Create New** tab to add one.")
        else:
            selected_client = st.selectbox(
                "Client",
                clients,
                key="editor_client_select",
                label_visibility="collapsed",
            )

    with tab_create:
        new_name = st.text_input("Client Name", key="editor_new_client_name",
                                 placeholder="e.g. Acme Corp")

        # Category picker — user selects which categories (slot types) the client needs
        choosable = [s for s in base_slot_names if s not in const_slots]
        new_categories = st.multiselect(
            "Select Categories",
            options=choosable,
            default=choosable,
            format_func=prettify_slot_name,
            key="editor_new_client_categories",
        )

        if new_categories:
            st.caption(
                f"{len(new_categories)} categories selected: "
                f"{', '.join(prettify_slot_name(s) for s in new_categories)}"
            )

        if st.button("Create Client", type="primary", key="editor_create_client_btn",
                     use_container_width=True):
            name = (new_name or '').strip()
            if not name:
                st.error("Enter a client name.")
            elif name in clients:
                st.error(f"Client '{name}' already exists.")
            elif not new_categories:
                st.error("Select at least one category.")
            else:
                try:
                    api.create_client(name, new_categories)
                    st.session_state['editor_success_msg'] = f"Client '{name}' created successfully"
                    st.session_state.pop('editor_new_client_name', None)
                    st.session_state.pop('editor_new_client_categories', None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")

    return selected_client
