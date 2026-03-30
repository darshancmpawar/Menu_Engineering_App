"""
Streamlit frontend for Ikigai Masala Menu Planning.

Single entry point — auto-starts the Flask API backend in a background thread.

Run with:
    cd Rebuild_ikigai_masala_new-main/ikigai_masala-main
    streamlit run app.py
"""

import os
import sys

# Ensure the app directory is on sys.path (needed when Streamlit Cloud
# launches from the repo root instead of this subdirectory).
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
    theme_label,
    display_label_for_slot_id,
    format_item_for_ui,
    format_item_html,
    slot_sort_key,
    WEEKDAY_THEME_BADGES,
)
from customisation.main import render_customisation_editor


def _flatten_solution(raw_solution: dict) -> dict:
    """Convert the nested API solution format into a flat {date: {slot: item}} dict."""
    flat = {}
    for date_key, day_data in raw_solution.items():
        items = day_data.get("items", {}) if isinstance(day_data, dict) else {}
        flat[date_key] = {
            slot_id: slot_val.get("item", "") if isinstance(slot_val, dict) else str(slot_val)
            for slot_id, slot_val in items.items()
        }
    return flat


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
    page_icon="🍛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Dark Theme CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* --- Global dark --- */
    .stApp { background-color: #0f0f0f; }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; max-width: 1200px; }
    header[data-testid="stHeader"] { background: #0f0f0f; }

    /* --- Sidebar --- */
    [data-testid="stSidebar"] { background: #171717; border-right: 1px solid #262626; }
    [data-testid="stSidebar"] label { color: #a3a3a3 !important; }

    .sidebar-brand {
        padding: 0.75rem 0 1.25rem; border-bottom: 1px solid #262626;
        margin-bottom: 1.25rem;
    }
    .sidebar-brand h2 {
        margin: 0; font-size: 1.2rem; color: #f5f5f5; font-weight: 700;
        letter-spacing: -0.3px;
    }
    .sidebar-brand p { margin: 0.2rem 0 0; font-size: 0.75rem; color: #737373; }

    /* --- Page header --- */
    .page-title {
        font-size: 1.5rem; font-weight: 700; color: #f5f5f5;
        margin: 0 0 0.15rem; letter-spacing: -0.3px;
    }
    .page-subtitle { font-size: 0.85rem; color: #737373; margin: 0 0 1.25rem; }

    /* --- Metric cards --- */
    .metric-row { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }
    .metric-card {
        flex: 1; background: #171717; border: 1px solid #262626;
        border-radius: 10px; padding: 0.7rem 1rem;
    }
    .metric-card .label {
        font-size: 0.65rem; color: #737373; text-transform: uppercase;
        letter-spacing: 0.5px; font-weight: 600;
    }
    .metric-card .value {
        font-size: 1.2rem; font-weight: 700; color: #f5f5f5; margin-top: 0.15rem;
    }

    /* --- Menu table --- */
    .menu-table {
        width: 100%; border-collapse: collapse; font-size: 0.82rem;
        border: 1px solid #262626; border-radius: 10px; overflow: hidden;
    }
    .menu-table thead th {
        background: #1a1a1a; color: #d4d4d4; padding: 0.6rem 0.75rem;
        text-align: center; font-weight: 600; font-size: 0.78rem;
        border-right: 1px solid #262626; border-bottom: 1px solid #262626;
    }
    .menu-table thead th:first-child { text-align: left; }
    .menu-table thead th:last-child { border-right: none; }
    .menu-table thead .day-label { display: block; color: #e5e5e5; }
    .menu-table thead .theme-tag {
        display: inline-block; margin-top: 4px; padding: 2px 8px;
        border-radius: 4px; font-size: 0.6rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.4px;
    }
    .menu-table tbody td {
        padding: 0.5rem 0.75rem; border-bottom: 1px solid #1f1f1f;
        border-right: 1px solid #1f1f1f; color: #d4d4d4;
        background: #0f0f0f;
    }
    .menu-table tbody td:first-child {
        font-weight: 600; color: #a3a3a3; background: #141414;
        white-space: nowrap; min-width: 110px; font-size: 0.78rem;
    }
    .menu-table tbody td:last-child { border-right: none; }
    .menu-table tbody tr:last-child td { border-bottom: none; }
    .menu-table tbody tr:hover td { background: #171717; }
    .menu-table tbody tr:hover td:first-child { background: #1a1a1a; }

    /* --- Empty state --- */
    .empty-state {
        text-align: center; padding: 4rem 2rem; border: 2px dashed #262626;
        border-radius: 12px; margin: 2rem 0;
    }
    .empty-state .icon { font-size: 2.5rem; margin-bottom: 0.5rem; }
    .empty-state h3 { color: #d4d4d4; margin: 0 0 0.3rem; font-size: 1.1rem; }
    .empty-state p { color: #737373; font-size: 0.85rem; margin: 0; }

    /* --- Log entry --- */
    .log-entry {
        padding: 0.35rem 0.7rem; background: #171717;
        border-left: 3px solid #525252; border-radius: 0 4px 4px 0;
        margin-bottom: 0.35rem; font-size: 0.8rem; color: #a3a3a3;
    }

    /* --- Regen header --- */
    .regen-day-header {
        font-weight: 600; font-size: 0.82rem; color: #e5e5e5;
        margin-bottom: 0.25rem;
    }

    /* --- Streamlit overrides for dark --- */
    .stMarkdown, .stMarkdown p, .stCaption { color: #a3a3a3; }
    .stExpander { border-color: #262626 !important; }
    div[data-testid="stExpander"] details {
        background: #141414; border: 1px solid #262626; border-radius: 8px;
    }
    div[data-testid="stExpander"] summary span { color: #d4d4d4 !important; }
</style>
""", unsafe_allow_html=True)

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
    "client_name": None,
    "changes_log": [],
    "view": "planner",
    # Editor state
    "editor_confirm_delete": False,
}
for key, default in _SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Editor view — full page, no sidebar
# ---------------------------------------------------------------------------
if st.session_state.view == "editor":
    render_customisation_editor(client)
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar (planner view only)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""<div class="sidebar-brand">
        <h2>Ikigai Masala</h2>
        <p>Weekly Menu Planner</p>
    </div>""", unsafe_allow_html=True)

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
    time_limit = st.slider("Solver time (sec)", min_value=10, max_value=600, value=240)

    st.divider()
    generate_clicked = st.button("Generate Menu Plan", type="primary",
                                 use_container_width=True)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
_hdr_col1, _hdr_col2 = st.columns([5, 1])
with _hdr_col1:
    st.markdown('<p class="page-title">Menu Plan</p>', unsafe_allow_html=True)
    if st.session_state.client_name:
        st.markdown(f'<p class="page-subtitle">{st.session_state.client_name}</p>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<p class="page-subtitle">Generate a plan to get started</p>',
                    unsafe_allow_html=True)
with _hdr_col2:
    if st.button("Edit Logic", key="open_editor_btn", use_container_width=True):
        st.session_state.view = "editor"
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
                    time_limit_seconds=time_limit,
                )
                flat_plan = _flatten_solution(result.get("solution", {}))
                st.session_state.plan = flat_plan
                st.session_state.plan_dates = sorted(flat_plan.keys())
                st.session_state.client_name = selected_client
                st.session_state.changes_log = []
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
    # --- Collect slots ---
    all_slots = set()
    for date_str in plan_dates:
        all_slots.update(plan.get(date_str, {}).keys())
    sorted_slots = sorted(all_slots, key=slot_sort_key)

    # --- Metrics ---
    total_items = sum(1 for d in plan_dates for s in sorted_slots
                      if plan.get(d, {}).get(s, ""))
    st.markdown(f"""<div class="metric-row">
        <div class="metric-card"><div class="label">Client</div>
            <div class="value">{st.session_state.client_name}</div></div>
        <div class="metric-card"><div class="label">Days</div>
            <div class="value">{len(plan_dates)}</div></div>
        <div class="metric-card"><div class="label">Slots</div>
            <div class="value">{len(sorted_slots)}</div></div>
        <div class="metric-card"><div class="label">Items</div>
            <div class="value">{total_items}</div></div>
    </div>""", unsafe_allow_html=True)

    # --- Table ---
    header_html = '<tr><th>Slot</th>'
    for d_str in plan_dates:
        d = dt.date.fromisoformat(d_str)
        wd = d.weekday()
        bg, fg, label = WEEKDAY_THEME_BADGES.get(wd, ("#262626", "#a3a3a3", ""))
        header_html += (
            f'<th><span class="day-label">{d.strftime("%a %d %b")}</span>'
            f'<span class="theme-tag" style="background:{bg};color:{fg};">'
            f'{label}</span></th>')
    header_html += '</tr>'

    body_html = ''
    for slot_id in sorted_slots:
        body_html += f'<tr><td>{display_label_for_slot_id(slot_id)}</td>'
        for d_str in plan_dates:
            raw_item = plan.get(d_str, {}).get(slot_id, "")
            body_html += f'<td>{format_item_html(raw_item)}</td>'
        body_html += '</tr>'

    st.markdown(
        f'<table class="menu-table"><thead>{header_html}</thead>'
        f'<tbody>{body_html}</tbody></table>',
        unsafe_allow_html=True)

    st.markdown("")

    # --- Actions ---
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    with c1:
        if st.button("Save to History", use_container_width=True):
            try:
                client.save(client_name=st.session_state.client_name,
                            week_plan=plan, week_start=plan_dates[0])
                st.toast("Plan saved!", icon="✓")
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
            wd = d.weekday()
            bg, fg, label = WEEKDAY_THEME_BADGES.get(wd, ("#262626", "#a3a3a3", ""))
            col = cols[i % len(cols)]
            with col:
                st.markdown(
                    f'<div class="regen-day-header">{d.strftime("%a %d %b")} '
                    f'<span class="theme-tag" style="background:{bg};color:{fg};'
                    f'font-size:0.6rem;">{label}</span></div>',
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
                            time_limit_seconds=time_limit)
                        flat_regen = _flatten_solution(result.get("solution", {}))
                        st.session_state.plan = flat_regen if flat_regen else plan
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
        <div class="icon">🍛</div>
        <h3>No menu plan yet</h3>
        <p>Select a client and click <b>Generate Menu Plan</b> in the sidebar.</p>
    </div>""", unsafe_allow_html=True)
