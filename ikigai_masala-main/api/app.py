"""
Flask API Application for Menu Planning System.

Endpoints:
  POST /api/v1/plan — Generate a menu plan for a client
  POST /api/v1/regenerate — Regenerate selected cells
  POST /api/v1/save — Save plan to history
  GET  /api/v1/clients — List available clients
  GET  /api/v1/health — Health check
"""

import datetime as dt
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from flask import Flask, request, jsonify, g, has_request_context
from flask_cors import CORS

from api.concurrency import solver_gate, get_stats as _solver_stats
from api.auth import api_login, require_api_auth

from api.config import (
    DEFAULT_EXCEL_PATH, MENU_RULES_CONFIG_PATH,
    API_HOST, API_PORT, DEBUG, APP_VERSION,
    MIN_NUM_DAYS, MAX_NUM_DAYS, MIN_TIME_LIMIT_SECONDS, MAX_TIME_LIMIT_SECONDS,
    validate_required_env, today_in_app_tz,
)
from api.logging_config import (
    configure_logging,
    new_request_id,
    request_id_var,
)

# Install the logging config before anything else logs. Idempotent, so
# callers that also import us (Streamlit entry, tests) don't double-up.
configure_logging()

# Fail fast if required secrets / URLs are unset. The alternative is an
# opaque KeyError or Supabase auth error on the first request — which
# happens in production long after the process looked healthy.
validate_required_env()
from user_authentication.models import ROLE_ADMIN
from src.preprocessor import ExcelReader, DataCleanser
from src.preprocessor.pool_builder import PoolBuilder, _base_slot
from src.constants import BASE_SLOT_NAMES, CONST_SLOTS, REPEATABLE_ITEM_BASES
from src.client import ClientConfigLoader
from src.client.client_config import DEFAULT_THEME_MAP, AVAILABLE_THEMES  # noqa: used in editor-metadata
from src.history import HistoryManager
from src.menu_rules import MenuRuleLoader
from src.solver.menu_solver import MenuSolver, SolverConfig
from src.solver._helpers import (
    weekday_type_for_config as _weekday_type_cfg,
    strip_color_suffix,
    items_from_day as _items_from_day,
)
from src.solver.solution_formatter import SolutionFormatter
from src.solver.regenerator import MenuRegenerator

logger = logging.getLogger(__name__)

# Generic message returned to clients when the server hits an unexpected
# error. The real exception is logged server-side with exc_info; we must not
# echo exception details back to the caller, since Supabase errors and
# similar can reveal connection strings, internal hostnames, or schema info.
_INTERNAL_ERROR_MSG = "Internal server error"

# Record when the process started so /health can report uptime. Used
# for liveness / deploy-tracking rather than anything load-bearing.
_STARTED_AT = time.time()

app = Flask(__name__)

# CORS: default to loopback-only (the Streamlit frontend calls the API
# server-side via `requests`, so no browser origin needs access). Set
# CORS_ALLOWED_ORIGINS="https://prod.example.com,https://staging.example.com"
# to permit additional origins in production.
_cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
CORS(app, origins=_cors_origins)


# ---------------------------------------------------------------------------
# Request tracing — one access log line per request with timing + user.
# ---------------------------------------------------------------------------

@app.before_request
def _trace_request_start() -> None:
    # Prefer a caller-supplied X-Request-ID so traces can be correlated
    # across services; otherwise mint our own.
    rid = request.headers.get("X-Request-ID", "").strip() or new_request_id()
    g.request_id = rid
    # Every request's before_request overwrites the ContextVar, so
    # thread-pool reuse can't leak an id from the previous request.
    request_id_var.set(rid)
    g._t0 = time.perf_counter()


@app.after_request
def _trace_request_end(response):
    t0 = getattr(g, "_t0", None)
    duration_ms = (
        int((time.perf_counter() - t0) * 1000) if t0 is not None else None
    )
    rid = getattr(g, "request_id", "-")
    response.headers["X-Request-ID"] = rid

    # Principal email is populated by require_api_auth via g.api_user
    # when auth passes; None for /health, /, and /auth/login.
    api_user = getattr(g, "api_user", None)
    user_email = (api_user or {}).get("email")

    # /health gets spammy fast — skip its access log unless it errored.
    if request.path == "/api/v1/health" and response.status_code < 400:
        return response

    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "user": user_email,
            "remote_addr": request.remote_addr,
        },
    )
    return response


