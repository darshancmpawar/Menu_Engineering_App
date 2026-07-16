"""
Customisation Editor — create / edit clients with single or multi cuisine
counters, styled with the Pulse (OP Lens) light design language.

Flow (top to bottom):
  Step 1  Client        — select an existing client or type a new name
  Step 2  Counter setup — Single Cuisine Counter vs Multi Cuisine Counter;
                          for multi, pick how many counters
  Step 3  Configure     — per counter: food categories, frequency, day themes

Called from app.py when st.session_state.view == "editor".
"""

from typing import Dict, List

import streamlit as st

from ui.api_client import MenuApiClient
from ui.branding import logo_img_tag
from customisation.pulse import PULSE_EDITOR_CSS
from customisation.counter_editor import render_counter_editor


def _default_counter(idx: int, all_base_slots: List[str], const_slots: List[str],
                     default_theme_map: Dict[str, str]) -> Dict:
    """Build a fresh counter config from editor metadata."""
    cats = [s for s in all_base_slots if s not in const_slots]
    return {
        'name': f'Counter {idx + 1}',
        'categories': list(cats),
        'slot_counts': {s: 1 for s in cats},
        'theme_map': dict(default_theme_map),
    }


def _step_header(num: int, title: str, desc: str) -> None:
    st.markdown(
        f'<div class="pulse-step">'
        f'<span class="pulse-step-badge">{num}</span>'
        f'<p class="pulse-step-title">{title}</p></div>'
        f'<p class="pulse-step-desc">{desc}</p>',
        unsafe_allow_html=True,
    )


def _counters_equal(a: List[Dict], b: List[Dict]) -> bool:
    """Structural comparison of two counter lists (order matters)."""
    if len(a) != len(b):
        return False
    for ca, cb in zip(a, b):
        if (ca.get('name') != cb.get('name')
                or sorted(ca.get('categories', [])) != sorted(cb.get('categories', []))
                or ca.get('slot_counts', {}) != cb.get('slot_counts', {})
                or ca.get('theme_map', {}) != cb.get('theme_map', {})):
            return False
    return True


