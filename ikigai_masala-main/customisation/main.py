"""
Customisation Editor — Main page that orchestrates all editor sections.

Two flows:
  Select Existing: select client → edit categories/frequency/themes → Save | Reset
  Create New:      enter name → pick categories/frequency/themes → Create Client | Reset Setup

Called from app.py when st.session_state.view == "editor".
"""

import streamlit as st
from ui.api_client import MenuApiClient
from ui.formatters import prettify_slot_name
from customisation.slot_editor import render_slot_editor
from customisation.multi_slot_editor import render_multi_slot_editor
from customisation.theme_editor import render_theme_editor


def _inject_editor_css():
    st.markdown("""
    <style>
        .editor-title {
            font-size: 1.4rem; font-weight: 700; color: #f5f5f5;
            letter-spacing: -0.3px; margin: 0;
        }
        .editor-subtitle {
            font-size: 0.78rem; color: #737373; margin: 0.15rem 0 0;
        }
    </style>
    """, unsafe_allow_html=True)


def render_customisation_editor(api: MenuApiClient):
    """Main entry point for the customisation editor view."""
    _inject_editor_css()

    # --- Top bar ---
    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("< Back to Menu", key="editor_back_btn", use_container_width=True):
            st.session_state.view = "planner"
            st.rerun()
    with col_title:
        st.markdown(
            '<div><p class="editor-title">Customisation Editor</p>'
            '<p class="editor-subtitle">Create or edit clients, categories, frequency, and day themes</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # --- Show success message ---
    if st.session_state.get('editor_success_msg'):
        st.success(st.session_state.pop('editor_success_msg'))

    # --- Load metadata ---
    try:
        metadata = api.get_editor_metadata()
    except Exception as e:
        st.error(f"Failed to load editor data: {e}")
        return

    clients = metadata.get('clients', [])
    all_base_slots = metadata.get('base_slot_names', [])
    const_slots = metadata.get('const_slots', [])
    default_theme_map = metadata.get('default_theme_map', {})
    available_themes = metadata.get('available_themes', [])
    menu_categories = metadata.get('menu_categories', {})

    # ============================================================
    # Section 1: Client Management (Tabs)
    # ============================================================
    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#f5f5f5;margin:0 0 0.75rem;">'
        'Client Management</p>',
        unsafe_allow_html=True,
    )

    tab_select, tab_create = st.tabs(["Select Existing", "Create New"])

    selected_client = None
    with tab_select:
        if not clients:
            st.info("No clients found. Switch to the **Create New** tab to add one.")
        else:
            selected_client = st.selectbox(
                "Client", clients,
                key="editor_client_select",
                label_visibility="collapsed",
            )

    new_client_name = ""
    with tab_create:
        new_client_name = st.text_input(
            "Client Name", key="editor_new_client_name",
            placeholder="e.g. Acme Corp",
        )

    # Determine mode: if on Create New tab, selected_client is None
    # Streamlit sets selected_client to None when Create tab is active
    is_create_mode = selected_client is None

    # For Select Existing: load config from DB
    # For Create New: use defaults
    if not is_create_mode:
        try:
            config = api.get_client_config(selected_client)
        except Exception as e:
            st.error(f"Failed to load config for {selected_client}: {e}")
            return
        current_active = config.get('active_base_slots', [])
        current_counts = config.get('slot_counts', {})
        current_theme = config.get('theme_map', dict(default_theme_map))
        client_key = selected_client  # for widget keys
    else:
        if not new_client_name.strip():
            st.markdown(
                '<p style="color:#737373;text-align:center;padding:2rem;">'
                'Enter a client name above to start configuring.</p>',
                unsafe_allow_html=True,
            )
            return
        # Defaults for new client: all non-constant categories active
        current_active = [s for s in all_base_slots if s not in set(const_slots)]
        current_counts = {s: 1 for s in all_base_slots}
        current_theme = dict(default_theme_map)
        client_key = "_new_"

    # ============================================================
    # Section 2: Customize Categories
    # ============================================================
    st.divider()
    new_active_slots = render_slot_editor(
        all_base_slots, current_active, const_slots, client_key,
    )

    # --- Show auto-mapped menu category ---
    if new_active_slots:
        sorted_selected = sorted(new_active_slots)
        matched_cat = None
        for cat_name, cat_slots in menu_categories.items():
            if sorted(cat_slots) == sorted_selected:
                matched_cat = cat_name
                break
        if matched_cat:
            st.markdown(
                f'<p style="font-size:0.75rem;color:#86efac;margin:0.25rem 0 0;">'
                f'Mapped to existing menu category: <b>{matched_cat}</b></p>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p style="font-size:0.75rem;color:#fdba74;margin:0.25rem 0 0;">'
                'New menu category will be created for this combination.</p>',
                unsafe_allow_html=True,
            )

    # ============================================================
    # Section 3: Item Frequency (Multi-Category)
    # ============================================================
    st.divider()
    new_slot_counts = render_multi_slot_editor(
        new_active_slots, current_counts, const_slots, client_key,
    )

    # ============================================================
    # Section 4: Day-wise Theme Override
    # ============================================================
    st.divider()
    new_theme_map = render_theme_editor(
        current_theme, default_theme_map, available_themes, client_key,
    )

    # ============================================================
    # Action bar
    # ============================================================
    st.divider()

    # Unsaved changes indicator (only for select mode)
    if not is_create_mode:
        changes = []
        if set(new_active_slots) != set(current_active):
            changes.append("categories")
        count_changes = {k: v for k, v in new_slot_counts.items()
                         if v != current_counts.get(k, 1) and k in new_active_slots}
        if count_changes:
            changes.append("frequency")
        theme_changes = {k: v for k, v in new_theme_map.items()
                         if v != current_theme.get(k)}
        if theme_changes:
            changes.append("themes")
        if changes:
            st.markdown(
                f'<p style="color:#fdba74;font-size:0.82rem;margin:0 0 0.5rem;">'
                f'Unsaved changes: {", ".join(changes)}</p>',
                unsafe_allow_html=True,
            )

    if is_create_mode:
        # --- Create New flow: Create Client | Reset Setup ---
        col_create, col_reset = st.columns(2)

        with col_create:
            create_clicked = st.button(
                "Create Client", type="primary",
                key="editor_create_btn", use_container_width=True,
            )

        with col_reset:
            reset_clicked = st.button(
                "Reset Setup",
                key="editor_reset_new", use_container_width=True,
            )

        if create_clicked:
            name = new_client_name.strip()
            if not name:
                st.error("Enter a client name.")
            elif name in clients:
                st.error(f"Client '{name}' already exists.")
            elif not new_active_slots:
                st.error("Select at least one category.")
            else:
                try:
                    api.create_client(name, new_active_slots)
                    # Save frequency overrides if any differ from 1
                    freq_overrides = {k: v for k, v in new_slot_counts.items()
                                      if k in new_active_slots and v != 1}
                    theme_overrides = {k: v for k, v in new_theme_map.items()
                                       if v != default_theme_map.get(k)}
                    if freq_overrides or theme_overrides:
                        payload = {}
                        if freq_overrides:
                            payload['slot_counts'] = new_slot_counts
                        if theme_overrides:
                            payload['theme_map'] = new_theme_map
                        api.update_client_config(name, payload)
                    st.session_state['editor_success_msg'] = f"Client '{name}' created successfully!"
                    st.session_state.pop('editor_new_client_name', None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")

        if reset_clicked:
            # Clear all create-mode widget state
            for key in list(st.session_state.keys()):
                if '_new_' in key or key == 'editor_new_client_name':
                    st.session_state.pop(key, None)
            st.rerun()

    else:
        # --- Select Existing flow: Save | Reset ---
        col_save, col_reset = st.columns(2)

        with col_save:
            save_clicked = st.button(
                "Save", type="primary",
                key="editor_save_all", use_container_width=True,
            )

        with col_reset:
            reset_clicked = st.button(
                "Reset to Defaults",
                key="editor_reset_all", use_container_width=True,
            )

        if save_clicked:
            payload = {}
            if set(new_active_slots) != set(current_active):
                payload['active_base_slots'] = new_active_slots
            count_overrides = {k: v for k, v in new_slot_counts.items()
                               if k in new_active_slots}
            payload['slot_counts'] = count_overrides
            payload['theme_map'] = new_theme_map
            try:
                api.update_client_config(selected_client, payload)
                st.session_state['editor_success_msg'] = f"Configuration saved for {selected_client}"
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

        if reset_clicked:
            payload = {
                'active_base_slots': list(all_base_slots),
                'slot_counts': {s: 1 for s in all_base_slots},
                'theme_map': dict(default_theme_map),
            }
            try:
                api.update_client_config(selected_client, payload)
                st.session_state['editor_success_msg'] = f"Reset {selected_client} to defaults"
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")
