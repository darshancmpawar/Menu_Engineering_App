"""
Customisation Editor — Main page that orchestrates all 4 editor sections.

Sections:
  1. Client Management (create / select)
  2. Slot Customization (toggle base slots)
  3. Multi-Slot Configuration (slot count overrides)
  4. Day-wise Theme Overrides

Action bar at the bottom: Save | Reset | Delete

Called from app.py when st.session_state.view == "editor".
"""

import streamlit as st
from ui.api_client import MenuApiClient
from customisation.client_editor import render_client_editor
from customisation.slot_editor import render_slot_editor
from customisation.multi_slot_editor import render_multi_slot_editor
from customisation.theme_editor import render_theme_editor


def _inject_editor_css():
    """Inject editor-specific styles (same dark palette as main app)."""
    st.markdown("""
    <style>
        .editor-title {
            font-size: 1.4rem; font-weight: 700; color: #f5f5f5;
            letter-spacing: -0.3px; margin: 0;
        }
        .editor-subtitle {
            font-size: 0.78rem; color: #737373; margin: 0.15rem 0 0;
        }
        .editor-section {
            background: #171717; border: 1px solid #262626;
            border-radius: 10px; padding: 1.25rem; margin-bottom: 1rem;
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
            '<p class="editor-subtitle">Create or edit clients, slots, multi-slots, and day themes</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # --- Load metadata ---
    try:
        metadata = api.get_editor_metadata()
    except Exception as e:
        st.error(f"Failed to load editor data: {e}")
        return

    # ============================================================
    # Section 1: Client Management
    # ============================================================
    with st.container():
        st.markdown('<div class="editor-section">', unsafe_allow_html=True)
        selected_client = render_client_editor(api, metadata)
        st.markdown('</div>', unsafe_allow_html=True)

    if not selected_client:
        st.markdown(
            '<p style="color:#737373;text-align:center;padding:2rem;">'
            'Select or create a client above to configure their menu settings.</p>',
            unsafe_allow_html=True,
        )
        return

    # --- Load client config ---
    try:
        config = api.get_client_config(selected_client)
    except Exception as e:
        st.error(f"Failed to load config for {selected_client}: {e}")
        return

    all_base_slots = metadata.get('base_slot_names', [])
    const_slots = metadata.get('const_slots', [])
    default_theme_map = metadata.get('default_theme_map', {})
    available_themes = metadata.get('available_themes', [])

    current_active = config.get('active_base_slots', [])
    current_counts = config.get('slot_counts', {})
    current_theme = config.get('theme_map', dict(default_theme_map))

    # ============================================================
    # Section 2: Slot Customization
    # ============================================================
    with st.container():
        st.markdown('<div class="editor-section">', unsafe_allow_html=True)
        new_active_slots = render_slot_editor(all_base_slots, current_active, const_slots)
        st.markdown('</div>', unsafe_allow_html=True)

    # ============================================================
    # Section 3: Multi-Slot Configuration
    # ============================================================
    with st.container():
        st.markdown('<div class="editor-section">', unsafe_allow_html=True)
        new_slot_counts = render_multi_slot_editor(new_active_slots, current_counts, const_slots)
        st.markdown('</div>', unsafe_allow_html=True)

    # ============================================================
    # Section 4: Day-wise Theme Override
    # ============================================================
    with st.container():
        st.markdown('<div class="editor-section">', unsafe_allow_html=True)
        new_theme_map = render_theme_editor(current_theme, default_theme_map, available_themes)
        st.markdown('</div>', unsafe_allow_html=True)

    # ============================================================
    # Action bar: Save | Reset | Delete
    # ============================================================
    st.markdown("")
    st.divider()

    # Unsaved changes indicator
    changes = []
    if set(new_active_slots) != set(current_active):
        changes.append("slots")
    count_changes = {k: v for k, v in new_slot_counts.items()
                     if v != current_counts.get(k, 1) and k in new_active_slots}
    if count_changes:
        changes.append("multi-slots")
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

    # --- Three action buttons in one row ---
    col_save, col_reset, col_delete = st.columns(3)

    with col_save:
        save_clicked = st.button(
            "Save",
            type="primary",
            key="editor_save_all",
            use_container_width=True,
        )

    with col_reset:
        reset_clicked = st.button(
            "Reset to Defaults",
            key="editor_reset_all",
            use_container_width=True,
        )

    with col_delete:
        if not st.session_state.editor_confirm_delete:
            delete_clicked = st.button(
                "Delete Client",
                key="editor_delete_client",
                use_container_width=True,
            )
            if delete_clicked:
                st.session_state.editor_confirm_delete = True
                st.rerun()
        else:
            st.warning(f"Delete **{selected_client}**? This cannot be undone.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirm Delete", type="primary", key="editor_confirm_del_btn"):
                    try:
                        api.delete_client(selected_client)
                        st.session_state.editor_confirm_delete = False
                        st.session_state.pop('editor_client_select', None)
                        st.toast(f"Deleted {selected_client}", icon="✓")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")
            with c2:
                if st.button("Cancel", key="editor_cancel_del_btn"):
                    st.session_state.editor_confirm_delete = False
                    st.rerun()

    # --- Handle Save ---
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
            st.toast(f"Saved configuration for {selected_client}", icon="✓")
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")

    # --- Handle Reset ---
    if reset_clicked:
        payload = {
            'active_base_slots': list(all_base_slots),
            'slot_counts': {s: 1 for s in all_base_slots},
            'theme_map': dict(default_theme_map),
        }
        try:
            api.update_client_config(selected_client, payload)
            st.toast(f"Reset {selected_client} to defaults", icon="✓")
            st.rerun()
        except Exception as e:
            st.error(f"Reset failed: {e}")
