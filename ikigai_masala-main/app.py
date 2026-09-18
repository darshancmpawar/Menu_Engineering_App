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
import logging
import threading
import time

import streamlit as st


def _bridge_streamlit_secrets() -> None:
    """Copy Supabase credentials out of ``st.secrets`` into the environment.

    Streamlit-hosted deployments supply credentials via
    ``.streamlit/secrets.toml``, and ``src/db.py`` used to read ``st.secrets``
    itself — which made the database singleton import a UI framework, so the
    domain could not be used without Streamlit installed. Reading them here
    instead keeps that deployment working with the dependency pointing the right
    way: the interface knows about its own host, and ``src/`` only reads env.

    Secrets win over pre-existing environment variables, preserving the old
    precedence (``st.secrets`` was tried first). Must run before anything touches
    the database — hence at import, above the modules that do.
    """
    for name in ('SUPABASE_URL', 'SUPABASE_KEY'):
        try:
            value = st.secrets[name]
        except Exception:
            continue          # no secrets.toml, or key absent → env is the source
        if value:
            os.environ[name] = str(value)


_bridge_streamlit_secrets()

from ui.api_client import MenuApiClient, RuleDiagnosticsBlockedError
from ui.formatters import (
    dishes_from_solution,
    display_label_for_slot_id,
    flatten_api_solution,
    format_item_for_ui,
    meal_difference,
    MIN_MEAL_DIFFERENCE,
    nonveg_slots_from_solution,
    shared_items_from_solution,
    slot_sort_key,
    THEME_TAG_COLORS,
    THEME_ICONS,
)
# The two service names. Imported rather than spelled as literals so the UI,
# the API payloads and the history key cannot drift apart.
from src.history import DINNER, LUNCH
from ui.planner_view import (
    date_label,
    flatten_result,
    menu_table_html,
    download_filename,
    plan_xlsx,
    XLSX_MIME,
)
from src.explain.checks import MAIN_COURSES, base_slot
from ui.styles import STYLES
from ui.branding import favicon as _favicon, logo_img_tag
from ui.backend_probe import health_check, pick_backend_port
from customisation.main import render_customisation_editor


logger = logging.getLogger(__name__)

# Streamlit-side cap on solver wall-clock per request. The API itself
# accepts up to MAX_TIME_LIMIT_SECONDS; we send a tighter value so a
# single slow request doesn't pin a worker for the full 10-minute API
# ceiling. Tuned against the 5-day default plan; revisit if num_days
# grows or rule count balloons.
_PLANNING_TIME_LIMIT_SECONDS = 180


def _render_view_error(view_name: str, exc: BaseException) -> None:
    """Show a clean Streamlit-native error block for an unhandled
    exception inside a top-level view (editor / planner).

    The full traceback lands in the server log via ``logger.exception``;
    the user sees a short message + a button to bounce back to the
    planner. Without this guard a render-side bug renders a half-page
    or — depending on Streamlit's config — a full Python traceback,
    neither of which is acceptable for a multi-user deployment.
    """
    logger.exception("Unhandled error in %s view", view_name)
    st.error(
        f"Something went wrong loading the {view_name}. "
        "The error has been logged. Please go back and try again."
    )
    if st.button("Back to planner", key=f"err_back_{view_name}"):
        st.session_state.view = "planner"
        st.rerun()


# ---------------------------------------------------------------------------
# Auto-start Flask API backend
# ---------------------------------------------------------------------------
_BACKEND_URL = None  # set by _ensure_backend_running()


def _start_flask_backend(port: int) -> None:
    # api.app's module-level validate_required_env() raises if any
    # required var is missing; let that bubble up so the Streamlit
    # process shows a clear error instead of a silent backend crash.
    # Logging is configured inside api.app via configure_logging(),
    # so don't install a second root handler here.
    from api.app import app as flask_app
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
    page_icon=_favicon(),  # SmartQ logo if ui/assets/smartq_logo.png exists, else emoji
    layout="wide",
    initial_sidebar_state="expanded",
)