def render_customisation_editor(api: MenuApiClient):
    """Main entry point for the customisation editor view."""
    st.markdown(PULSE_EDITOR_CSS, unsafe_allow_html=True)

    # --- Top bar ---
    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("< Back to Menu", key="editor_back_btn", use_container_width=True):
            st.session_state.view = "planner"
            st.rerun()
    with col_title:
        _logo = logo_img_tag(height=34, extra_style="flex-shrink:0;")
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:0.7rem;">{_logo}'
            '<div><p class="pulse-title">Customisation Editor</p>'
            '<p class="pulse-subtitle">Create or edit clients, cuisine counters, '
            'categories, frequency, and day themes</p></div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

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
    max_counters = int(metadata.get('max_counters', 6) or 6)

    # ============================================================
    # Step 1 — Client
    # ============================================================
    with st.container(border=True):
        _step_header(1, "Client", "Select an existing client or create a new one.")

        mode = st.radio(
            "Mode", ["Select Existing", "Create New"],
            horizontal=True, key="editor_mode", label_visibility="collapsed",
        )
        is_create_mode = (mode == "Create New")

        selected_client = None
        new_client_name = ""

        if not is_create_mode:
            if not clients:
                st.info("No clients yet. Switch to **Create New** to add one.")
                return
            selected_client = st.selectbox(
                "Client", clients, key="editor_client_select",
                label_visibility="collapsed",
            )
        else:
            new_client_name = st.text_input(
                "Client Name", key="editor_new_client_name",
                placeholder="e.g. Acme Corp",
            )

    # --- Resolve the config + counters we start from ---
    if not is_create_mode:
        try:
            config = api.get_client_config(selected_client)
        except Exception as e:
            st.error(f"Failed to load config for {selected_client}: {e}")
            return
        loaded_mode = config.get('counter_mode', 'single')
        loaded_counters = config.get('counters') or [
            _default_counter(0, all_base_slots, const_slots, default_theme_map)
        ]
        current_version = config.get('version')
        client_key = f"exist_{selected_client}"
    else:
        if not new_client_name.strip():
            st.markdown(
                '<div style="text-align:center;padding:2.5rem;color:#AEAEAE;">'
                'Enter a client name above to start configuring counters.</div>',
                unsafe_allow_html=True,
            )
            return
        loaded_mode = 'single'
        loaded_counters = [
            _default_counter(0, all_base_slots, const_slots, default_theme_map)
        ]
        current_version = None
        client_key = "_new_"

    # ============================================================
    # Step 2 — Counter setup
    # ============================================================
    with st.container(border=True):
        _step_header(
            2, "Cuisine Counter Setup",
            "A single counter serves one cuisine plan. Multiple counters let "
            "you run independent stations, each with its own categories, "
            "frequency, and day themes.",
        )

        counter_choice = st.radio(
            "Counter type",
            ["Single Cuisine Counter", "Multi Cuisine Counter"],
            index=(1 if loaded_mode == 'multi' else 0),
            horizontal=True,
            key=f"counter_mode_{client_key}",
            label_visibility="collapsed",
        )
        is_multi = (counter_choice == "Multi Cuisine Counter")

        if is_multi:
            default_num = max(2, len(loaded_counters) if loaded_mode == 'multi' else 2)
            default_num = min(default_num, max_counters)
            num_counters = int(st.number_input(
                "Number of counters",
                min_value=2, max_value=max_counters, value=default_num, step=1,
                key=f"num_counters_{client_key}",
                help=f"Between 2 and {max_counters} counters.",
            ))
        else:
            num_counters = 1

    # ============================================================
    # Step 3 — Configure counters
    # ============================================================
    _step_header(
        3, "Configure Counters",
        "For each counter, choose its food categories, how many items per "
        "category, and the theme for each weekday.",
    )

    def _counter_seed(i: int) -> Dict:
        if i < len(loaded_counters):
            return loaded_counters[i]
        return _default_counter(i, all_base_slots, const_slots, default_theme_map)

    result_counters: List[Dict] = []

    if not is_multi:
        result_counters.append(
            render_counter_editor(
                _counter_seed(0), 0, metadata,
                key_prefix=f"{client_key}__c0", show_name=False,
            )
        )
    else:
        # Tab labels reflect the (possibly edited) counter name from the
        # previous rerun, falling back to the seed / default name.
        labels = []
        for i in range(num_counters):
            edited = st.session_state.get(f"cname_{client_key}__c{i}")
            labels.append((edited or _counter_seed(i).get('name') or f"Counter {i + 1}"))
        tabs = st.tabs(labels)
        for i, tab in enumerate(tabs):
            with tab:
                result_counters.append(
                    render_counter_editor(
                        _counter_seed(i), i, metadata,
                        key_prefix=f"{client_key}__c{i}", show_name=True,
                    )
                )

    counter_mode = 'multi' if is_multi else 'single'
    empty_counters = [c['name'] for c in result_counters if not c['categories']]

    # ============================================================
    # Action bar
    # ============================================================
    st.markdown("")

    if not is_create_mode:
        dirty = (
            counter_mode != loaded_mode
            or not _counters_equal(result_counters, loaded_counters)
        )
        if dirty:
            st.markdown(
                '<div class="pulse-changes">&#9679; Unsaved changes</div>',
                unsafe_allow_html=True,
            )

    if empty_counters:
        st.markdown(
            f'<p class="pulse-hint warn">Every counter needs at least one '
            f'food category. Missing: {", ".join(empty_counters)}.</p>',
            unsafe_allow_html=True,
        )

    if is_create_mode:
        col_create, col_reset = st.columns(2)
        with col_create:
            create_clicked = st.button(
                "Create Client", type="primary",
                key="editor_create_btn", use_container_width=True,
            )
        with col_reset:
            reset_clicked = st.button(
                "Reset Setup", key="editor_reset_new", use_container_width=True,
            )

        if create_clicked:
            name = new_client_name.strip()
            if not name:
                st.error("Enter a client name.")
            elif name in clients:
                st.error(f"Client '{name}' already exists.")
            elif empty_counters:
                st.error("Give every counter at least one food category.")
            else:
                try:
                    api.create_client(
                        name, counter_mode=counter_mode, counters=result_counters,
                    )
                    st.cache_data.clear()
                    st.session_state['editor_success_msg'] = (
                        f"Client '{name}' created with "
                        f"{len(result_counters)} counter"
                        f"{'s' if len(result_counters) != 1 else ''}."
                    )
                    _clear_new_client_state()
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")

        if reset_clicked:
            _clear_new_client_state()
            st.rerun()

    else:
        col_save, col_reset, col_delete = st.columns(3)
        with col_save:
            save_clicked = st.button(
                "Save", type="primary",
                key="editor_save_all", use_container_width=True,
            )
        with col_reset:
            reset_clicked = st.button(
                "Reset to Defaults", key="editor_reset_all",
                use_container_width=True,
            )
        with col_delete:
            delete_clicked = st.button(
                "Delete Client", key="editor_delete_btn",
                use_container_width=True,
            )

        if save_clicked:
            if empty_counters:
                st.error("Give every counter at least one food category.")
            else:
                payload = {
                    'version': current_version,
                    'counter_mode': counter_mode,
                    'counters': result_counters,
                }
                try:
                    api.update_client_config(selected_client, payload)
                    st.session_state['editor_success_msg'] = (
                        f"Configuration saved for {selected_client}."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

        if reset_clicked:
            payload = {
                'version': current_version,
                'counter_mode': 'single',
                'counters': [
                    _default_counter(0, all_base_slots, const_slots, default_theme_map)
                ],
            }
            try:
                api.update_client_config(selected_client, payload)
                st.session_state['editor_success_msg'] = (
                    f"Reset {selected_client} to a single default counter."
                )
                # Drop the per-widget state for this client so the reloaded
                # defaults render instead of the stale edited values.
                _clear_client_state(client_key)
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")

        if delete_clicked:
            try:
                api.delete_client(selected_client)
                st.cache_data.clear()
                st.session_state['editor_success_msg'] = (
                    f"Client '{selected_client}' deleted."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Delete failed: {e}")


def _clear_new_client_state() -> None:
    """Drop all widget state tied to the in-progress new client."""
    for key in list(st.session_state.keys()):
        if key == 'editor_new_client_name' or '_new_' in key:
            st.session_state.pop(key, None)


def _clear_client_state(client_key: str) -> None:
    """Drop per-counter widget state for a specific client key."""
    for key in list(st.session_state.keys()):
        if client_key in key:
            st.session_state.pop(key, None)
