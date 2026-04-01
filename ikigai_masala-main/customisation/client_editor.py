"""
Client Editor — Create new clients or select existing ones.

Create New only asks for a name. After creation, the client's categories
are configured through the Customize Categories section and saved with
the main Save button.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
from ui.api_client import MenuApiClient


def render_client_editor(api: MenuApiClient, metadata: dict) -> Optional[str]:
    """Render the client management section. Returns the selected client name."""

    clients = metadata.get('clients', [])

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
        st.caption("After creation, configure categories, counts, and themes below, then click **Save**.")

        if st.button("Create Client", type="primary", key="editor_create_client_btn",
                     use_container_width=True):
            name = (new_name or '').strip()
            if not name:
                st.error("Enter a client name.")
            elif name in clients:
                st.error(f"Client '{name}' already exists.")
            else:
                try:
                    # Create with all base slots; user customizes via Customize Categories
                    base_slots = [s for s in metadata.get('base_slot_names', [])
                                  if s not in set(metadata.get('const_slots', []))]
                    api.create_client(name, base_slots)
                    st.session_state['editor_success_msg'] = (
                        f"Client '{name}' created! Now configure categories below and click Save."
                    )
                    st.session_state.pop('editor_new_client_name', None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")

    return selected_client
