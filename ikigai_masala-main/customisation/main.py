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

import html

import streamlit as st

from ui.api_client import MenuApiClient
from ui.branding import logo_img_tag
from ui.formatters import display_label_for_slot_id
from src.constants import DISPLAY_SLOT_ORDER
from customisation.pulse import PULSE_EDITOR_CSS
from customisation.counter_editor import render_counter_editor


def pools_for_city(metadata: Dict, city) -> List[str]:
    """Item-pool tokens offerable for *city*, and nothing else.

    A pool token names a pool inside ONE city's item list, so a Bangalore token on
    a Pune client would match nothing there — and the API rejects it on save. This
    deliberately does NOT fall back to ``available_client_pools`` (the cross-city
    union the endpoint returns when no city is given): offering the wrong city's
    pools is worse than offering none, so an API build without
    ``client_pools_by_city`` yields an empty list rather than a misleading one.
    """
    if not city:
        return []
    return list((metadata.get('client_pools_by_city') or {}).get(city, []))


def _default_counter(idx: int, all_base_slots: List[str], const_slots: List[str],
                     default_theme_map: Dict[str, str],
                     default_off_slots: List[str] = ()) -> Dict:
    """Build a fresh counter config from editor metadata.

    ``default_off_slots`` (e.g. curd_rice) are selectable but excluded from a
    new client's defaults.
    """
    skip = set(const_slots) | set(default_off_slots or ())
    cats = [s for s in all_base_slots if s not in skip]
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


