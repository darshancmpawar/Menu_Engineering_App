"""
Streamlit frontend for Ikigai Masala Menu Planning.

Single entry point - auto-starts the Flask API backend in a background thread.

Run with:
    cd ikigai_masala-main
    streamlit run app.py
"""

import os
import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

import datetime as dt
import html
import io
import csv
import logging
import threading
import time

import requests
import streamlit as st

from ui.api_client import MenuApiClient
from ui.formatters import (
    display_label_for_slot_id,
    flatten_api_solution,
    format_item_for_ui,
    format_item_html,
    slot_sort_key,
    THEME_TAG_COLORS,
    THEME_ICONS,
)
from ui.styles import STYLES
from ui.backend_probe import health_check, pick_backend_port
from customisation.main import render_customisation_editor
from user_authentication.session import (
    init_auth_state,
    is_authenticated,
    current_user,
    current_token,
    logout_user,
    require_role,
)
from user_authentication.login_ui import render_login_form
from user_authentication.user_manager_ui import render_user_manager
from user_authentication.models import ROLE_SUPER_ADMIN, ROLE_ADMIN


# ---------------------------------------------------------------------------
# Auto-start Flask API backend
# ---------------------------------------------------------------------------
_BACKEND_URL = None  # set by _ensure_backend_running()


def _start_flask_backend(port: int) -> None:
    # api.app's module-level validate_required_env() raises if any
    # required var is missing; let that bubble up so the Streamlit
    # process shows a clear error instead of a silent backend crash.
    from api.app import app as flask_app
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    flask_app.run(host="127.0.0.1", port=port, debug=False,
                  use_reloader=False, threaded=True)


def _ensure_backend_running() -> str:
    """Start the backend if needed and return its base URL.

    Raises ``RuntimeError`` if no port is available or the backend does
    not become healthy within the startup window — the caller should
    surface the error to the user rather than hit an unrelated service
    that happens to sit on port 5000.
    """
    global _BACKEND_URL
    port = pick_backend_port()
    url = f"http://localhost:{port}"
    if health_check(port):
        _BACKEND_URL = url
        return url
    if "flask_started" not in st.session_state:
        t = threading.Thread(
            target=_start_flask_backend, args=(port,), daemon=True,
        )
        t.start()
        st.session_state.flask_started = True
    for _ in range(20):
        if health_check(port):
            _BACKEND_URL = url
            return url
        time.sleep(0.5)
    raise RuntimeError(
        f"Backend did not become healthy on port {port} within 10s. "
        "Check the Streamlit server logs for errors."
    )


# ---------------------------------------------------------------------------
# Page config — MUST be first Streamlit command
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Ikigai Masala - Menu Planner",
    page_icon="https://em-content.zobj.net/source/apple/391/curry-rice_1f35b.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(STYLES, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Backend must be up before the login form (login hits the API).
# ---------------------------------------------------------------------------
# Validate required env vars first so a misconfigured deployment shows a
# clear Streamlit-native error instead of "backend did not become healthy"
# after the spawned thread silently crashes.
try:
    from api.config import validate_required_env
    validate_required_env()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

try:
    _ensure_backend_running()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

# ---------------------------------------------------------------------------
# Authentication gate — before anything else
# ---------------------------------------------------------------------------
init_auth_state()

if not is_authenticated():
    render_login_form(_BACKEND_URL)
    st.stop()

client = MenuApiClient(_BACKEND_URL, token=current_token())

# ---------------------------------------------------------------------------
# Session state initialization (only after auth)
# ---------------------------------------------------------------------------
_SESSION_DEFAULTS = {
    "plan": None,
    "plan_dates": [],
    "day_types": {},
    "pool_warnings": [],
    "client_name": None,
    "changes_log": [],
    "view": "planner",
}
for key, default in _SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Safety: if somehow view is set but user lacks permission, reset
if st.session_state.view in ("editor", "user_manager"):
    if not require_role(ROLE_SUPER_ADMIN, ROLE_ADMIN):
        st.session_state.view = "planner"

# ---------------------------------------------------------------------------
# Editor view (role-gated, full-page)
# ---------------------------------------------------------------------------
if st.session_state.view == "editor":
    render_customisation_editor(client)
    st.stop()

