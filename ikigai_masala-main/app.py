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
    format_item_for_ui,
    format_item_html,
    slot_sort_key,
    THEME_TAG_COLORS,
    THEME_ICONS,
)
from customisation.main import render_customisation_editor
from user_authentication.session import (
    init_auth_state,
    is_authenticated,
    current_user,
    logout_user,
    require_role,
)
from user_authentication.login_ui import render_login_form
from user_authentication.user_manager_ui import render_user_manager
from user_authentication.models import ROLE_SUPER_ADMIN, ROLE_ADMIN


def _flatten_solution(raw_solution: dict) -> tuple:
    """Convert the nested API solution format.

    Returns:
        (flat_plan, day_types) where flat_plan = {date: {slot: item}}
        and day_types = {date: day_type_string}.
    """
    flat = {}
    day_types = {}
    for date_key, day_data in raw_solution.items():
        if isinstance(day_data, dict):
            items = day_data.get("items", {})
            day_types[date_key] = day_data.get("day_type", "")
        else:
            items = {}
        flat[date_key] = {
            slot_id: slot_val.get("item", "") if isinstance(slot_val, dict) else str(slot_val)
            for slot_id, slot_val in items.items()
        }
    return flat, day_types


# ---------------------------------------------------------------------------
# Auto-start Flask API backend
# ---------------------------------------------------------------------------
_BACKEND_PORT = 5000
_BACKEND_URL = f"http://localhost:{_BACKEND_PORT}"


def _start_flask_backend():
    from api.app import app as flask_app
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    flask_app.run(host="127.0.0.1", port=_BACKEND_PORT, debug=False, use_reloader=False)