def render_customisation_editor(api: MenuApiClient, *, launch_mode: bool = False):
    """Main entry point for the customisation editor view.

    ``launch_mode`` flags a client created here as a launch site — the launch
    view sets it from the sidebar toggle. The editor UI is otherwise identical
    in both modes (same UI/UX for launch and non-launch clients).
    """
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

    clients = metadata.get('clients', [])  # every client name — for the dup check
    # Clients WITH their city, for the city-first picker (city → clients of that
    # city, the same shape as the planner's sidebar). Falls back to the flat
    # name list (no city) if the detail call fails, and is launch-filtered in
    # the launch view (same scoping as the planner).
    try:
        clients_detail = api.list_clients_with_city()
    except Exception:  # noqa: BLE001 — never break the editor over this
        clients_detail = [{'name': n, 'city': None, 'is_launch_site': False}
                          for n in clients]
    if launch_mode:
        clients_detail = [c for c in clients_detail if c.get('is_launch_site')]
    all_base_slots = metadata.get('base_slot_names', [])
    const_slots = metadata.get('const_slots', [])
    default_off_slots = metadata.get('default_off_slots', [])
    default_theme_map = metadata.get('default_theme_map', {})
    available_cities = metadata.get('available_cities', [])
    default_cooldown = int(metadata.get('default_item_cooldown_days', 20) or 20)
    max_counters = int(metadata.get('max_counters', 6) or 6)

    # ============================================================
    # Step 1 — Client
    # ============================================================
    with st.container(border=True):
        _step_header(1, "Client",
                     "Pick a city, then a client served from it — or create a "
                     "new one in that city.")
        if launch_mode:
            st.caption("🚀 Launch view — the existing-client list shows launch "
                       "sites only; a new client created here is a launch site.")

        selected_client = None
        new_client_name = ""
        config = None

        # City FIRST — it filters the existing-client list to that city (and is
        # the city a new client is created in). Reordered above the client
        # picker per request; one City control, no cross-city editing. Cities
        # present among clients are unioned in so a client whose city is not in
        # AVAILABLE_CITIES is still reachable.
        city_options = sorted(
            set(available_cities)
            | {c['city'] for c in clients_detail if c.get('city')}
        )
        selected_city = st.selectbox(
            "City", city_options, key="editor_city_filter",
            help="The existing-client list below shows only this city's clients.",
        ) if city_options else None

        # Existing vs New client as two tabs. Streamlit tabs are visual-only
        # (the server can't tell which is active), so the signal for "create"
        # is a name typed on the New tab; otherwise we edit the selected
        # existing client.
        tab_existing, tab_new = st.tabs(["Existing client", "➕ New client"])
        with tab_new:
            new_client_name = st.text_input(
                "New client name", key="editor_new_client_name",
                placeholder="e.g. Acme Corp",
            )
        is_create_mode = bool(new_client_name.strip())
        with tab_existing:
            city_client_names = [
                c['name'] for c in clients_detail
                if (c.get('city') or None) == selected_city
            ]
            if city_client_names:
                selected_client = st.selectbox(
                    "Client", city_client_names,
                    key=f"editor_client_select_{selected_city}",
                    label_visibility="collapsed",
                )
            elif not is_create_mode:
                _noun = "launch sites" if launch_mode else "clients"
                st.info(f"No {_noun} in {selected_city or 'this city'}. Pick "
                        f"another city, or use the **New client** tab to add one.")

        if not is_create_mode:
            if not selected_client:
                return
            try:
                config = api.get_client_config(selected_client)
            except Exception as e:
                st.error(f"Failed to load config for {selected_client}: {e}")
                return

        # For an existing client the city equals its stored city (the list is
        # filtered by it), so the save sends it unchanged; for a new client it
        # is the city being created in.
        loaded_city = (config or {}).get('city') if not is_create_mode else None

        # Weekend-service toggle — when on, generated plans also cover Sat/Sun.
        loaded_serve_weekends = bool((config or {}).get('serve_weekends', False))
        serve_weekends = st.toggle(
            "Serve on weekends (Sat / Sun)",
            value=loaded_serve_weekends,
            key=f"editor_weekends_{'new' if is_create_mode else selected_client}",
            help="If on, menu generation includes Saturday/Sunday instead of "
                 "skipping them.",
        )

        # Item-cooldown window — how many days before a dish can repeat.
        _loaded_cooldown = (config or {}).get('item_cooldown_days')
        loaded_cooldown = (
            int(_loaded_cooldown) if _loaded_cooldown is not None
            else default_cooldown
        )
        item_cooldown_days = int(st.number_input(
            "Item cooldown (days)",
            min_value=0, max_value=60, value=loaded_cooldown, step=1,
            key=f"editor_cooldown_{'new' if is_create_mode else selected_client}",
            help="A dish served within this many days is not repeated. "
                 f"Default {default_cooldown}.",
        ))

    # ============================================================
    # Item Pools (F5) — which client item-pools feed this client
    # ============================================================
    # Pool tokens live inside ONE city's item list, so ONLY the selected city's
    # are offered. There is deliberately no fall back to the cross-city union
    # (`available_client_pools`): offering a Bangalore pool to a Pune client is
    # worse than offering none — the API rejects it on save, and the pool would
    # match nothing in Pune's list even if it didn't. An API build that predates
    # `client_pools_by_city` therefore shows an empty list, not the wrong one.
    available_client_pools = pools_for_city(metadata, selected_city)
    loaded_source_pools = (
        list((config or {}).get('source_pools') or [])
        if not is_create_mode else []
    )
    selected_source_pools = loaded_source_pools
    if selected_city:
        with st.container(border=True):
            st.markdown(
                '<p class="pulse-step-title">Item Pools</p>'
                '<p class="pulse-step-desc">Choose which client item-pools this '
                'client can draw from. <b>Common</b> is always included; add '
                'others to widen the available items. The client\'s own rules '
                'still apply to borrowed items.</p>',
                unsafe_allow_html=True,
            )
            st.caption("✓ Common — always included")
            if not available_client_pools:
                # Say so rather than rendering an empty control: a city whose item
                # list tags every dish `common` has no pools to pick, and silence
                # reads like a bug.
                st.caption(
                    f"{selected_city}'s item list has no per-client pools — every "
                    f"dish in it is shared, so this client already draws from all "
                    f"of it. Pools from other cities are not offered: they name "
                    f"pools inside those cities' lists and would match nothing "
                    f"here."
                )
                selected_source_pools = []
            else:
                selected_source_pools = st.multiselect(
                    "Additional item pools",
                    options=available_client_pools,
                    default=[p for p in loaded_source_pools
                             if p in available_client_pools],
                    key=f"editor_pools_{'new' if is_create_mode else selected_client}",
                    format_func=lambda s: s.title(),
                    help="An item is eligible if it belongs to Common or any "
                         "selected pool (exact match).",
                )
            try:
                preview = api.pool_preview(selected_source_pools, city=selected_city)
                cats = preview.get('category_counts', {})
                st.markdown(
                    f"**Eligible distinct items:** "
                    f"{preview.get('eligible_item_count', 0)}  \n"
                    f"*Pools: {', '.join(preview.get('active_pools', []))}*"
                )
                if cats:
                    top = sorted(cats.items(), key=lambda kv: -kv[1])
                    st.caption("By category — " + " · ".join(
                        f"{k}: {v}" for k, v in top))
            except Exception as e:
                st.caption(f"(eligible-count preview unavailable: {e})")

    # --- Resolve the config + counters we start from ---
    if not is_create_mode:
        loaded_mode = config.get('counter_mode', 'single')
        loaded_counters = config.get('counters') or [
            _default_counter(0, all_base_slots, const_slots, default_theme_map, default_off_slots)
        ]
        loaded_shared_categories = list(config.get('shared_categories') or [])
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
            _default_counter(0, all_base_slots, const_slots, default_theme_map, default_off_slots)
        ]
        loaded_shared_categories = []
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
        return _default_counter(i, all_base_slots, const_slots, default_theme_map, default_off_slots)

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
    # Shared categories (multi-counter only)
    # ============================================================
    # A common category serves the SAME dish on every counter each day: the
    # planner solves the primary counter, then pins its dish for each shared
    # base slot into the others. Only offered for multi-counter clients, and
    # only for base slots present on 2+ counters (a slot on one counter has
    # nothing to sync).
    selected_shared_categories: List[str] = []
    if is_multi:
        from collections import Counter as _Counter
        slot_counts_across = _Counter(
            s for c in result_counters for s in (c.get('categories') or [])
        )
        shareable = [s for s, n in slot_counts_across.items() if n >= 2]
        shareable_sorted = sorted(
            shareable,
            key=lambda s: DISPLAY_SLOT_ORDER.index(s)
            if s in DISPLAY_SLOT_ORDER else 999,
        )
        with st.container(border=True):
            st.markdown(
                '<p class="pulse-step-title">Shared categories</p>'
                '<p class="pulse-step-desc">Turn on to serve the same dish on '
                'every counter for the chosen categories each day (the primary '
                'counter decides; the others follow).</p>',
                unsafe_allow_html=True,
            )
            share_on = st.toggle(
                "Share common categories across counters",
                value=bool(loaded_shared_categories),
                key=f"share_toggle_{client_key}",
            )
            if share_on:
                if shareable_sorted:
                    selected_shared_categories = st.multiselect(
                        "Categories shared across counters",
                        options=shareable_sorted,
                        default=[s for s in loaded_shared_categories
                                 if s in shareable_sorted],
                        key=f"share_cats_{client_key}",
                        format_func=display_label_for_slot_id,
                        help="Only categories present on 2+ counters can be "
                             "shared.",
                    )
                else:
                    st.caption("No category is present on 2 or more counters "
                               "yet — add a common category to share it.")

    # ============================================================
    # Action bar
    # ============================================================
    st.markdown("")

    if not is_create_mode:
        dirty = (
            counter_mode != loaded_mode
            or selected_city != loaded_city
            or serve_weekends != loaded_serve_weekends
            or item_cooldown_days != loaded_cooldown
            or sorted(selected_source_pools) != sorted(loaded_source_pools)
            or sorted(selected_shared_categories) != sorted(loaded_shared_categories)
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
            f'food category. Missing: '
            # Counter names are free text typed by an admin, and this block
            # renders with unsafe_allow_html — escape before interpolating so a
            # name containing markup cannot execute. Every other raw-HTML site
            # in the app already does this (ui/formatters.py, app.py).
            f'{", ".join(html.escape(n) for n in empty_counters)}.</p>',
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
                        city=selected_city, serve_weekends=serve_weekends,
                        item_cooldown_days=item_cooldown_days,
                        source_pools=selected_source_pools,
                        is_launch_site=launch_mode,
                        shared_categories=selected_shared_categories,
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
                    'city': selected_city,
                    'serve_weekends': serve_weekends,
                    'item_cooldown_days': item_cooldown_days,
                    'source_pools': selected_source_pools,
                    'shared_categories': selected_shared_categories,
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
                    _default_counter(0, all_base_slots, const_slots, default_theme_map, default_off_slots)
                ],
                'shared_categories': [],
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