# ---------------------------------------------------------------------------
# User manager view (role-gated, full-page)
# ---------------------------------------------------------------------------
if st.session_state.view == "user_manager":
    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("< Back to Menu", key="um_back_btn", use_container_width=True):
            st.session_state.view = "planner"
            st.rerun()
    with col_title:
        st.markdown('<p class="page-title">User Management</p>', unsafe_allow_html=True)
    st.markdown("")
    render_user_manager()
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar (planner view)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""<div class="sidebar-brand">
        <div class="sidebar-brand-row">
            <div class="sidebar-brand-icon">&#127835;</div>
            <div>
                <h2>Ikigai Masala</h2>
                <p>Weekly Menu Planner</p>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # User chip
    _user = current_user()
    if _user:
        initials = ''.join(w[0] for w in _user.profile_name.split()[:2]).upper() if _user.profile_name else '?'
        st.markdown(
            f'<div class="user-chip">'
            f'<div class="user-avatar">{html.escape(initials)}</div>'
            f'<div class="user-chip-info">'
            f'<div class="user-chip-name">{html.escape(_user.profile_name or "")}</div>'
            f'<div class="user-chip-role">{html.escape(_user.role or "")}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Logout", key="sidebar_logout", use_container_width=True):
            logout_user()
            st.rerun()
        st.divider()

    try:
        clients_list = client.list_clients()
    except (ConnectionError, OSError, ValueError):
        clients_list = []
        st.error("Cannot reach API.")

    selected_client = st.selectbox("Client",
        clients_list if clients_list else ["(no clients)"])
    start_date = st.date_input("Start date", value=dt.date.today())
    num_days = st.slider("Weekdays", min_value=1, max_value=20, value=5,
                         help="Number of weekdays (Sat/Sun are skipped)")

    st.divider()
    generate_clicked = st.button("Generate Menu Plan", type="primary",
                                 use_container_width=True)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
_hdr_col1, _hdr_col2 = st.columns([5, 2])
with _hdr_col1:
    st.markdown('<p class="page-title">Menu Plan</p>', unsafe_allow_html=True)
    if st.session_state.client_name:
        st.markdown(
            f'<p class="page-subtitle">Generated plan for {html.escape(st.session_state.client_name)}</p>',
            unsafe_allow_html=True)
    else:
        st.markdown(
            '<p class="page-subtitle">Select a client and generate a plan to get started</p>',
            unsafe_allow_html=True)
with _hdr_col2:
    btn_cols = st.columns(2)
    with btn_cols[0]:
        if require_role(ROLE_SUPER_ADMIN, ROLE_ADMIN):
            if st.button("Edit Logic", key="open_editor_btn", use_container_width=True):
                st.session_state.view = "editor"
                st.rerun()
    with btn_cols[1]:
        if require_role(ROLE_SUPER_ADMIN, ROLE_ADMIN):
            if st.button("Users", key="open_users_btn", use_container_width=True):
                st.session_state.view = "user_manager"
                st.rerun()

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------
if generate_clicked:
    if selected_client and selected_client != "(no clients)":
        with st.spinner(f"Generating plan for {selected_client}..."):
            try:
                result = client.plan(
                    client_name=selected_client,
                    start_date=start_date.isoformat(),
                    num_days=num_days,
                    time_limit_seconds=180,
                )
                flat_plan, day_types = flatten_api_solution(result.get("solution", {}))
                st.session_state.plan = flat_plan
                st.session_state.plan_dates = sorted(flat_plan.keys())
                st.session_state.day_types = day_types
                st.session_state.client_name = selected_client
                st.session_state.changes_log = []
                st.session_state.pool_warnings = result.get("pool_warnings", [])
                st.rerun()
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Generation failed: {e}")
    else:
        st.warning("Select a valid client first.")

# ---------------------------------------------------------------------------
# Display plan
# ---------------------------------------------------------------------------
plan = st.session_state.plan
plan_dates = st.session_state.plan_dates

if plan and plan_dates:
    if st.session_state.get('save_success_msg'):
        st.success(st.session_state.pop('save_success_msg'))

    all_slots = set()
    for date_str in plan_dates:
        all_slots.update(plan.get(date_str, {}).keys())
    sorted_slots = sorted(all_slots, key=slot_sort_key)

    total_items = sum(1 for d in plan_dates for s in sorted_slots
                      if plan.get(d, {}).get(s, ""))

    st.markdown(f"""<div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Client</div>
            <div class="metric-value">{html.escape(st.session_state.client_name or "")}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Days</div>
            <div class="metric-value">{len(plan_dates)}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Slots per day</div>
            <div class="metric-value">{len(sorted_slots)}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Total items</div>
            <div class="metric-value">{total_items}</div>
        </div>
    </div>""", unsafe_allow_html=True)

    if st.session_state.pool_warnings:
        with st.expander(f"Pool warnings ({len(st.session_state.pool_warnings)})", expanded=False):
            for w in st.session_state.pool_warnings:
                st.markdown(f'<div class="pool-warn-bar">&#9888; {html.escape(str(w))}</div>', unsafe_allow_html=True)

    # Menu table
    _day_types = st.session_state.day_types
    header_html = '<tr><th>Slot</th>'
    for d_str in plan_dates:
        d = dt.date.fromisoformat(d_str)
        day_type = _day_types.get(d_str, "")
        bg, fg = THEME_TAG_COLORS.get(day_type, ("#27272a", "#71717a"))
        icon = THEME_ICONS.get(day_type, "")
        label = day_type.replace("_", " ").title() if day_type else ""
        header_html += (
            f'<th><span class="day-label">{d.strftime("%a %d %b")}</span>'
            f'<span class="theme-tag" style="background:{bg};color:{fg};">'
            f'{icon} {label}</span></th>')
    header_html += '</tr>'

    body_html = ''
    for slot_id in sorted_slots:
        body_html += f'<tr><td>{display_label_for_slot_id(slot_id)}</td>'
        for d_str in plan_dates:
            raw_item = plan.get(d_str, {}).get(slot_id, "")
            body_html += f'<td>{format_item_html(raw_item)}</td>'
        body_html += '</tr>'

    st.markdown(
        f'<div class="menu-table-wrap"><table class="menu-table">'
        f'<thead>{header_html}</thead>'
        f'<tbody>{body_html}</tbody></table></div>',
        unsafe_allow_html=True)

    st.markdown("")

    # Action buttons
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    with c1:
        if st.button("Save to History", use_container_width=True):
            try:
                client.save(client_name=st.session_state.client_name,
                            week_plan=plan, week_start=plan_dates[0])
                st.session_state['save_success_msg'] = "Plan saved to history!"
                st.rerun()
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Save failed: {e}")
    with c2:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Slot"] + plan_dates)
        for slot_id in sorted_slots:
            row = [display_label_for_slot_id(slot_id)]
            for d_str in plan_dates:
                row.append(format_item_for_ui(plan.get(d_str, {}).get(slot_id, "")))
            writer.writerow(row)
        st.download_button("Download CSV", data=buf.getvalue(),
            file_name=f"menu_{st.session_state.client_name}.csv",
            mime="text/csv", use_container_width=True)
    with c3:
        if st.button("Clear", use_container_width=True):
            st.session_state.plan = None
            st.session_state.plan_dates = []
            st.session_state.changes_log = []
            st.rerun()

    # Regeneration
    with st.expander("Regenerate cells"):
        st.caption("Pick slots to replace with fresh items.")
        regen_selections = {}
        cols = st.columns(min(len(plan_dates), 5))
        for i, d_str in enumerate(plan_dates):
            d = dt.date.fromisoformat(d_str)
            day_type = _day_types.get(d_str, "")
            bg, fg = THEME_TAG_COLORS.get(day_type, ("#27272a", "#71717a"))
            icon = THEME_ICONS.get(day_type, "")
            label = day_type.replace("_", " ").title() if day_type else ""
            col = cols[i % len(cols)]
            with col:
                st.markdown(
                    f'<div class="regen-day-header">{d.strftime("%a %d %b")} '
                    f'<span class="theme-tag" style="background:{bg};color:{fg};'
                    f'font-size:0.6rem;">{icon} {label}</span></div>',
                    unsafe_allow_html=True)
                day_slots = sorted(plan.get(d_str, {}).keys(), key=slot_sort_key)
                selected = st.multiselect(f"Slots for {d_str}", day_slots,
                    format_func=display_label_for_slot_id,
                    key=f"regen_{d_str}", label_visibility="collapsed")
                if selected:
                    regen_selections[d_str] = selected

        if st.button("Regenerate Selected", type="primary"):
            if regen_selections:
                with st.spinner("Regenerating..."):
                    try:
                        result = client.regenerate(
                            client_name=st.session_state.client_name,
                            base_plan=plan, replace_slots=regen_selections,
                            start_date=plan_dates[0],
                            num_days=len(plan_dates),
                            time_limit_seconds=180)
                        flat_regen, regen_day_types = flatten_api_solution(result.get("solution", {}))
                        st.session_state.plan = flat_regen if flat_regen else plan
                        if regen_day_types:
                            st.session_state.day_types = regen_day_types
                        st.session_state.plan_dates = sorted(st.session_state.plan.keys())
                        n = sum(len(v) for v in regen_selections.values())
                        st.session_state.changes_log.append(f"Regenerated {n} cell{'s' if n != 1 else ''}")
                        st.rerun()
                    except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                        st.error(f"Regeneration failed: {e}")
            else:
                st.warning("Select at least one cell.")

    if st.session_state.changes_log:
        with st.expander("Changes log"):
            for entry in st.session_state.changes_log:
                # Escape defensively: today's entries are code-constructed
                # ("Regenerated N cells"), but the moment someone appends
                # a slot/client name or rule string that came from user
                # input, this div becomes an XSS sink because it renders
                # with unsafe_allow_html=True.
                st.markdown(
                    f'<div class="log-entry">{html.escape(str(entry))}</div>',
                    unsafe_allow_html=True,
                )

else:
    st.markdown("""<div class="empty-state">
        <div class="empty-icon">&#127835;</div>
        <h3>No menu plan yet</h3>
        <p>Select a client and click <b>Generate Menu Plan</b><br>in the sidebar to get started.</p>
    </div>""", unsafe_allow_html=True)