@app.teardown_request
def _trace_request_teardown(_exc):
    # Return the ContextVar to its sentinel so log records emitted
    # after this request finishes (e.g. background cleanup, the next
    # test in a pytest session) don't inherit a stale request id.
    # Using set() rather than reset() because tokens are single-use
    # and the after_request path may have already released it.
    request_id_var.set("-")


# Thread-safe lazy singletons
_init_lock = threading.Lock()
_client_loader = None
_pools = None
_df = None
_menu_rules = None


def _get_client_loader():
    global _client_loader
    if _client_loader is None:
        with _init_lock:
            if _client_loader is None:
                _client_loader = ClientConfigLoader()
    return _client_loader


def _get_menu_data():
    global _pools, _df
    if _pools is None:
        with _init_lock:
            if _pools is None:
                reader = ExcelReader(DEFAULT_EXCEL_PATH)
                raw_df = reader.read()
                cleanser = DataCleanser(raw_df)
                _df = cleanser.clean()
                _pools = PoolBuilder.build_pools(_df)
    return _df, _pools


def _get_menu_rules():
    global _menu_rules
    if _menu_rules is None:
        with _init_lock:
            if _menu_rules is None:
                loader = MenuRuleLoader(MENU_RULES_CONFIG_PATH)
                _menu_rules = loader.load_from_file()
    return _menu_rules


def _rules_and_skip_for_client(client_name, dates):
    """Return (rules, skip_cells) for a client, merging generic + per-client."""
    generic = _get_menu_rules()
    loader = MenuRuleLoader()
    rules = loader.load_for_client(client_name, generic)
    skip_cells = set()
    for rule in rules:
        if hasattr(rule, 'compute_skip_cells'):
            skip_cells |= rule.compute_skip_cells(dates)
    return rules, skip_cells


# Longest backward window any HistoryManager consumer looks at
# (week-signature cooldown is 30d, item cooldown 20d, rice-bread gap 10d).
# A few extra days of slack lets small schema changes to those defaults
# land without needing this constant to track them exactly.
_HISTORY_WINDOW_DAYS = 45


def _build_history_context(df, client_name, start_date, weekday_dates):
    """Shared helper to build history-based solver inputs from Supabase.

    Pushes ``client_name`` and ``service_date >= cutoff`` filters down to
    Supabase so the query hits the ``(client_name, service_date DESC)``
    index on ``menu_history`` (and the analogous index on
    ``week_signatures``) instead of scanning every row for every tenant.
    """
    import pandas as pd
    from src.db import get_supabase

    earliest = start_date - dt.timedelta(days=_HISTORY_WINDOW_DAYS)
    earliest_iso = earliest.isoformat()

    hm = HistoryManager()
    sb = get_supabase()
    long_resp = (
        sb.table('menu_history')
        .select('*')
        .eq('client_name', client_name)
        .gte('service_date', earliest_iso)
        .execute()
    )
    weeks_resp = (
        sb.table('week_signatures')
        .select('*')
        .eq('client_name', client_name)
        .gte('week_start', earliest_iso)
        .execute()
    )
    long_df = pd.DataFrame(long_resp.data) if long_resp.data else None
    weeks_df = pd.DataFrame(weeks_resp.data) if weeks_resp.data else None
    hm.load_from_dataframes(long_df, weeks_df)
    # Rows are already scoped to this client at the DB layer, but leave
    # the in-memory filter in place as belt-and-suspenders for anyone
    # who seeds the manager from an unfiltered DataFrame.
    hm = hm.filter_by_client(client_name)

    banned = hm.banned_items_by_date(weekday_dates, const_slots=CONST_SLOTS,
                                      repeatable_items=REPEATABLE_ITEM_BASES)
    ricebread_items = set(
        df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
    ) if 'is_rice_bread' in df.columns else set()
    rb_ban = hm.ricebread_ban_by_date(weekday_dates, ricebread_items)
    recent_sigs = hm.recent_week_signatures(start_date)
    return banned, rb_ban, recent_sigs