# The planner uses the dark theme (ui/styles.py); the customisation editor is
# a self-contained full-page view rendered against the Pulse light theme, so
# skip the dark stylesheet while the editor is active — otherwise the two sets
# of !important rules fight and the editor renders half-dark. The editor
# injects its own Pulse CSS in render_customisation_editor().
if st.session_state.get("view", "planner") != "editor":
    st.markdown(STYLES, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Backend must be up before we render anything (the UI hits the API).
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

# Streamlit reruns the entire script on every widget interaction, so a
# naïve `MenuApiClient(_BACKEND_URL)` rebuilds a fresh requests.Session
# on every click — connection pool, retry adapter, etc. — for no
# reason. Cache one client per base URL so the underlying HTTPS pool
# survives across reruns.
@st.cache_resource(show_spinner=False)
def _get_api_client(base_url: str) -> MenuApiClient:
    return MenuApiClient(base_url)


client = _get_api_client(_BACKEND_URL)


# Cache low-churn reads (60s TTL): the sidebar's client picker re-renders
# on every interaction but the list itself only changes when someone
# creates/deletes a client. The underscore-prefixed arg is excluded from
# the hash key (Streamlit can't hash MenuApiClient).
@st.cache_data(ttl=60, show_spinner=False)
def _cached_list_clients(_api: MenuApiClient) -> list:
    """Return ``[{'name', 'city'}, …]`` for the sidebar's client + city pickers."""
    return _api.list_clients_with_city()


#: A working week for a weekday-only kitchen, and for one that serves Sat/Sun.
WEEK_LENGTH_WEEKDAYS = 5
WEEK_LENGTH_WITH_WEEKENDS = 7


@st.cache_data(ttl=60, show_spinner=False)
def _cached_serves_dinner(_api: MenuApiClient, client_name: str) -> bool:
    """Does this client serve a second meal? False on any failure.

    False is the safe default in both directions: it never doubles a solve
    nobody asked for, and the sidebar checkbox above it can always turn dinner
    on for this run regardless of what the database says.
    """
    try:
        return bool(_api.get_client_config(client_name).get("serve_dinner"))
    except Exception:
        return False


@st.cache_data(ttl=60, show_spinner=False)
def _cached_week_length(_api: MenuApiClient, client_name: str) -> int:
    """How many days this client's week is — the horizon default.

    5 for a Mon-Fri kitchen, 7 for one that serves Saturday and Sunday. A
    weekend site asked for "5 days" got Mon-Fri and no weekend at all, so the
    default has to follow the client rather than the app.

    Falls back to 5 if the config cannot be read: a wrong default is a slider
    the operator moves, while an exception here would take the sidebar down.
    """
    try:
        cfg = _api.get_client_config(client_name)
    except Exception:  # noqa: BLE001 — the sidebar must render regardless
        return WEEK_LENGTH_WEEKDAYS
    return (WEEK_LENGTH_WITH_WEEKENDS if cfg.get("serve_weekends")
            else WEEK_LENGTH_WEEKDAYS)

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
_SESSION_DEFAULTS = {
    "plan": None,
    "plan_dates": [],
    "day_types": {},
    "pool_warnings": [],
    "client_name": None,
    "changes_log": [],
    "view": "planner",
    # "history" when the current plan was loaded from /saved-plan,
    # "solver" when it came from /plan, "modified" once the user has
    # regenerated a cell (so the on-screen plan no longer matches the
    # DB version), "preflight_blocked" when the diagnostic gate stopped
    # the solver from running. Drives the badge on the page header.
    "plan_source": None,
    # Pre-flight rule_diagnostics from the most recent /plan or
    # /saved-plan response (or from a RuleDiagnosticsBlockedError).
    # Empty list = nothing to show. Rendered as the inline expander
    # above the plan table.
    "rule_diagnostics": [],
    "diagnostics_summary": None,
    # Unified plan state: a list of per-counter "blocks". Single-cuisine
    # clients have one block; multi-cuisine clients have one per counter.
    # Each block: {name, plan, plan_dates, day_types, pool_warnings, source, error}.
    "plan_blocks": [],
    # Two services a day (feature: lunch + dinner). `meal_blocks` holds one
    # block list per service and `plan_blocks` MIRRORS the selected one, so
    # every display, regenerate and save path below is unchanged — a one-meal
    # client simply has a single entry and never sees the switcher.
    "meal_blocks": {},
    "active_meal": LUNCH,
    "plan_mode": "single",
    # Launch view (feature F): when on, the sidebar lists launch sites only —
    # otherwise the UI is identical to the normal planner. Defaults off.
    "launch_mode": False,
}
for key, default in _SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Editor view (full-page)
# ---------------------------------------------------------------------------
if st.session_state.view == "editor":
    try:
        # launch_mode is carried so a client created here while the launch
        # toggle is on is flagged is_launch_site. The editor UI is identical
        # in both modes.
        render_customisation_editor(
            client, launch_mode=st.session_state.get("launch_mode", False))
    except Exception as _exc:
        # A Supabase blip while loading client config, a malformed rule
        # in client_rules.json, etc. Log + show a friendly fallback so
        # the user can navigate out instead of staring at a half-page.
        _render_view_error("editor", _exc)
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar (planner view)
# ---------------------------------------------------------------------------
with st.sidebar:
    _logo_tag = logo_img_tag(height=30)
    _brand_icon = (
        f'<div class="sidebar-brand-icon" style="background:transparent;'
        f'box-shadow:none;">{_logo_tag}</div>'
        if _logo_tag
        else '<div class="sidebar-brand-icon">&#127835;</div>'
    )
    st.markdown(f"""<div class="sidebar-brand">
        <div class="sidebar-brand-row">
            {_brand_icon}
            <div>
                <h2>Ikigai Masala</h2>
                <p>Weekly Menu Planner</p>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # Launch view toggle — sits above City (feature F). Off by default; on →
    # the picker lists launch sites only. The rest of the UI is unchanged, so a
    # launch site is planned/edited exactly like any other client. A client
    # created via Edit Logic while this is on is flagged a launch site. Off =
    # the Ops Client View (every client that is not a launch site).
    launch_mode = st.toggle(
        "Launch sites", key="launch_mode",
        help="Show launch sites only. A client created via Edit Logic while "
             "this is on becomes a launch site. Off = Ops Client View (all "
             "non-launch clients).",
    )
    if launch_mode:
        st.caption("🚀 **Launch view** — showing launch sites only")
    else:
        st.caption("🗂️ **Ops Client View** — showing operational (non-launch) "
                   "clients")

    try:
        clients_detail = _cached_list_clients(client)
    except (ConnectionError, OSError, ValueError):
        clients_detail = []
        st.error("Cannot reach API.")

    # Launch view lists launch sites only; the Ops Client View lists the rest
    # (a client is in exactly one of the two).
    if launch_mode:
        clients_detail = [c for c in clients_detail if c.get("is_launch_site")]
    else:
        clients_detail = [c for c in clients_detail
                          if not c.get("is_launch_site")]

    # City filter — single-select, default "All". Only cities that actually
    # have (in-scope) clients are offered, so no selection yields an empty list.
    cities = sorted({c.get("city") for c in clients_detail if c.get("city")})
    city_filter = st.selectbox("City", ["All"] + cities,
                               key="planner_city_filter")
    if city_filter == "All":
        clients_list = [c["name"] for c in clients_detail]
    else:
        clients_list = [c["name"] for c in clients_detail
                        if c.get("city") == city_filter]

    _client_label = "Launch site" if launch_mode else "Client"
    _empty_msg = "(no launch sites yet)" if launch_mode else "(no clients)"
    selected_client = st.selectbox(_client_label,
        clients_list if clients_list else [_empty_msg],
        key="planner_client_select")

    # Launch -> Ops: reclassify the selected launch site as an operational
    # (non-launch) client. It then leaves the Launch view and appears in the
    # Ops Client View. Only offered in launch view for a real selection.
    if launch_mode and selected_client and selected_client != _empty_msg:
        if st.button("Move to Ops Client View", key="planner_demote_btn",
                     use_container_width=True,
                     help="Reclassify this launch site as an operational client "
                          "(is_launch_site = false)."):
            try:
                _cfg = client.get_client_config(selected_client)
                client.update_client_config(selected_client, {
                    "version": _cfg.get("version"),
                    "is_launch_site": False,
                })
                st.cache_data.clear()
                st.session_state.pop("planner_client_select", None)
                st.toast(f"{selected_client} moved to Ops Client View", icon="🗂️")
                st.rerun()
            except Exception as e:  # noqa: BLE001 — surface any API error inline
                st.error(f"Could not move client: {e}")

    start_date = st.date_input("Start date", value=dt.date.today(),
                               key="planner_start_date")

    # The horizon default is the CLIENT's week, not the app's: 7 for a site
    # that serves Sat/Sun, 5 otherwise. Reset when the client changes, because
    # a Streamlit widget with a `key` keeps its session value and would carry
    # a 5 over to a weekend site (and a 7 back to a weekday one).
    _week = (_cached_week_length(client, selected_client)
             if clients_list and selected_client != _empty_msg
             else WEEK_LENGTH_WEEKDAYS)
    if st.session_state.get("_planner_week_for") != selected_client:
        st.session_state["_planner_week_for"] = selected_client
        st.session_state["planner_num_days"] = _week

    _serves_weekends = _week == WEEK_LENGTH_WITH_WEEKENDS
    num_days = st.slider(
        "Days" if _serves_weekends else "Weekdays",
        min_value=1, max_value=20, value=_week, key="planner_num_days",
        help=("Number of days (this client serves Sat/Sun)" if _serves_weekends
              else "Number of weekdays (Sat/Sun are skipped). A day the client "
                   "does not work is still shown, as a blank column."))

    # Plan dinner as well as lunch. Defaults to the client's stored
    # `serve_dinner`, and is a control HERE rather than only in the editor
    # because the stored value depends on a `clients.serve_dinner` column that
    # a deployment may not have migrated yet — and a missing COLUMN is caught
    # by `_is_missing_relation` and degrades to False, so the feature was
    # silently off with nothing anywhere saying why. A per-run checkbox cannot
    # be defeated by an un-run migration.
    _client_wants_dinner = (
        _cached_serves_dinner(client, selected_client)
        if clients_list and selected_client != _empty_msg else False)
    if st.session_state.get("_planner_dinner_for") != selected_client:
        st.session_state["_planner_dinner_for"] = selected_client
        st.session_state["planner_serve_dinner"] = _client_wants_dinner
    plan_dinner = st.checkbox(
        "Also plan dinner", key="planner_serve_dinner",
        help="Generates a second menu for the same dates, below lunch, "
             "avoiding lunch's dishes. Roughly doubles the solve time.")

    st.divider()
    generate_clicked = st.button("Generate Menu Plan", type="primary",
                                 key="planner_generate_btn",
                                 use_container_width=True)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
_hdr_col1, _hdr_col2 = st.columns([5, 2])
_SOURCE_BADGES = {
    # bg, fg, label, title attr — Pulse low-emphasis badge tints
    "history":  ("#E5FFF1", "#1AA45B", "Loaded from history",
                 "These exact dates already had a saved plan — shown as-is."),
    "solver":   ("#F3ECFF", "#6F42C1", "Freshly generated",
                 "No saved plan for these dates — solver produced this from scratch."),
    "modified": ("#FFF5E8", "#C56A00", "Modified — unsaved",
                 "You regenerated at least one cell since this plan was loaded."),
    "preflight_blocked": ("#FFE7E9", "#C40D1B", "Pre-flight blocked",
                 "Diagnostic checks found a guaranteed failure; solver skipped."),
}


# bg, fg, label per Diagnostic severity (Pulse status tints).
_SEVERITY_STYLE = {
    "error":   ("#FFE7E9", "#C40D1B", "Error"),
    "warning": ("#FFF5E8", "#C56A00", "Warning"),
    "info":    ("#EBF3FF", "#0D6EFD", "Info"),
}


def _render_diagnostics_expander(diagnostics, summary):
    """Render the inline 'Diagnostics' expander above the plan table.

    Auto-expanded when any error is present (the user must act);
    collapsed otherwise. Sectioned by severity so errors are visible
    first. Reuses the design tokens from ``ui/styles.py``.
    """
    if not diagnostics:
        return
    has_error = bool(summary and summary.get("errors", 0)) or any(
        d.get("severity") == "error" for d in diagnostics
    )
    counts = []
    if summary:
        if summary.get("errors"):
            counts.append(f"{summary['errors']} error"
                          f"{'s' if summary['errors'] != 1 else ''}")
        if summary.get("warnings"):
            counts.append(f"{summary['warnings']} warning"
                          f"{'s' if summary['warnings'] != 1 else ''}")
        if summary.get("infos"):
            counts.append(f"{summary['infos']} info")
    label = (
        f"Diagnostics ({', '.join(counts)})" if counts else "Diagnostics"
    )

    with st.expander(label, expanded=has_error):
        # Group by severity so errors come first regardless of how the
        # server sorted them.
        order = ("error", "warning", "info")
        grouped = {sev: [d for d in diagnostics if d.get("severity") == sev] for sev in order}
        for sev in order:
            items = grouped[sev]
            if not items:
                continue
            bg, fg, sev_label = _SEVERITY_STYLE.get(sev, ("#F0F0F0", "#555555", sev.title()))
            st.markdown(
                f'<p style="font-size:0.85rem;font-weight:700;color:{fg};'
                f'margin:0.5rem 0 0.4rem;">{sev_label}'
                f' ({len(items)})</p>',
                unsafe_allow_html=True,
            )
            for d in items:
                rule_pill = html.escape(d.get("rule_type") or d.get("rule") or "?")
                msg = html.escape(d.get("message") or "")
                suggestion = html.escape(d.get("suggestion") or "")
                affected = d.get("affected") or {}
                chips = []
                # Surface the most commonly-useful affected fields as
                # chips; everything else stays inside ``affected`` for
                # the API surface but isn't visualised.
                for k in ("date", "day_type", "slot"):
                    if k in affected:
                        chips.append(
                            f'<span style="background:#F0F0F0;color:#555555;'
                            f'border-radius:99px;padding:1px 8px;font-size:0.65rem;'
                            f'margin-right:4px;">{html.escape(str(affected[k]))}</span>'
                        )
                chip_html = ''.join(chips)
                st.markdown(
                    f'<div style="background:{bg};border-left:3px solid {fg};'
                    f'padding:0.55rem 0.8rem;border-radius:8px;'
                    f'margin-bottom:0.45rem;">'
                    f'<div style="display:flex;align-items:center;gap:0.45rem;'
                    f'margin-bottom:0.2rem;">'
                    f'<span style="background:{fg};color:{bg};font-weight:700;'
                    f'font-size:0.6rem;letter-spacing:0.04em;text-transform:uppercase;'
                    f'padding:1px 7px;border-radius:99px;">{rule_pill}</span>'
                    f'{chip_html}'
                    f'</div>'
                    f'<div style="color:#131313;font-size:0.85rem;'
                    f'line-height:1.4;">{msg}</div>'
                    + (f'<div style="color:#777777;font-size:0.75rem;'
                       f'margin-top:0.25rem;">Fix: {suggestion}</div>'
                       if suggestion else '')
                    + '</div>',
                    unsafe_allow_html=True,
                )


with _hdr_col1:
    st.markdown('<p class="page-title">Menu Plan</p>', unsafe_allow_html=True)
    if st.session_state.client_name:
        src = st.session_state.get("plan_source")
        badge_html = ""
        if src in _SOURCE_BADGES:
            bg, fg, label, title_attr = _SOURCE_BADGES[src]
            badge_html = (
                f'<span class="plan-source-badge" '
                f'title="{html.escape(title_attr)}" '
                f'style="display:inline-block;margin-left:0.6rem;'
                f'padding:2px 10px;border-radius:99px;font-size:0.7rem;'
                f'font-weight:700;letter-spacing:0.04em;text-transform:uppercase;'
                f'background:{bg};color:{fg};vertical-align:middle;">'
                f'{html.escape(label)}</span>'
            )
        st.markdown(
            f'<p class="page-subtitle">Generated plan for '
            f'{html.escape(st.session_state.client_name)}{badge_html}</p>',
            unsafe_allow_html=True)
    else:
        st.markdown(
            '<p class="page-subtitle">Select a client and generate a plan to get started</p>',
            unsafe_allow_html=True)
with _hdr_col2:
    if st.button("Edit Logic", key="open_editor_btn", use_container_width=True):
        st.session_state.view = "editor"
        st.rerun()

# Planner render/export helpers live in ui/planner_view.py.


def _pool_warnings_expander(block: dict) -> None:
    warns = block.get("pool_warnings") or []
    if warns:
        with st.expander(f"Pool warnings ({len(warns)})", expanded=False):
            for w in warns:
                st.markdown(
                    f'<div class="pool-warn-bar">&#9888; {html.escape(str(w))}</div>',
                    unsafe_allow_html=True)


def _render_explain_expander(api, block_index: int, counter_index: int,
                             key_ns: str) -> None:
    """"Why this menu" for one plan block — a stepped read, not a text dump.

    Behind a button rather than fetched alongside the plan: /explain is a
    second request and an optional one, so a user who never opens this pays
    nothing for it, and a failure here can never cost anyone a menu.

    **The order is the argument.** A chef opening this wants four things in this
    sequence and gets lost if they arrive mixed together, which is what the
    first version did — one monospaced block with the plate, the verdicts, the
    reasons and the relaxations interleaved:

      1. what is on the plate
      2. how it balances (only the verdicts fit to be judged — `CALIBRATED`)
      3. why THESE dishes
      4. what the solver could not fully enforce

    Step 4 is last and is never hidden. It is the honest half: a rule that bent
    is the one thing here the kitchen can act on, and burying it under three
    green ticks is how a diagnostic becomes decoration.

    The numbers are still the renderer's — `src/explain/renderer.py` remains the
    single place that decides how a verdict READS, and the raw bullet text stays
    available under each day for anyone who wants to copy it.
    """
    b = st.session_state.plan_blocks[block_index]
    if not b.get("plan_dates") or not b.get("solution"):
        return
    store = st.session_state.setdefault("explanations", {})
    cache_key = f"{st.session_state.client_name}|{key_ns}|{b['plan_dates'][0]}"
    with st.expander("Why this menu"):
        st.caption(
            "Plate-balance checks read off the menu itself, the reason each "
            "dish is there, and any rule the solver could not fully enforce. "
            "A flagged check is a suggestion; a relaxed rule is a fact.")
        if st.button("Explain this menu", key=f"explain_btn_{key_ns}",
                     use_container_width=True):
            try:
                store[cache_key] = api.explain(
                    client_name=st.session_state.client_name,
                    # plan_dates spans the horizon including days this client
                    # does not serve, so [0] is the horizon start and the count
                    # is its length.
                    start_date=b["plan_dates"][0],
                    num_days=len(b["plan_dates"]),
                    counter_index=counter_index,
                    solution=b.get("solution") or {},
                    relaxations=b.get("relaxations") or None,
                )
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Could not explain this menu: {e}")
        payload = store.get(cache_key)
        if not payload:
            return

        days = payload.get("days") or []
        if not days:
            st.info("No served day in this plan has a plate to describe.")
            return

        # A relaxation is plan-wide, so it is stated ONCE at the top rather than
        # repeated under every day — twenty identical warnings read as noise and
        # the reader stops seeing them.
        relaxed = days[0].get("relaxations") or []
        if relaxed:
            st.warning(
                "**Rules the solver could not fully enforce for this counter**")
            for r in relaxed:
                rule = str(r.get("rule") or "a rule").replace("_", " ")
                st.markdown(f"- **{rule}** — {html.escape(str(r.get('detail','')))}")
                for extra in (r.get("samples") or [])[1:]:
                    st.caption(f"　also: {html.escape(str(extra))}")
        if payload.get("llm_used"):
            st.caption("Prose written by the optional model and checked against "
                       "the facts below; the numbers are computed, not written.")

        tabs = st.tabs([date_label(d["date"]) for d in days])
        for tab, day in zip(tabs, days):
            with tab:
                _render_explain_day(day)


def _render_explain_day(day: dict) -> None:
    """One day of the explanation, in the four steps above."""
    profile = day.get("plate_profile") or {}
    theme = day.get("theme")
    if theme:
        st.markdown(f"**{date_label(day['date'])}** &nbsp; · &nbsp; "
                    f"{str(theme).replace('_', ' ').title()} day",
                    unsafe_allow_html=True)
    if day.get("prose"):
        st.info(day["prose"])

    cols = st.columns(4)
    for col, (label, value) in zip(cols, (
        ("Main dishes", profile.get("main_dish_count") or 0),
        ("Colours", len(profile.get("colour_spread") or {})),
        ("Textures", len(profile.get("texture_spread") or {})),
        ("Avg richness", profile.get("mean_richness")),
    )):
        with col:
            st.metric(label, "—" if value is None else value)

    # The overview comes FIRST and reads as prose: four or five sentences about
    # what goes with what on this plate and what it lacks. Everything below it
    # is the working — the itemised plate, the pairings one per line, the
    # verdicts — for a reader who wants to check it. Most readers do not: they
    # want to know whether today's combination works, which is a paragraph.
    # `overview` is already the model's paragraph when one was configured and
    # its reply passed the validator, and the rendered fallback otherwise —
    # the API picks, so this does not repeat that decision. `prose` is still
    # read as a fallback for an API that predates `overview_source`.
    overview = (day.get("overview") or day.get("prose") or "").strip()
    if overview:
        st.markdown(
            f"<div style='padding:.6rem .8rem;border-left:3px solid #4c8bf5;"
            f"opacity:.95;margin-bottom:.8rem'>{html.escape(overview)}</div>",
            unsafe_allow_html=True)

    st.markdown("**1 · The plate**")
    dishes = day.get("dishes") or {}
    if dishes:
        # The checks score MAIN courses only — a welcome drink's colour says
        # nothing about whether lunch works, and counting white_rice would put
        # a white dish on every day and flatten the colour verdict into noise.
        # So the plate lists everything and MARKS what was counted: without the
        # marker a reader sees fourteen dishes above "Main dishes 7" and has no
        # way to tell which seven, which makes every number below it look wrong.
        counted = {s for s in dishes if base_slot(s) in MAIN_COURSES}
        for slot, dish in sorted(dishes.items(), key=lambda kv: slot_sort_key(kv[0])):
            traits = " · ".join(
                str(dish[k]) for k in ("item_color", "texture")
                if dish.get(k)) or "no attributes recorded"
            mark = "●" if slot in counted else "○"
            st.markdown(
                f"- {mark} `{display_label_for_slot_id(slot)}` &nbsp; "
                f"**{format_item_for_ui(dish.get('name'))}** &nbsp; "
                f"<span style='opacity:.65'>{html.escape(traits)}</span>",
                unsafe_allow_html=True)
        st.caption("● counted by the checks below  ·  ○ condiment, drink or "
                   "staple — not scored")
    else:
        st.caption("The plate is not itemised in this response.")

    # Step 2 is the question a chef asks first — not "how many textures" but
    # "does this meal work". It sits above the checks because a pairing names
    # two dishes and a reason, which is actionable on its own, where "4 colours
    # across 7 dishes" still has to be interpreted.
    pairings = day.get("pairings") or {}
    st.markdown("**2 · What works together**")
    if pairings.get("summary"):
        st.caption(html.escape(str(pairings["summary"])))
    for pair in pairings.get("pairings") or []:
        st.markdown(f"- 🤝 {html.escape(str(pair.get('detail','')))}")
    # Gaps are never hidden or folded into the summary line. A plate with a hot
    # curry and no yogurt is the one thing here a kitchen can fix this morning,
    # and an explanation that only ever reports good news gets ignored.
    for gap in pairings.get("gaps") or []:
        st.markdown(f"- &#9888; {html.escape(str(gap))}")
    if not (pairings.get("pairings") or pairings.get("gaps")):
        st.caption("No pairing could be argued from the recorded attributes.")

    st.markdown("**3 · How it balances**")
    for check in day.get("checks") or []:
        icon = "&#9989;" if check.get("passed") else "&#9888;"
        name = str(check.get("name", "")).replace("_", " ")
        st.markdown(f"{icon} **{name}** — {html.escape(str(check.get('detail','')))}",
                    unsafe_allow_html=True)

    provenance = day.get("provenance") or []
    if provenance:
        st.markdown("**4 · Why these dishes**")
        for p in provenance:
            st.markdown(
                f"- **{format_item_for_ui(p.get('dish'))}** — "
                f"{html.escape(str(p.get('detail','')))}")

    if day.get("bullets"):
        with st.expander("Plain text (copy)"):
            st.code("\n".join(day["bullets"]), language=None)


def _render_regen_expander(api, block_index: int, counter_index: int,
                           key_ns: str) -> None:
    """Regenerate-cells panel for one plan block; mutates
    st.session_state.plan_blocks[block_index] in place and reruns."""
    b = st.session_state.plan_blocks[block_index]
    plan, plan_dates, day_types = b["plan"], b["plan_dates"], b["day_types"]
    with st.expander("Regenerate cells"):
        st.caption("Pick slots to replace with fresh items.")
        regen_selections = {}
        cols_per_row = min(len(plan_dates), 3) or 1
        cols = st.columns(cols_per_row)
        for i, d_str in enumerate(plan_dates):
            try:
                d_lbl = dt.date.fromisoformat(d_str).strftime("%a %d %b")
            except ValueError:
                d_lbl = d_str
            day_type = day_types.get(d_str, "")
            bg, fg = THEME_TAG_COLORS.get(day_type, ("#F0F0F0", "#777777"))
            icon = THEME_ICONS.get(day_type, "")
            label = day_type.replace("_", " ").title() if day_type else ""
            with cols[i % cols_per_row]:
                st.markdown(
                    f'<div class="regen-day-header">{d_lbl} '
                    f'<span class="theme-tag" style="background:{bg};color:{fg};'
                    f'font-size:0.6rem;">{icon} {label}</span></div>',
                    unsafe_allow_html=True)
                day_map = plan.get(d_str, {})

                def _fmt(slot_id, _dm=day_map):
                    cur = format_item_for_ui(_dm.get(slot_id, ""))
                    lbl = display_label_for_slot_id(slot_id)
                    return f"{lbl} — {cur}" if cur else lbl

                day_slots = sorted(day_map.keys(), key=slot_sort_key)
                selected = st.multiselect(
                    f"Slots for {d_str}", day_slots, format_func=_fmt,
                    key=f"regen_{key_ns}_{d_str}", label_visibility="collapsed")
                if selected:
                    regen_selections[d_str] = selected

        if st.button("Regenerate Selected", type="primary",
                     key=f"regen_btn_{key_ns}"):
            if not regen_selections:
                st.warning("Select at least one cell.")
                return
            old_snap = {
                (d, s): plan.get(d, {}).get(s, "")
                for d, slots in regen_selections.items() for s in slots
            }
            # Exclude every item already shown for each selected cell this
            # session (plus its current item), so repeated regenerations keep
            # producing something new instead of flipping A->B->A. Keyed per
            # (counter, date, slot); reset when the pool is exhausted.
            seen_store = st.session_state.setdefault("regen_seen", {})
            exclude_items = {}
            for d_str, slots in regen_selections.items():
                for s in slots:
                    k = f"{counter_index}|{d_str}|{s}"
                    ex = set(seen_store.get(k, set()))
                    cur = plan.get(d_str, {}).get(s, "")
                    if cur:
                        ex.add(cur)
                    if ex:
                        exclude_items.setdefault(d_str, {})[s] = sorted(ex)
            with st.spinner("Regenerating..."):
                try:
                    result = api.regenerate(
                        client_name=st.session_state.client_name,
                        base_plan=plan, replace_slots=regen_selections,
                        start_date=plan_dates[0], num_days=len(plan_dates),
                        time_limit_seconds=_PLANNING_TIME_LIMIT_SECONDS,
                        counter_index=counter_index,
                        exclude_items=exclude_items)
                    solution = result.get("solution", {})
                    flat_regen, regen_day_types = flatten_api_solution(solution)
                    new_plan = flat_regen if flat_regen else plan
                    # Record what each cell now shows so the next regenerate
                    # avoids it too; if the solver had to repeat an already-seen
                    # item (pool exhausted), restart that cell's cycle.
                    for d_str, slots in regen_selections.items():
                        for s in slots:
                            k = f"{counter_index}|{d_str}|{s}"
                            prev = set(seen_store.get(k, set()))
                            new_item = new_plan.get(d_str, {}).get(s, "")
                            old_item = plan.get(d_str, {}).get(s, "")
                            if new_item and new_item in prev:
                                seen_store[k] = {new_item}
                            else:
                                seen_store[k] = prev | {
                                    x for x in (old_item, new_item) if x}
                    b["plan"] = new_plan
                    if regen_day_types:
                        b["day_types"] = regen_day_types
                    b["plan_dates"] = sorted(new_plan.keys())
                    if flat_regen:
                        b["nonveg"] = nonveg_slots_from_solution(solution)

                    diffs = []
                    for (d, s), old_raw in old_snap.items():
                        op = format_item_for_ui(old_raw)
                        np = format_item_for_ui(new_plan.get(d, {}).get(s, ""))
                        if op == np:
                            continue
                        try:
                            dl = dt.date.fromisoformat(d).strftime("%a %d %b")
                        except ValueError:
                            dl = d
                        diffs.append({
                            "kind": "regen", "counter": b["name"], "day": dl,
                            "slot": display_label_for_slot_id(s),
                            "old": op, "new": np,
                        })
                    if diffs:
                        st.session_state.changes_log.extend(diffs)
                        b["source"] = "modified"
                        st.session_state.plan_source = "modified"
                    st.rerun()
                except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                    st.error(f"Regeneration failed: {e}")


def _render_changes_log() -> None:
    log = st.session_state.get("changes_log") or []
    if not log:
        return
    with st.expander("Changes log", expanded=True):
        for entry in log:
            if isinstance(entry, dict) and entry.get("kind") == "regen":
                ctr = entry.get("counter")
                ctr_html = (
                    f'<span class="log-slot">{html.escape(ctr)}</span>'
                    f'<span class="log-sep">&middot;</span>' if ctr else ''
                )
                st.markdown(
                    '<div class="log-entry log-diff">'
                    f'{ctr_html}'
                    f'<span class="log-day">{html.escape(entry["day"])}</span>'
                    f'<span class="log-sep">&middot;</span>'
                    f'<span class="log-slot">{html.escape(entry["slot"])}</span>'
                    f'<span class="log-sep">&middot;</span>'
                    f'<span class="log-old">{html.escape(entry["old"] or "(empty)")}</span>'
                    '<span class="log-arrow">&rarr;</span>'
                    f'<span class="log-new">{html.escape(entry["new"] or "(empty)")}</span>'
                    '</div>',
                    unsafe_allow_html=True)
            else:
                text = entry.get("text", "") if isinstance(entry, dict) else str(entry)
                st.markdown(
                    f'<div class="log-entry">{html.escape(text)}</div>',
                    unsafe_allow_html=True)


def _client_counter_names(api, name: str):
    """(mode, [counter names], city, shared_categories, excluded, serve_dinner).

    ``shared_categories`` are the base slots this client serves identically
    across its counters — the planner pins the primary counter's dish for each
    into the others. ``excluded`` names the counters that opt out of that sync
    (ICON Chn's Rice Combo, which the client states has its own menu).
    ``serve_dinner`` asks for a second service after lunch.

    Degrades to a single unsynced lunch-only counter if the config cannot be
    read — the conservative direction on every field, since guessing a second
    service into existence would double a client's solve time on a config read
    that failed.
    """
    try:
        cfg = api.get_client_config(name)
        counters = cfg.get("counters") or []
        names = [(c.get("name") or f"Counter {i + 1}")
                 for i, c in enumerate(counters)] or ["Counter 1"]
        return (cfg.get("counter_mode", "single"), names, cfg.get("city"),
                cfg.get("shared_categories") or [],
                set(cfg.get("shared_categories_excluded_counters") or []),
                bool(cfg.get("serve_dinner")))
    except Exception:
        return "single", ["Counter 1"], None, [], set(), False


def _solve_counters(api, name, counter_names, start_iso, days, *,
                    shared_categories, shared_excluded, time_limit,
                    meal=None, exclude_by_counter=None):
    """Solve every counter for ONE service. Returns (blocks, diagnostics, summary).

    Factored out because lunch and dinner are the same pass with a different
    `meal` and a different exclusion set — the second service must not be a
    second code path, or the two drift and only one of them gets the next fix.

    `exclude_by_counter` is `{counter_index: {iso_date: [item, …]}}`: the
    dishes this counter already served at the earlier sitting. Keyed per
    COUNTER, not pooled across the site, because counters are separate
    stations with separate menus — pooling a six-counter site's lunch would
    ban eighty dishes from every dinner cell and starve the thin pools for no
    benefit a diner would notice.
    """
    blocks, diagnostics, summary = [], [], None
    shared_items: list = []
    for i, cname in enumerate(counter_names):
        try:
            send_shared = (
                shared_items if i > 0 and cname not in shared_excluded else None)
            result = api.plan(
                client_name=name, start_date=start_iso, num_days=days,
                time_limit_seconds=time_limit, counter_index=i,
                shared_items=send_shared, meal=meal,
                exclude_items=(exclude_by_counter or {}).get(i))
            if i == 0 and shared_categories:
                shared_items = shared_items_from_solution(
                    result.get("solution", {}), shared_categories)
            blk = flatten_result(result)
            blk["name"] = cname
            if i == 0:
                diagnostics = result.get("rule_diagnostics") or []
                summary = result.get("summary")
        except RuleDiagnosticsBlockedError as e:
            blk = {"name": cname, "plan": {}, "plan_dates": [],
                   "day_types": {}, "pool_warnings": [],
                   "source": "preflight_blocked",
                   "error": str(e) or "Pre-flight blocked for this counter"}
            if i == 0:
                diagnostics = e.diagnostics or []
                summary = e.summary or None
        except (ConnectionError, OSError, ValueError, RuntimeError) as e:
            blk = {"name": cname, "plan": {}, "plan_dates": [],
                   "day_types": {}, "pool_warnings": [],
                   "source": "error", "error": str(e) or "Generation failed"}
            # A solve that fails AFTER a clean pre-flight ships the pre-flight
            # report with the 500; its warnings name the slots under pressure.
            if getattr(e, "diagnostics", None):
                diagnostics = e.diagnostics
                summary = getattr(e, "summary", None) or None
        blk["meal"] = meal or LUNCH
        blocks.append(blk)
    return blocks, diagnostics, summary


def _concat_meal_blocks(meal_order, meal_blocks):
    """`(all_blocks, {meal: offset})` — every service's blocks, lunch first.

    The offset is what turns a counter's position WITHIN its service into its
    position in `st.session_state.plan_blocks`, which is what the regenerate
    and explain panels address. Get it wrong by one and the dinner section's
    Regenerate edits a lunch cell — silently, because both are real blocks and
    the page still renders. That is why this is a function with a test rather
    than a counter incremented inside the render loop.
    """
    blocks, offsets, n = [], {}, 0
    for meal in meal_order:
        offsets[meal] = n
        got = list(meal_blocks.get(meal) or [])
        blocks.extend(got)
        n += len(got)
    return blocks, offsets


def _render_one_block(api, b, block_index: int, counter_index: int,
                      key_ns: str) -> None:
    """One counter's table for one service, with ITS OWN controls.

    `key_ns` scopes every Streamlit widget key. Two services render the same
    counter twice on one page, and Streamlit keys are global — without the
    namespace the dinner tab would reuse lunch's widget state and its
    regenerate panel would edit lunch's plan.

    `block_index` addresses `st.session_state.plan_blocks`, which is every
    service concatenated; `counter_index` is the counter's position within its
    own service, which is what `/plan` and `/regenerate` take.
    """
    _pool_warnings_expander(b)
    st.markdown(
        menu_table_html(b["plan"], b["plan_dates"], b["day_types"],
                        b.get("nonveg"), b.get("off_days")),
        unsafe_allow_html=True)
    st.markdown("")
    _c1, _c2, _rest = st.columns([1, 1, 4])
    with _c2:
        if st.button("Clear", key=f"clear_{key_ns}", use_container_width=True):
            b["plan"], b["plan_dates"], b["day_types"] = {}, [], {}
            b["nonveg"] = {}
            st.rerun()
    _render_regen_expander(api, block_index, counter_index, key_ns)
    _render_explain_expander(api, block_index, counter_index, key_ns)


def _saveable_meals(meal_blocks, fallback_blocks):
    """`[(meal, blocks), …]` for every service that has something to save.

    Falls back to a single lunch entry when `meal_blocks` is empty, which is
    the shape a client generated before this feature existed — and the shape a
    saved-plan REPLAY produces, since only one service is replayed.
    """
    if meal_blocks:
        return [(m, b) for m, b in sorted(meal_blocks.items()) if b]
    return [(LUNCH, fallback_blocks)] if fallback_blocks else []


def _exclusions_from(blocks):
    """`{counter_index: {iso_date: [item, …]}}` from a solved service.

    What stops dinner reprinting lunch. It has to be done here rather than by
    a solver rule because the two services are SEPARATE SOLVES: `unique_items`
    is scoped to one model and cannot see across them, and the item cooldown
    only reads SAVED history, which is after the duplicate is already on
    screen.
    """
    out = {}
    for i, blk in enumerate(blocks):
        raw = blk.get("solution") or {}
        got = dishes_from_solution(raw)
        if got:
            out[i] = got
    return out


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------
if generate_clicked:
    if not selected_client or selected_client == "(no clients)":
        st.warning("Select a valid client first.")
    else:
        (mode, counter_names, city, shared_categories,
         shared_excluded, _cfg_dinner) = _client_counter_names(
            client, selected_client)
        # The sidebar checkbox is the authority for THIS run — it is seeded
        # from the client's stored `serve_dinner` and then owns the decision,
        # so a deployment whose `clients.serve_dinner` column does not exist
        # yet can still plan dinner instead of silently getting lunch only.
        serve_dinner = bool(plan_dinner)
        del _cfg_dinner
        st.session_state.client_name = selected_client
        st.session_state.client_city = city
        st.session_state.plan_mode = mode
        st.session_state.changes_log = []
        # Drop the previous plan BEFORE solving. Without this a failed generation
        # left the last client's table on screen under the new client's name and
        # city — an Amadeus Pune header above a Bangalore counter's chicken and
        # egg dishes, with stale Days / Slots / Total items cards to match.
        st.session_state.plan_blocks = []
        st.session_state.meal_blocks = {}
        st.session_state.active_meal = LUNCH
        st.session_state.plan_source = None
        # Fresh plan → forget which items regenerate has already shown.
        st.session_state.regen_seen = {}
        st.session_state.rule_diagnostics = []
        st.session_state.diagnostics_summary = None

        # The time budget is divided across counters so total wall-clock stays
        # bounded, and across SERVICES too — a dinner site solves twice as many
        # models for one click, and a budget that ignored that would double the
        # wait rather than split it.
        n_services = 2 if serve_dinner else 1
        per_limit = max(
            45,
            _PLANNING_TIME_LIMIT_SECONDS
            // max(1, len(counter_names) * n_services))
        if mode != "multi" and not serve_dinner:
            per_limit = _PLANNING_TIME_LIMIT_SECONDS

        replayed = False
        if mode != "multi":
            # Single-cuisine: saved-plan replay first, unchanged. Only lunch is
            # replayed — a saved dinner is fetched below on its own key.
            try:
                saved = client.get_saved_plan(
                    client_name=selected_client,
                    start_date=start_date.isoformat(), num_days=num_days,
                    meal=LUNCH)
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.warning(f"Couldn't check saved history ({e}); generating fresh.")
                saved = {"exists": False}

            if saved.get("exists"):
                with st.spinner(f"Loading saved plan for {selected_client}..."):
                    blk = flatten_result(saved)
                    blk["name"] = counter_names[0]
                    blk["source"] = "history"
                    blk["meal"] = LUNCH
                    st.session_state.plan_blocks = [blk]
                    st.session_state.meal_blocks = {LUNCH: [blk]}
                    st.session_state.active_meal = LUNCH
                    st.session_state.plan_source = "history"
                    replayed = True

        if not replayed:
            label = ("Generating lunch and dinner" if serve_dinner
                     else "Generating plan")
            with st.spinner(f"{label} for {selected_client}..."):
                lunch_blocks, diags, summary = _solve_counters(
                    client, selected_client, counter_names,
                    start_date.isoformat(), num_days,
                    shared_categories=shared_categories,
                    shared_excluded=shared_excluded,
                    time_limit=per_limit, meal=LUNCH)
                by_meal = {LUNCH: lunch_blocks}

                if serve_dinner:
                    # Dinner is solved AFTER lunch and is handed lunch's dishes
                    # to avoid. Sequential rather than parallel for that reason:
                    # the exclusion is the whole mechanism, and it needs the
                    # first result to exist.
                    by_meal[DINNER] = _solve_counters(
                        client, selected_client, counter_names,
                        start_date.isoformat(), num_days,
                        shared_categories=shared_categories,
                        shared_excluded=shared_excluded,
                        time_limit=per_limit, meal=DINNER,
                        exclude_by_counter=_exclusions_from(lunch_blocks))[0]

            st.session_state.meal_blocks = by_meal
            st.session_state.active_meal = LUNCH
            st.session_state.plan_blocks = lunch_blocks
            st.session_state.rule_diagnostics = diags
            st.session_state.diagnostics_summary = summary
            # The header badge describes the PLAN, so a failure only sets it
            # when there is no plan at all. On a multi-counter client one
            # blocked counter is a warning inside its own tab, and hoisting it
            # to the page header would put a red "Pre-flight blocked" above
            # three tabs that each have a menu.
            failed = [b for b in lunch_blocks
                      if b.get("source") in ("error", "preflight_blocked")]
            st.session_state.plan_source = (
                failed[0]["source"]
                if failed and len(failed) == len(lunch_blocks)
                else "solver")
        st.rerun()

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
_meal_blocks = st.session_state.get("meal_blocks") or {}
_plan_mode = st.session_state.get("plan_mode", "single")

#: The services to render, in the order they are eaten. Dinner is a SECTION
#: BELOW lunch rather than a tab or a radio beside it: the two menus are for
#: the same dates and a kitchen reads them together, so putting one behind a
#: click means nobody compares them — which is the whole point of generating
#: the second one against the first.
_MEAL_LABELS = {LUNCH: "Lunch", DINNER: "Dinner"}
_meal_order = [m for m in (LUNCH, DINNER) if _meal_blocks.get(m)]

# `plan_blocks` is every meal's blocks CONCATENATED, lunch first, so a block
# index addresses one block across the whole page. That is what lets the
# regenerate and explain panels stay index-addressed and unchanged — and the
# dicts are the SAME objects `meal_blocks` holds, so a regenerate on the
# dinner section mutates the stored dinner rather than a copy.
_meal_offsets = {}
if _meal_order:
    _all, _meal_offsets = _concat_meal_blocks(_meal_order, _meal_blocks)
    st.session_state.plan_blocks = _all
_blocks = st.session_state.get("plan_blocks") or []

_render_diagnostics_expander(
    st.session_state.get("rule_diagnostics") or [],
    st.session_state.get("diagnostics_summary"),
)

# A failure short-circuits only when there is NOTHING to show. It used to test
# `_blocks[0]`, which is lunch's first block — so with two services a failed
# lunch stopped the page and took a perfectly good dinner down with it.
_nothing_planned = bool(_blocks) and not any(b.get("plan") for b in _blocks)
_first_bad = next(
    (b for b in _blocks
     if b.get("source") in ("preflight_blocked", "error")), None)

if _plan_mode != "multi" and _nothing_planned and _first_bad is not None:
    if _first_bad.get("source") == "preflight_blocked":
        st.warning(
            "Pre-flight diagnostics found a guaranteed failure for these "
            "dates. Fix the issues above (or change the dates / client) and "
            "try again.")
    else:
        # Falling through would render an empty table plus live Save /
        # Download buttons for a plan that does not exist.
        st.error(
            f"Generation failed: {_first_bad.get('error') or 'unknown error'}")
    st.stop()

if _blocks and any(b.get("plan") for b in _blocks):
    dates_union = sorted({d for b in _blocks for d in b.get("plan_dates", [])})
    total_items = sum(
        1 for b in _blocks for d in b.get("plan_dates", [])
        for s in b["plan"].get(d, {}) if b["plan"][d].get(s)
    )
    # Metric cards (Counters is always shown now).
    cards = [
        ("Client", html.escape(st.session_state.client_name or "")),
    ]
    _city = st.session_state.get("client_city")
    if _city:
        cards.append(("City", html.escape(_city)))
    # Counters is per SERVICE, not the length of the concatenated list — with
    # lunch and dinner on the page that would read "6 counters" for a
    # three-counter site. Services is shown only when there are two, so a
    # one-meal client's cards are exactly what they were.
    _counters_each = len(_meal_blocks[_meal_order[0]]) if _meal_order else len(_blocks)
    cards += [
        ("Counters", str(_counters_each)),
        ("Days", str(len(dates_union))),
    ]
    if len(_meal_order) > 1:
        cards.append(("Services", str(len(_meal_order))))
    if _plan_mode != "multi":
        b0 = _blocks[0]
        slots_per_day = len({s for d in b0["plan_dates"] for s in b0["plan"].get(d, {})})
        cards.append(("Slots per day", str(slots_per_day)))
    cards.append(("Total items", str(total_items)))
    st.markdown(
        '<div class="metrics-grid">' + ''.join(
            f'<div class="metric-card"><div class="metric-label">{lbl}</div>'
            f'<div class="metric-value">{val}</div></div>'
            for lbl, val in cards
        ) + '</div>', unsafe_allow_html=True)

    # --- Save / Download / Clear, once for the whole page ------------------
    # Shared across services on purpose: a save writes BOTH meals (they are
    # one day's cooking), and two Save buttons would invite saving half of it.
    sc1, sc2, sc3, _sc = st.columns([1.3, 1, 1, 3])
    _n_meals = len(_meal_order)
    with sc1:
        _save_label = ("Save All to History" if _plan_mode == "multi" or _n_meals > 1
                       else "Save to History")
        if st.button(_save_label, type="primary", key="plan_save_btn",
                     use_container_width=True):
            try:
                for _meal, _mb in _saveable_meals(_meal_blocks, _blocks):
                    payload = [{"name": b["name"], "week_plan": b["plan"]}
                               for b in _mb if b.get("plan")]
                    if not payload:
                        continue
                    if _plan_mode == "multi":
                        client.save(client_name=st.session_state.client_name,
                                    week_start=dates_union[0],
                                    counters=payload, meal=_meal)
                    else:
                        client.save(client_name=st.session_state.client_name,
                                    week_start=dates_union[0],
                                    week_plan=payload[0]["week_plan"],
                                    meal=_meal)
                    for b in _mb:
                        if b.get("plan"):
                            b["source"] = "history"
                st.session_state.plan_source = "history"
                st.toast(
                    f"Saved {_n_meals} service(s) to history"
                    if _n_meals > 1 else "Plan saved to history", icon="✅")
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Save failed: {e}")
    with sc2:
        # The export names its sheets after the block, so with two services a
        # counter would appear twice under one name. The meal is folded into
        # the name for the workbook only — the on-screen tab keeps the plain
        # counter name, since the section heading above it already says which
        # service it is.
        _xl_blocks = ([dict(b, name=f"{_MEAL_LABELS.get(b.get('meal'), '')} "
                                    f"{b['name']}".strip())
                       for b in _blocks] if _n_meals > 1 else _blocks)
        st.download_button(
            "Download Excel",
            data=plan_xlsx(_xl_blocks, st.session_state.client_name),
            file_name=download_filename(_blocks, st.session_state.client_name),
            mime=XLSX_MIME, key="plan_dl_btn", use_container_width=True)
    with sc3:
        if st.button("Clear All" if _n_meals > 1 or _plan_mode == "multi"
                     else "Clear", key="plan_clear_btn",
                     use_container_width=True):
            st.session_state.plan_blocks = []
            st.session_state.meal_blocks = {}
            st.session_state.changes_log = []
            st.session_state.plan_source = None
            st.session_state.rule_diagnostics = []
            st.session_state.diagnostics_summary = None
            st.rerun()

    # --- one section per service, lunch then dinner ------------------------
    for _meal in _meal_order:
        _mblocks = _meal_blocks[_meal]
        _offset = _meal_offsets[_meal]
        if _n_meals > 1:
            st.markdown(
                f'<p class="page-subtitle" style="margin-top:1.4rem;'
                f'font-size:1.05rem;font-weight:700">'
                f'{_MEAL_LABELS.get(_meal, str(_meal).title())}</p>',
                unsafe_allow_html=True)
            if _meal == DINNER:
                # How different dinner came out. Reported, never enforced: the
                # exclusion that produces it bans lunch's dishes outright and
                # overshoots the floor by a wide margin, so a CP-SAT bound
                # would be machinery for a condition that never binds. What is
                # worth having is the NUMBER — if a thin pool ever pushes the
                # two services back together, somebody sees it instead of the
                # guarantee quietly lapsing.
                _diff = meal_difference(
                    {d: v for b in (_meal_blocks.get(LUNCH) or [])
                     for d, v in (b.get("solution") or {}).items()},
                    {d: v for b in _mblocks
                     for d, v in (b.get("solution") or {}).items()})
                if _diff["per_day"]:
                    _pct = round(_diff["overall"] * 100)
                    if _diff["below_floor"]:
                        st.warning(
                            f"Dinner differs from lunch on {_pct}% of dishes, "
                            f"but {len(_diff['below_floor'])} day(s) fall "
                            f"below the {round(MIN_MEAL_DIFFERENCE * 100)}% "
                            "floor: " + ", ".join(_diff["below_floor"]))
                    else:
                        st.caption(
                            f"Dinner differs from lunch on {_pct}% of dishes.")

        if not any(b.get("plan") for b in _mblocks):
            # This service failed while another one has a menu — say so here
            # rather than taking the page down (see the short-circuit above).
            _why = next((b.get("error") for b in _mblocks if b.get("error")),
                        "no menu was produced")
            st.warning(f"&#9888; {_MEAL_LABELS.get(_meal, _meal)}: {_why}")
            continue

        if _plan_mode == "multi":
            _tabs = st.tabs([b["name"] for b in _mblocks])
            for i, (_tab, b) in enumerate(zip(_tabs, _mblocks)):
                with _tab:
                    if b.get("error") and not b.get("plan"):
                        st.warning(f"&#9888; {b['name']}: {b['error']}")
                        continue
                    _render_one_block(client, b, _offset + i, i,
                                      f"{_meal}_c{i}")
        else:
            _render_one_block(client, _mblocks[0], _offset, 0, f"{_meal}_single")

    _render_changes_log()

else:
    st.markdown("""<div class="empty-state">
        <div class="empty-icon">&#127835;</div>
        <h3>No menu plan yet</h3>
        <p>Select a client and click <b>Generate Menu Plan</b><br>in the sidebar to get started.</p>
    </div>""", unsafe_allow_html=True)