def _ensure_backend_running():
    try:
        requests.get(f"{_BACKEND_URL}/api/v1/health", timeout=1)
        return True
    except (requests.ConnectionError, requests.Timeout):
        pass
    if "flask_started" not in st.session_state:
        t = threading.Thread(target=_start_flask_backend, daemon=True)
        t.start()
        st.session_state.flask_started = True
    for _ in range(20):
        try:
            requests.get(f"{_BACKEND_URL}/api/v1/health", timeout=1)
            return True
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Ikigai Masala - Menu Planner",
    page_icon="https://em-content.zobj.net/source/apple/391/curry-rice_1f35b.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Premium Dark Theme CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* ================================================================
       DESIGN SYSTEM TOKENS
       ================================================================ */
    :root {
        --bg-primary:    #09090b;
        --bg-secondary:  #111113;
        --bg-tertiary:   #18181b;
        --bg-elevated:   #1c1c1f;
        --bg-hover:      #222225;
        --border-subtle: #27272a;
        --border-default:#3f3f46;
        --text-primary:  #fafafa;
        --text-secondary:#a1a1aa;
        --text-tertiary: #71717a;
        --text-muted:    #52525b;
        --accent:        #a78bfa;
        --accent-dim:    #7c3aed;
        --success:       #34d399;
        --warning:       #fbbf24;
        --danger:        #f87171;
        --radius-sm:     6px;
        --radius-md:     10px;
        --radius-lg:     14px;
        --radius-xl:     20px;
        --shadow-sm:     0 1px 2px rgba(0,0,0,0.3);
        --shadow-md:     0 4px 12px rgba(0,0,0,0.4);
        --shadow-lg:     0 8px 30px rgba(0,0,0,0.5);
        --transition:    all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* ================================================================
       GLOBAL
       ================================================================ */
    .stApp {
        background: var(--bg-primary);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    .block-container {
        padding: 1.5rem 2rem 2rem;
        max-width: 1400px;
    }
    header[data-testid="stHeader"] {
        background: transparent;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-bottom: 1px solid var(--border-subtle);
    }

    /* Hide Streamlit branding */
    #MainMenu, footer, .stDeployButton { display: none !important; }

    /* ================================================================
       SIDEBAR
       ================================================================ */
    [data-testid="stSidebar"] {
        background: var(--bg-secondary);
        border-right: 1px solid var(--border-subtle);
    }
    [data-testid="stSidebar"] label {
        color: var(--text-secondary) !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.02em;
    }
    [data-testid="stSidebar"] .stSelectbox > div > div,
    [data-testid="stSidebar"] .stDateInput > div > div > input {
        background: var(--bg-tertiary) !important;
        border-color: var(--border-subtle) !important;
        color: var(--text-primary) !important;
        border-radius: var(--radius-sm) !important;
    }

    /* Brand block in sidebar */
    .sidebar-brand {
        padding: 0.5rem 0 1.5rem;
        border-bottom: 1px solid var(--border-subtle);
        margin-bottom: 1.5rem;
    }
    .sidebar-brand-row {
        display: flex; align-items: center; gap: 0.65rem;
    }
    .sidebar-brand-icon {
        width: 36px; height: 36px; border-radius: var(--radius-md);
        background: linear-gradient(135deg, var(--accent-dim), #a78bfa);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.1rem; flex-shrink: 0;
        box-shadow: 0 0 20px rgba(124,58,237,0.25);
    }
    .sidebar-brand h2 {
        margin: 0; font-size: 1.15rem; color: var(--text-primary);
        font-weight: 700; letter-spacing: -0.4px; line-height: 1.2;
    }
    .sidebar-brand p {
        margin: 0; font-size: 0.7rem; color: var(--text-tertiary);
        font-weight: 400; letter-spacing: 0.02em;
    }

    /* Sidebar user chip */
    .user-chip {
        display: flex; align-items: center; gap: 0.55rem;
        padding: 0.55rem 0.7rem; background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
        margin-bottom: 0.75rem;
    }
    .user-avatar {
        width: 30px; height: 30px; border-radius: 50%;
        background: linear-gradient(135deg, #6366f1, #a78bfa);
        display: flex; align-items: center; justify-content: center;
        font-size: 0.72rem; font-weight: 700; color: #fff; flex-shrink: 0;
    }
    .user-chip-info { flex: 1; min-width: 0; }
    .user-chip-name {
        font-size: 0.8rem; font-weight: 600; color: var(--text-primary);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .user-chip-role {
        font-size: 0.65rem; color: var(--text-tertiary);
        text-transform: uppercase; letter-spacing: 0.04em; font-weight: 500;
    }

    /* ================================================================
       PAGE HEADER
       ================================================================ */
    .page-header {
        display: flex; align-items: flex-start; justify-content: space-between;
        margin-bottom: 1.75rem; gap: 1rem;
    }
    .page-title {
        font-size: 1.65rem; font-weight: 800; color: var(--text-primary);
        margin: 0; letter-spacing: -0.5px; line-height: 1.2;
    }
    .page-subtitle {
        font-size: 0.82rem; color: var(--text-tertiary); margin: 0.2rem 0 0;
        font-weight: 400;
    }
    .page-actions {
        display: flex; gap: 0.5rem; flex-shrink: 0; align-items: center;
    }
    .action-btn {
        display: inline-flex; align-items: center; gap: 0.35rem;
        padding: 0.45rem 0.85rem; border-radius: var(--radius-sm);
        font-size: 0.78rem; font-weight: 500; cursor: pointer;
        border: 1px solid var(--border-subtle); background: var(--bg-tertiary);
        color: var(--text-secondary); text-decoration: none;
        transition: var(--transition);
    }
    .action-btn:hover {
        background: var(--bg-hover); color: var(--text-primary);
        border-color: var(--border-default);
    }

    /* ================================================================
       METRIC CARDS
       ================================================================ */
    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0.75rem;
        margin-bottom: 1.75rem;
    }
    .metric-card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        padding: 1rem 1.15rem;
        position: relative;
        overflow: hidden;
        transition: var(--transition);
    }
    .metric-card:hover {
        border-color: var(--border-default);
        transform: translateY(-1px);
        box-shadow: var(--shadow-md);
    }
    .metric-card::before {
        content: '';
        position: absolute; top: 0; left: 0; right: 0; height: 2px;
    }
    .metric-card:nth-child(1)::before { background: linear-gradient(90deg, #a78bfa, #6366f1); }
    .metric-card:nth-child(2)::before { background: linear-gradient(90deg, #34d399, #059669); }
    .metric-card:nth-child(3)::before { background: linear-gradient(90deg, #fbbf24, #d97706); }
    .metric-card:nth-child(4)::before { background: linear-gradient(90deg, #60a5fa, #3b82f6); }
    .metric-label {
        font-size: 0.65rem; color: var(--text-tertiary);
        text-transform: uppercase; letter-spacing: 0.06em;
        font-weight: 600; margin-bottom: 0.3rem;
    }
    .metric-value {
        font-size: 1.5rem; font-weight: 800; color: var(--text-primary);
        letter-spacing: -0.5px; line-height: 1;
    }

    /* ================================================================
       MENU TABLE
       ================================================================ */
    .menu-table-wrap {
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        overflow: hidden;
        box-shadow: var(--shadow-sm);
        background: var(--bg-secondary);
    }
    .menu-table {
        width: 100%; border-collapse: collapse; font-size: 0.82rem;
    }
    .menu-table thead th {
        background: var(--bg-tertiary);
        color: var(--text-secondary);
        padding: 0.75rem 0.85rem;
        text-align: center;
        font-weight: 600;
        font-size: 0.76rem;
        border-bottom: 1px solid var(--border-subtle);
        border-right: 1px solid var(--border-subtle);
        letter-spacing: 0.01em;
    }
    .menu-table thead th:first-child {
        text-align: left;
        min-width: 120px;
        background: var(--bg-elevated);
    }
    .menu-table thead th:last-child { border-right: none; }

    /* Day column headers */
    .day-label {
        display: block; color: var(--text-primary); font-weight: 700;
        font-size: 0.82rem; margin-bottom: 4px;
    }
    .theme-tag {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 2px 8px; border-radius: 99px;
        font-size: 0.6rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em;
        line-height: 1.6;
    }

    /* Table body */
    .menu-table tbody td {
        padding: 0.55rem 0.85rem;
        border-bottom: 1px solid rgba(39,39,42,0.6);
        border-right: 1px solid rgba(39,39,42,0.6);
        color: var(--text-secondary);
        background: var(--bg-secondary);
        vertical-align: middle;
        transition: background 0.15s ease;
    }
    .menu-table tbody td:first-child {
        font-weight: 600; color: var(--text-tertiary);
        background: var(--bg-tertiary);
        font-size: 0.76rem; letter-spacing: 0.01em;
        white-space: nowrap; min-width: 120px;
        border-right: 1px solid var(--border-subtle);
    }
    .menu-table tbody td:last-child { border-right: none; }
    .menu-table tbody tr:last-child td { border-bottom: none; }
    .menu-table tbody tr:hover td { background: var(--bg-hover); }
    .menu-table tbody tr:hover td:first-child { background: var(--bg-elevated); }

    /* Item cells */
    .item-name {
        color: var(--text-primary); font-weight: 500;
        font-size: 0.8rem; line-height: 1.4;
    }
    .color-pill {
        display: inline-block; margin-left: 5px;
        padding: 1px 6px; border-radius: 99px;
        font-size: 0.6rem; font-weight: 600;
        letter-spacing: 0.02em; vertical-align: middle;
    }
    .cell-empty {
        color: var(--text-muted); font-size: 0.8rem;
    }

    /* ================================================================
       POOL WARNINGS
       ================================================================ */
    .pool-warn-bar {
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.6rem 1rem; margin-bottom: 1rem;
        background: rgba(251,191,36,0.06);
        border: 1px solid rgba(251,191,36,0.15);
        border-radius: var(--radius-md);
        font-size: 0.78rem; color: #fbbf24;
    }

    /* ================================================================
       EMPTY STATE
       ================================================================ */
    .empty-state {
        text-align: center; padding: 5rem 2rem;
        border: 2px dashed var(--border-subtle);
        border-radius: var(--radius-xl);
        margin: 3rem auto; max-width: 500px;
    }
    .empty-icon {
        width: 64px; height: 64px; margin: 0 auto 1rem;
        border-radius: 50%;
        background: linear-gradient(135deg, var(--accent-dim), #a78bfa);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.6rem;
        box-shadow: 0 0 40px rgba(124,58,237,0.2);
    }
    .empty-state h3 {
        color: var(--text-primary); margin: 0 0 0.4rem;
        font-size: 1.15rem; font-weight: 700;
    }
    .empty-state p {
        color: var(--text-tertiary); font-size: 0.85rem; margin: 0;
        line-height: 1.5;
    }

    /* ================================================================
       CHANGES LOG
       ================================================================ */
    .log-entry {
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.4rem 0.75rem; background: var(--bg-tertiary);
        border-left: 3px solid var(--accent);
        border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
        margin-bottom: 0.35rem; font-size: 0.78rem; color: var(--text-secondary);
    }

    /* ================================================================
       REGEN SECTION
       ================================================================ */
    .regen-day-header {
        font-weight: 700; font-size: 0.82rem; color: var(--text-primary);
        margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.4rem;
    }

    /* ================================================================
       ACTION BAR
       ================================================================ */
    .action-bar {
        display: flex; gap: 0.65rem; align-items: center;
        padding: 1rem 0; margin-top: 0.5rem;
    }

    /* ================================================================
       STREAMLIT COMPONENT OVERRIDES
       ================================================================ */
    /* Buttons */
    .stButton > button {
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        font-size: 0.8rem !important;
        letter-spacing: 0.01em !important;
        transition: var(--transition) !important;
        border: 1px solid var(--border-subtle) !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--accent-dim), #8b5cf6) !important;
        border: none !important;
        color: #fff !important;
        box-shadow: 0 2px 8px rgba(124,58,237,0.3) !important;
    }
    .stButton > button[kind="primary"]:hover {
        box-shadow: 0 4px 16px rgba(124,58,237,0.45) !important;
        transform: translateY(-1px);
    }
    .stButton > button:not([kind="primary"]) {
        background: var(--bg-tertiary) !important;
        color: var(--text-secondary) !important;
    }
    .stButton > button:not([kind="primary"]):hover {
        background: var(--bg-hover) !important;
        color: var(--text-primary) !important;
        border-color: var(--border-default) !important;
    }

    /* Slider */
    [data-testid="stSidebar"] .stSlider > div > div > div {
        color: var(--text-primary) !important;
    }

    /* Expanders */
    .stExpander {
        border-color: var(--border-subtle) !important;
    }
    div[data-testid="stExpander"] details {
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-md) !important;
    }
    div[data-testid="stExpander"] summary span {
        color: var(--text-secondary) !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
    }
    div[data-testid="stExpander"] summary:hover span {
        color: var(--text-primary) !important;
    }

    /* Divider */
    hr { border-color: var(--border-subtle) !important; opacity: 0.5; }

    /* Toasts / alerts */
    .stAlert { border-radius: var(--radius-md) !important; }
    [data-testid="stMarkdownContainer"] p { color: var(--text-secondary); }

    /* Multiselect */
    .stMultiSelect > div > div {
        background: var(--bg-tertiary) !important;
        border-color: var(--border-subtle) !important;
        border-radius: var(--radius-sm) !important;
    }

    /* Download button */
    .stDownloadButton > button {
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        font-size: 0.8rem !important;
        background: var(--bg-tertiary) !important;
        border: 1px solid var(--border-subtle) !important;
        color: var(--text-secondary) !important;
    }
    .stDownloadButton > button:hover {
        background: var(--bg-hover) !important;
        color: var(--text-primary) !important;
        border-color: var(--border-default) !important;
    }

    /* Spinner */
    .stSpinner > div { color: var(--accent) !important; }

    /* ================================================================
       RESPONSIVE
       ================================================================ */
    @media (max-width: 768px) {
        .metrics-grid { grid-template-columns: repeat(2, 1fr); }
        .block-container { padding: 1rem; }
        .menu-table { font-size: 0.75rem; }
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Authentication gate
# ---------------------------------------------------------------------------
init_auth_state()

if not is_authenticated():
    render_login_form()
    st.stop()

# ---------------------------------------------------------------------------
# Backend + client
# ---------------------------------------------------------------------------
backend_ok = _ensure_backend_running()
client = MenuApiClient(_BACKEND_URL)

# ---------------------------------------------------------------------------
# Session state
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

# ---------------------------------------------------------------------------
# Editor view (role-gated)
# ---------------------------------------------------------------------------
if st.session_state.view == "editor":
    if require_role(ROLE_SUPER_ADMIN, ROLE_ADMIN):
        render_customisation_editor(client)
    else:
        st.error("You don't have permission to configure clients.")
        if st.button("Back to Menu"):
            st.session_state.view = "planner"
            st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# User manager view (role-gated)
# ---------------------------------------------------------------------------
if st.session_state.view == "user_manager":
    if require_role(ROLE_SUPER_ADMIN, ROLE_ADMIN):
        col_back, col_title = st.columns([1, 5])
        with col_back:
            if st.button("< Back to Menu", key="um_back_btn", use_container_width=True):
                st.session_state.view = "planner"
                st.rerun()
        with col_title:
            st.markdown(
                '<p class="page-title">User Management</p>',
                unsafe_allow_html=True,
            )
        st.markdown("")
        render_user_manager()
    else:
        st.error("You don't have permission to manage users.")
        if st.button("Back to Menu"):
            st.session_state.view = "planner"
            st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
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
            f'<div class="user-avatar">{initials}</div>'
            f'<div class="user-chip-info">'
            f'<div class="user-chip-name">{_user.profile_name}</div>'
            f'<div class="user-chip-role">{_user.role}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Logout", key="sidebar_logout", use_container_width=True):
            logout_user()
            st.rerun()
        st.divider()

    if not backend_ok:
        st.error("Backend API failed to start.")
        clients_list = []
    else:
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
# Page header with action buttons
# ---------------------------------------------------------------------------
_hdr_col1, _hdr_col2 = st.columns([5, 2])
with _hdr_col1:
    st.markdown('<p class="page-title">Menu Plan</p>', unsafe_allow_html=True)
    if st.session_state.client_name:
        st.markdown(
            f'<p class="page-subtitle">Generated plan for {st.session_state.client_name}</p>',
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
                flat_plan, day_types = _flatten_solution(result.get("solution", {}))
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
    # --- Show save success ---
    if st.session_state.get('save_success_msg'):
        st.success(st.session_state.pop('save_success_msg'))

    # --- Collect slots ---
    all_slots = set()
    for date_str in plan_dates:
        all_slots.update(plan.get(date_str, {}).keys())
    sorted_slots = sorted(all_slots, key=slot_sort_key)

    # --- Metrics ---
    total_items = sum(1 for d in plan_dates for s in sorted_slots
                      if plan.get(d, {}).get(s, ""))
    unique_themes = set(st.session_state.day_types.get(d, '') for d in plan_dates)
    unique_themes.discard('')

    st.markdown(f"""<div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Client</div>
            <div class="metric-value">{st.session_state.client_name}</div>
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

    # --- Pool warnings ---
    if st.session_state.pool_warnings:
        with st.expander(f"Pool warnings ({len(st.session_state.pool_warnings)})", expanded=False):
            for w in st.session_state.pool_warnings:
                st.markdown(
                    f'<div class="pool-warn-bar">&#9888; {w}</div>',
                    unsafe_allow_html=True)

    # --- Table ---
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

    # --- Actions ---
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

    # --- Regeneration ---
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
                        flat_regen, regen_day_types = _flatten_solution(result.get("solution", {}))
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

    # --- Changes log ---
    if st.session_state.changes_log:
        with st.expander("Changes log"):
            for entry in st.session_state.changes_log:
                st.markdown(f'<div class="log-entry">{entry}</div>', unsafe_allow_html=True)

else:
    st.markdown("""<div class="empty-state">
        <div class="empty-icon">&#127835;</div>
        <h3>No menu plan yet</h3>
        <p>Select a client and click <b>Generate Menu Plan</b><br>in the sidebar to get started.</p>
    </div>""", unsafe_allow_html=True)