def _cached_on_g(key: str, compute):
    """Memoize ``compute()`` on Flask's ``g`` for the current request.

    ClientConfigLoader properties read Supabase on every access (no
    in-process cache, so admin edits are picked up immediately). Some of
    them — client_names, menu_categories — end up fetched multiple
    times per request: once from _require_known_client, once from the
    endpoint body, once from editor-metadata etc. Caching on ``g`` keeps
    the "live reads across requests" guarantee while collapsing the
    intra-request round trips.

    Outside a request context (module-import paths, bare scripts) there
    is no ``g`` to hang on to, so we just call compute() uncached.
    """
    if not has_request_context():
        return compute()
    cache = getattr(g, '_clientcfg_cache', None)
    if cache is None:
        cache = {}
        g._clientcfg_cache = cache
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def _request_client_names():
    return _cached_on_g(
        'client_names',
        lambda: _get_client_loader().client_names,
    )


def _request_menu_categories():
    return _cached_on_g(
        'menu_categories',
        lambda: _get_client_loader().menu_categories,
    )


def _require_known_client(client_name):
    """Validate ``client_name`` is non-empty and refers to a known client.

    Raises ``ValueError`` with a user-safe message so the caller's 400
    handler picks it up. Keeps invalid input from reaching solver setup
    or Supabase config reads, where it would surface as a less-clear
    error deep in the stack.
    """
    if not client_name or not isinstance(client_name, str):
        raise ValueError('client_name is required')
    if client_name not in _request_client_names():
        raise ValueError(f"Unknown client: {client_name}")


def _weekdays_from(start_date, num_days):
    """Return up to num_days weekday dates (skip Sat/Sun) starting from start_date."""
    dates = []
    d = start_date
    while len(dates) < num_days:
        if d.weekday() < 5:  # Mon-Fri
            dates.append(d)
        d += dt.timedelta(days=1)
    return dates


def _client_base_slots(client_cfg):
    """Return unique base slot names the client uses (excluding constants).

    Handles expanded slot IDs like veg_dry__1, veg_dry__2 by extracting
    the base name so the solver gets ['veg_dry'] not ['veg_dry__1', 'veg_dry__2'].
    """
    seen = set()
    result = []
    for s in client_cfg.active_slots:
        if s in CONST_SLOTS:
            continue
        base = _base_slot(s)
        if base not in seen:
            seen.add(base)
            result.append(base)
    return result


def _build_solver_config(df, client_cfg, start_date, num_days, time_limit, weekday_dates):
    """Shared helper to build SolverConfig."""
    active_base = _client_base_slots(client_cfg)
    return SolverConfig(
        days=num_days,
        start_date=start_date,
        time_limit_sec=time_limit,
        slot_counts=client_cfg.slot_counts,
        active_base_slots=active_base or None,
        explicit_dates=weekday_dates,
        premium_flag_col='is_premium_veg' if 'is_premium_veg' in df.columns and int(df['is_premium_veg'].sum()) > 0 else None,
        theme_map=client_cfg.theme_map or None,
    )


@dataclass
class SolverInputs:
    """Bundle of everything MenuSolver / MenuRegenerator need for one request."""
    client_name: str
    client_cfg: Any
    df: Any
    pools: Dict[str, Any]
    start_date: dt.date
    num_days: int
    time_limit: int
    weekday_dates: List[dt.date]
    rules: List[Any]
    skip_cells: Set[Any]
    banned: Dict[Any, Any]
    rb_ban: Dict[Any, Any]
    recent_sigs: List[Any]
    cfg: SolverConfig


def _prepare_solver_inputs(data: Dict[str, Any]) -> SolverInputs:
    """Parse request body and assemble all inputs the solver/regenerator need.

    Raises ``ValueError`` with a user-facing message on missing/invalid input.
    """
    client_name = data.get('client_name')
    _require_known_client(client_name)

    start_date_str = data.get('start_date')
    num_days = max(MIN_NUM_DAYS, min(MAX_NUM_DAYS, int(data.get('num_days', 5))))
    time_limit = max(
        MIN_TIME_LIMIT_SECONDS,
        min(MAX_TIME_LIMIT_SECONDS, int(data.get('time_limit_seconds', 240))),
    )

    client_cfg = _get_client_loader().get_client(client_name)
    df, pools = _get_menu_data()
    start_date = dt.date.fromisoformat(start_date_str) if start_date_str else today_in_app_tz()
    weekday_dates = _weekdays_from(start_date, num_days)
    rules, skip_cells = _rules_and_skip_for_client(client_name, weekday_dates)
    banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, weekday_dates)
    cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit, weekday_dates)

    return SolverInputs(
        client_name=client_name,
        client_cfg=client_cfg,
        df=df,
        pools=pools,
        start_date=start_date,
        num_days=num_days,
        time_limit=time_limit,
        weekday_dates=weekday_dates,
        rules=rules,
        skip_cells=skip_cells,
        banned=banned,
        rb_ban=rb_ban,
        recent_sigs=recent_sigs,
        cfg=cfg,
    )


def _validate_pools(pools, solver_config, menu_rules, dates, skip_cells=None):
    """Check pool sizes after theme filtering vs required slot counts.

    Returns a list of warning strings for any (day, slot) where the filtered
    pool is smaller than needed.  An empty list means no issues detected.
    """
    warnings = []
    base_slots = solver_config.active_base_slots or list(BASE_SLOT_NAMES)
    slot_counts = solver_config.slot_counts or {s: 1 for s in base_slots}

    filter_ctx_base = {
        'cfg': solver_config,
        'banned_by_date': {},
        'ricebread_ban_day': {},
        'pools': pools,
    }

    for d in dates:
        day_type = _weekday_type_cfg(d, solver_config.theme_map)
        for base in base_slots:
            if skip_cells and (d, base) in skip_cells:
                continue
            if base not in pools:
                continue
            pool = pools[base].copy()

            # Exclude steamed rice etc.
            if base in ('rice', 'healthy_rice') and len(pool) > 0:
                pool = pool[~pool['item'].isin(solver_config.rice_exclude_items)]

            # Apply rule pre-filters (theme slot filters, etc.)
            ctx = {**filter_ctx_base, 'slot_num': None}
            for rule in menu_rules:
                pool = rule.pre_filter_pool(pool, d, base, day_type, ctx)

            count_needed = slot_counts.get(base, 1)
            pool_size = len(pool)
            if pool_size < count_needed:
                day_label = d.strftime('%A %d %b')
                warnings.append(
                    f"{day_type.capitalize()} {day_label}: "
                    f"only {pool_size} {base.replace('_', ' ')} item{'s' if pool_size != 1 else ''} "
                    f"available, need {count_needed}"
                )
            elif pool_size == count_needed:
                day_label = d.strftime('%A %d %b')
                warnings.append(
                    f"{day_type.capitalize()} {day_label}: "
                    f"exactly {pool_size} {base.replace('_', ' ')} item{'s' if pool_size != 1 else ''} "
                    f"available for {count_needed} needed (no variety)"
                )
    return warnings


app.add_url_rule('/api/v1/auth/login', 'api_login', api_login, methods=['POST'])


@app.route('/api/v1/clients', methods=['GET'])
@require_api_auth()
def list_clients():
    try:
        return jsonify({'success': True, 'clients': _request_client_names()})
    except (FileNotFoundError, ValueError, KeyError) as e:
        logger.error("Failed to list clients: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/plan', methods=['POST'])
@require_api_auth()
@solver_gate
def plan_menu():
    try:
        inputs = _prepare_solver_inputs(request.get_json() or {})

        pool_warnings = _validate_pools(
            inputs.pools, inputs.cfg, inputs.rules,
            inputs.weekday_dates, skip_cells=inputs.skip_cells,
        )

        solver = MenuSolver(
            pools=inputs.pools,
            solver_config=inputs.cfg,
            menu_rules=inputs.rules,
            banned_by_date=inputs.banned,
            ricebread_ban_day=inputs.rb_ban,
            recent_sigs=inputs.recent_sigs,
            skip_cells=inputs.skip_cells,
        )

        week_plan, plan_dates = solver.solve()

        formatter = SolutionFormatter(
            week_plan, plan_dates, theme_map=inputs.client_cfg.theme_map or None,
        )
        response = {
            'success': True,
            'message': f'Menu plan generated for {inputs.client_name}',
            'solution': formatter.to_dict(),
        }
        if pool_warnings:
            response['pool_warnings'] = pool_warnings
        if solver.rule_failures:
            response['rule_warnings'] = solver.rule_failures
        return jsonify(response)

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Solver failed: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500
    except Exception as e:
        logger.error("Unexpected error in plan: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/regenerate', methods=['POST'])
@require_api_auth()
@solver_gate
def regenerate_cells():
    try:
        data = request.get_json() or {}
        base_plan_raw = data.get('base_plan', {})
        replace_slots_raw = data.get('replace_slots', {})
        if not base_plan_raw:
            return jsonify({'success': False, 'error': 'base_plan is required'}), 400
        if not replace_slots_raw:
            return jsonify({'success': False, 'error': 'replace_slots is required'}), 400

        inputs = _prepare_solver_inputs(data)

        base_plan = {
            dt.date.fromisoformat(d_str): _items_from_day(slots)
            for d_str, slots in base_plan_raw.items()
        }
        replace_mask = {
            dt.date.fromisoformat(d_str): set(slot_list)
            for d_str, slot_list in replace_slots_raw.items()
        }

        regen = MenuRegenerator(
            pools=inputs.pools,
            df=inputs.df,
            solver_config=inputs.cfg,
            menu_rules=inputs.rules,
            banned_by_date=inputs.banned,
            ricebread_ban_day=inputs.rb_ban,
            recent_sigs=inputs.recent_sigs,
            skip_cells=inputs.skip_cells,
        )

        week_plan, plan_dates = regen.regenerate(base_plan, replace_mask)

        formatter = SolutionFormatter(
            week_plan, plan_dates, theme_map=inputs.client_cfg.theme_map or None,
        )
        response = {
            'success': True,
            'message': f'Regenerated {sum(len(v) for v in replace_mask.values())} cells for {inputs.client_name}',
            'solution': formatter.to_dict(),
        }
        if regen.rule_failures:
            response['rule_warnings'] = regen.rule_failures
        return jsonify(response)

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Regeneration failed: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500
    except Exception as e:
        logger.error("Unexpected error in regenerate: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/save', methods=['POST'])
@require_api_auth()
def save_plan():
    try:
        data = request.get_json(silent=True) or {}
        client_name = data.get('client_name')
        week_plan_raw = data.get('week_plan', {})
        week_start_str = data.get('week_start')

        _require_known_client(client_name)
        if not week_plan_raw:
            return jsonify({'success': False, 'error': 'week_plan is required'}), 400
        if not week_start_str:
            return jsonify({'success': False, 'error': 'week_start is required'}), 400

        # Convert string date keys to date objects, extracting items from solution format
        week_plan = {
            dt.date.fromisoformat(d_str): _items_from_day(day_data)
            for d_str, day_data in week_plan_raw.items()
        }

        dates = sorted(week_plan.keys())
        week_start = dt.date.fromisoformat(week_start_str)

        sig = HistoryManager.compute_week_signature(
            week_plan, dates, const_slots=CONST_SLOTS,
            strip_color_fn=strip_color_suffix,
        )

        hm = HistoryManager()
        # Get Supabase client for persistent storage
        from src.db import get_supabase
        sb = get_supabase()
        hm.save(week_plan, dates, client_name, week_start, sig,
                supabase_client=sb,
                strip_color_fn=strip_color_suffix)

        return jsonify({'success': True, 'message': 'Plan saved to history'})

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except (FileNotFoundError, OSError) as e:
        logger.error("Save failed: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500
    except Exception as e:
        logger.error("Unexpected save error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/editor-metadata', methods=['GET'])
@require_api_auth()
def editor_metadata():
    """Return metadata needed by the customisation editor UI."""
    try:
        return jsonify({
            'success': True,
            'base_slot_names': list(BASE_SLOT_NAMES),
            'const_slots': list(CONST_SLOTS),
            'default_theme_map': DEFAULT_THEME_MAP,
            'available_themes': AVAILABLE_THEMES,
            'clients': _request_client_names(),
            'menu_categories': _request_menu_categories(),
        })
    except Exception as e:
        logger.error("Failed to load editor metadata: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/client-config/<client_name>', methods=['GET'])
@require_api_auth()
def get_client_config(client_name):
    """Return the full editable config for one client."""
    try:
        loader = _get_client_loader()
        base_slots = loader.get_active_slots_for_client(client_name)
        menu_category = loader.get_client_menu_category(client_name)
        cfg = loader.get_client(client_name)
        return jsonify({
            'success': True,
            'name': cfg.name,
            'menu_category': menu_category,
            'active_base_slots': [s for s in base_slots if s not in CONST_SLOTS],
            'slot_counts': cfg.slot_counts,
            'theme_map': cfg.theme_map,
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Failed to load client config: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/client-config/<client_name>', methods=['PUT'])
@require_api_auth(min_role=ROLE_ADMIN)
def update_client_config(client_name):
    """Update a client's configuration (slots, slot counts, theme overrides)."""
    try:
        data = request.get_json(silent=True) or {}
        loader = _get_client_loader()

        if 'active_base_slots' in data:
            loader.update_client_slots(client_name, data['active_base_slots'])
        if 'slot_counts' in data:
            loader.update_client_slot_counts(client_name, data['slot_counts'])
        if 'theme_map' in data:
            loader.update_client_theme_overrides(client_name, data['theme_map'])

        # No reload needed — Supabase reads are always live
        return jsonify({'success': True, 'message': f'Config updated for {client_name}'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Error updating client config: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/client', methods=['POST'])
@require_api_auth(min_role=ROLE_ADMIN)
def create_client():
    """Create a new client."""
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name', '').strip()
        active_slots = data.get('active_slots', list(BASE_SLOT_NAMES))
        if not name:
            return jsonify({'success': False, 'error': 'name is required'}), 400

        loader = _get_client_loader()
        loader.create_client(name, active_slots)

        return jsonify({'success': True, 'message': f'Client {name} created'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to create client: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/client/<client_name>', methods=['DELETE'])
@require_api_auth(min_role=ROLE_ADMIN)
def delete_client(client_name):
    """Delete a client."""
    try:
        loader = _get_client_loader()
        loader.delete_client(client_name)

        # No reload needed — Supabase reads are always live
        return jsonify({'success': True, 'message': f'Client {client_name} deleted'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Failed to delete client: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


@app.route('/api/v1/validate-pools', methods=['POST'])
@require_api_auth()
def validate_pools():
    """Check pool sizes after theme filtering — returns warnings without running solver."""
    try:
        data = request.get_json(silent=True) or {}
        client_name = data.get('client_name')
        start_date_str = data.get('start_date')
        num_days = max(MIN_NUM_DAYS, min(MAX_NUM_DAYS, int(data.get('num_days', 5))))

        _require_known_client(client_name)

        loader = _get_client_loader()
        client_cfg = loader.get_client(client_name)
        df, pools = _get_menu_data()
        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else today_in_app_tz()
        weekday_dates = _weekdays_from(start_date, num_days)
        rules, skip_cells = _rules_and_skip_for_client(client_name, weekday_dates)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, 180, weekday_dates)

        warnings = _validate_pools(pools, cfg, rules, weekday_dates, skip_cells=skip_cells)
        return jsonify({'success': True, 'warnings': warnings})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to validate pools: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': _INTERNAL_ERROR_MSG}), 500


def _probe_supabase() -> bool:
    """Cheap reachability check: fetch one row from `clients`. Any
    exception (network, auth, RLS) counts as unreachable.
    """
    try:
        from src.db import get_supabase
        get_supabase().table('clients').select('name').limit(1).execute()
        return True
    except Exception as exc:  # noqa: BLE001 — degraded state is fine
        logger.warning("Supabase health probe failed: %s", exc)
        return False


@app.route('/api/v1/health', methods=['GET'])
def health():
    """Liveness + readiness combined.

    Returns 200 with status=healthy when everything is up, 503 with
    status=degraded when Supabase is unreachable. Either way the body
    carries enough to diagnose: version, uptime, queue stats, and the
    supabase flag. Uptime monitors that only match on 200 will (correctly)
    start paging on degraded.
    """
    supabase_up = _probe_supabase()
    body = {
        'status': 'healthy' if supabase_up else 'degraded',
        'version': APP_VERSION,
        'uptime_seconds': int(time.time() - _STARTED_AT),
        'supabase_reachable': supabase_up,
        'queue': _solver_stats(),
    }
    return jsonify(body), (200 if supabase_up else 503)


@app.route('/')
def root():
    return jsonify({
        'name': 'Ikigai Masala Menu Planning API',
        'version': APP_VERSION,
        'docs': '/api/v1/clients',
    })


if __name__ == '__main__':
    # Logging was already configured at module import.
    app.run(host=API_HOST, port=API_PORT, debug=DEBUG)
