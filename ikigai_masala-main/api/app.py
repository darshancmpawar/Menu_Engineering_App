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
import functools
import hmac
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional, Set

from flask import Flask, request, jsonify, g, has_request_context
from flask_cors import CORS

from api.concurrency import solver_gate, get_worker_count, get_stats as _solver_stats
from src.ontology.paths import pool_tokens_for_city
from src.ontology import repository as ontology_repository
from src.application.constant_items import _canonical_item_name
from src.application.horizon import (
    _filter_dates_by_working_days, _weekdays_from)
from src.application.presentation import _enrich_history_plan
from src.application.solve_inputs import (
    prepare_solver_inputs, run_preflight, span_dates,
)
from api.rate_limit import rate_limit
from api import metrics

from api.config import (
    API_WRITE_TOKEN,
    MAX_CONTENT_LENGTH_BYTES,
    API_HOST, API_PORT, DEBUG, APP_VERSION,
    MIN_NUM_DAYS, MAX_NUM_DAYS, MIN_TIME_LIMIT_SECONDS, MAX_TIME_LIMIT_SECONDS,
    MAX_ALTERNATES, validate_required_env, today_in_app_tz,
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
from src.preprocessor.client_pool_filter import (
    get_active_pools, available_pool_tokens, normalize_name,
)
from src.constants import (
    BASE_SLOT_NAMES, CONST_SLOTS, DEFAULT_OFF_SLOTS,
)
from src.client import ClientConfigLoader
from src.client.client_config import normalize_city
from src.client.client_config import (  # noqa: F401 — surfaced in editor-metadata response
    DEFAULT_THEME_MAP,
    AVAILABLE_THEMES,
    AVAILABLE_CITIES,
    DEFAULT_ITEM_COOLDOWN_DAYS,
    MAX_COUNTERS,
)
from src.history import (HistoryManager, normalize_meal, normalize_meals,
                         DEFAULT_MEAL, DEFAULT_MEALS)
from src.menu_rules import MenuRuleLoader
from src.menu_rules import (
    has_blocking_errors,
    pool_warnings_projection,
)
from src.menu_rules.relaxations import RelaxationCapture
from src.explain.evidence import (
    attach_relaxations, attrs_from_dataframe, build_plan_evidence,
)
from src.explain.renderer import day_overview
from api.explain_llm import explain_plan
from src.solver.menu_solver import MenuSolver
from src.solver._helpers import (
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


def _internal_error_response(status: int = 500):
    """Return a generic-error JSON response with the current request_id.

    The body never carries exception details (security), but it does
    surface the request_id so an admin debugging "Internal server error"
    in the UI can grep that id in the access log and find the real
    traceback. Fix for the recurring "I see Internal server error and
    have no way to triage" pain.
    """
    rid = getattr(g, 'request_id', None) if has_request_context() else None
    body = {'success': False, 'error': _INTERNAL_ERROR_MSG}
    if rid:
        body['request_id'] = rid
    return jsonify(body), status

# Record when the process started so /health can report uptime. Used
# for liveness / deploy-tracking rather than anything load-bearing.
_STARTED_AT = time.time()

app = Flask(__name__)

# Reject oversized bodies before they are parsed (see MAX_CONTENT_LENGTH_BYTES).
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH_BYTES


def _too_large_response():
    return jsonify({
        'success': False,
        'error': (
            f'Request body exceeds the {MAX_CONTENT_LENGTH_BYTES} byte limit.'
        ),
    }), 413


@app.errorhandler(413)
def _payload_too_large(_exc):
    return _too_large_response()


@app.before_request
def _reject_oversized_body():
    """Reject an over-limit body before the view runs.

    ``MAX_CONTENT_LENGTH`` alone is not enough here: Werkzeug raises
    ``RequestEntityTooLarge`` lazily, when the view first reads the stream — and
    every endpoint wraps its body in a broad ``except Exception`` that catches
    it and returns a misleading 500 instead of 413. Checking the declared
    Content-Length up front keeps the status honest regardless of the handler.
    """
    limit = app.config.get('MAX_CONTENT_LENGTH')
    if limit and (request.content_length or 0) > limit:
        return _too_large_response()
    return None


def require_write_token(fn):
    """Gate a mutating endpoint on the optional shared secret.

    A no-op when ``API_WRITE_TOKEN`` is unset, which is the shipped default, so
    this changes nothing for a deployment that relies on the network perimeter.
    When it *is* set, a write without the matching token gets 401 — the cheapest
    thing that stops an exposed port from being writable by anyone.

    This is not a substitute for real per-user auth; it is the minimum that
    makes "the port leaked" survivable. The rate-limit principal hook
    (api.rate_limit._principal_key) is where a future identity would slot in.
    """
    @functools.wraps(fn)
    def _inner(*args, **kwargs):
        if not API_WRITE_TOKEN:
            return fn(*args, **kwargs)
        supplied = request.headers.get('X-API-Key', '').strip()
        if not supplied:
            auth = request.headers.get('Authorization', '').strip()
            if auth.lower().startswith('bearer '):
                supplied = auth[7:].strip()
        if not hmac.compare_digest(supplied, API_WRITE_TOKEN):
            metrics.incr('write_auth_rejected_total')
            return jsonify({
                'success': False,
                'error': (
                    'This endpoint requires a write token. Send it as '
                    'X-API-Key or Authorization: Bearer <token>.'
                ),
            }), 401
        return fn(*args, **kwargs)
    return _inner

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

# The ontology caches used to be four module-level dicts right here. They now
# live in src/ontology/repository.py — loading a workbook and building slot pools
# is not an HTTP concern, and as module globals they forced every integration
# test to reset four private attributes by name (54 places across 18 files) to
# get isolation. `reset_caches()` below is the one call that replaced that.


def reset_caches() -> None:
    """Drop every cached ontology, pool set and ruleset.

    The supported way for a test to isolate itself, and the hook for picking up
    an edited workbook without a restart. Prefer this over touching private
    attributes: it cannot go stale when a cache is added.
    """
    ontology_repository.reset()


def _get_client_loader():
    global _client_loader
    if _client_loader is None:
        with _init_lock:
            if _client_loader is None:
                _client_loader = ClientConfigLoader()
    return _client_loader


def _get_menu_data(city=None):
    """``(df, pools)`` for *city*'s ontology — see OntologyRepository.menu_data."""
    return ontology_repository.menu_data(city)


def _menu_data_for_client(client_name, city=None):
    """``(df, pools)`` for a client, with F5 client-pool filtering applied.

    Reads the client row here and hands `city` + `source_pools` to the
    repository, rather than letting the ontology layer query Supabase itself.
    One row read either way: the two values are columns of the same row, so
    separate helpers would double the round trips on a path that runs per plan.
    """
    row = (
        _client_row(client_name) if has_request_context()
        else _get_client_loader().get_client_row(client_name)
    )
    if city is None:
        city = row['city']
    return ontology_repository.filtered_menu_data(city, row['source_pools'])


def _get_nonveg_items(city=None):
    """Lowercased non-veg item names for *city* — used to render dishes red."""
    return ontology_repository.nonveg_items(city)


def _get_menu_rules_for_city(city):
    """Cached base ruleset for *city* (resolves the extends chain)."""
    return ontology_repository.rules_for_city(city)


def _prepare_solver_inputs(data, client_cfg=None):
    """Parse the request, then hand the assembly to the application layer.

    Everything this function does is HTTP: validating the client name,
    clamping `num_days` and the time limit to the API's bounds, defaulting
    `start_date` to the app timezone's today, and reading the client row once
    per request (memoised on `g`). Assembling the solve itself is domain work
    and lives in `src/application/solve_inputs.py`.

    Kept as a wrapper rather than pushed out to the five call sites: one place
    owning request parsing is the point of the split, and threading six
    keyword arguments through each endpoint would put it back.
    """
    client_name = data.get('client_name')
    _require_known_client(client_name)
    row = _client_row(client_name)
    if client_cfg is None:
        client_cfg = _get_client_loader().get_client_configs_from_row(
            client_name, row,
        )[0][1]
    start_date_str = data.get('start_date')
    return prepare_solver_inputs(
        data, client_cfg,
        client_name=client_name,
        row=row,
        start_date=(dt.date.fromisoformat(start_date_str) if start_date_str
                    else today_in_app_tz()),
        num_days=max(MIN_NUM_DAYS,
                     min(MAX_NUM_DAYS, int(data.get('num_days', 5)))),
        time_limit=max(MIN_TIME_LIMIT_SECONDS,
                       min(MAX_TIME_LIMIT_SECONDS,
                           int(data.get('time_limit_seconds', 240)))),
        # The one injected dependency: worker count is a web concern (how many
        # solves this process is serving), so the domain takes it as a callable
        # rather than importing `api.concurrency`.
        worker_count=get_worker_count,
    )


















# Floor lookback. Must cover every history-consuming rule's cooldown.
# With the default rules (week-signature 30d, item cooldown 20d,
# rice-bread gap 10d), 45d gives 15d of slack. For per-client overrides
# that push cooldowns past this floor, _effective_history_window()
# widens the window at runtime instead of silently cutting off data.
_HISTORY_WINDOW_DAYS = 45
_HISTORY_WINDOW_SLACK_DAYS = 15






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


def _client_row(client_name):
    """All of a client's config columns, read once per request.

    ``ClientConfigLoader`` intentionally has no cross-request cache so admin
    edits are live. That is fine, but the per-field getters each issued their
    own query, so one /plan cost six round trips against the same row. This
    keeps reads live while collapsing them to one per request.
    """
    return _cached_on_g(
        f'client_row:{client_name}',
        lambda: _get_client_loader().get_client_row(client_name),
    )


def _request_client_names():
    return _cached_on_g(
        'client_names',
        lambda: _get_client_loader().client_names,
    )


def _count_rule_failures(failures) -> None:
    """Bump ``rule_failures_total{rule=<name>}`` for every failure the
    solver recorded on this request. Keeps the metrics surface aligned
    with the response's ``rule_warnings`` payload so a Prometheus alert
    on rule_failures_total doesn't disagree with what the client saw.
    """
    if not failures:
        return
    for entry in failures:
        rule_name = entry.get('rule', 'unknown') if isinstance(entry, dict) else 'unknown'
        metrics.incr('rule_failures_total', rule=rule_name)


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




















def _resolve_counter(client_name: str, data: Dict[str, Any]):
    """Return ``(counter_index, counter_name, counter_count, client_cfg)`` for
    the requested counter. ``counter_index`` defaults to 0 (primary). Raises
    ValueError for an out-of-range index."""
    row = _client_row(client_name)
    configs = _get_client_loader().get_client_configs_from_row(client_name, row)
    counter_count = len(configs)
    try:
        idx = int(data.get('counter_index', 0) or 0)
    except (TypeError, ValueError):
        idx = 0
    if idx < 0 or idx >= counter_count:
        raise ValueError(
            f"counter_index {idx} out of range (client has {counter_count} counter"
            f"{'s' if counter_count != 1 else ''})"
        )
    name, cfg = configs[idx]
    return idx, name, counter_count, cfg












def _record_diag_metrics(diagnostics) -> None:
    """Bump ``rule_diagnostics_total{rule=<name>,severity=<sev>}`` once
    per emitted Diagnostic. Mirrors ``_count_rule_failures`` so a
    Prometheus alert can fire on either surface symmetrically.
    """
    for d in diagnostics:
        metrics.incr(
            'rule_diagnostics_total',
            rule=d.rule,
            severity=d.severity.value,
        )


@app.route('/api/v1/clients', methods=['GET'])
def list_clients():
    try:
        detail = _get_client_loader().list_clients_with_city()
        return jsonify({
            'success': True,
            # names only — backward-compatible with existing callers
            'clients': [c['name'] for c in detail],
            # {name, city} for city-aware pickers
            'clients_detail': detail,
        })
    except (FileNotFoundError, ValueError, KeyError) as e:
        logger.error("Failed to list clients: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/plan', methods=['POST'])
@rate_limit("plan")
@solver_gate
def plan_menu():
    # Pre-flight results, kept out of the try so the 500 handler can attach them
    # even when the solve fails. A counter that passes pre-flight and then goes
    # INFEASIBLE used to answer with a bare sentence naming no rule, which is the
    # hardest failure to act on — the non-blocking warnings are usually the clue.
    diag_dicts: list = []
    summary = None
    try:
        data = request.get_json() or {}
        _require_known_client(data.get('client_name'))
        counter_index, counter_name, counter_count, client_cfg = _resolve_counter(
            data.get('client_name'), data,
        )
        inputs = _prepare_solver_inputs(data, client_cfg=client_cfg)

        # Pre-flight gate: run every rule's diagnose() against the
        # assembled inputs. If any diagnostic is severity=error, the
        # solver would (with overwhelming probability) fail — so we
        # short-circuit with 422 and the structured diagnostics
        # before spending solver budget.
        diagnostics, summary = run_preflight(inputs)
        _record_diag_metrics(diagnostics)
        diag_dicts = [d.to_dict() for d in diagnostics]
        # Denormalised pool_warnings projection kept for one release so
        # older Streamlit builds that still read this key keep rendering
        # something. New code consumes ``rule_diagnostics``.
        pool_warnings = pool_warnings_projection(diagnostics)

        if has_blocking_errors(diagnostics):
            metrics.incr('plan_requests_total', outcome='preflight_blocked')
            body = {
                'success': False,
                'error': 'rule_diagnostics_blocked',
                'message': (
                    f"Pre-flight diagnostics found "
                    f"{summary['errors']} blocking issue"
                    f"{'s' if summary['errors'] != 1 else ''} for "
                    f"{inputs.client_name}; solver skipped."
                ),
                'rule_diagnostics': diag_dicts,
                'summary': summary,
            }
            if pool_warnings:
                body['pool_warnings'] = pool_warnings
            return jsonify(body), 422

        solver = MenuSolver(
            pools=inputs.pools,
            solver_config=inputs.cfg,
            menu_rules=inputs.rules,
            banned_by_date=inputs.banned,
            ricebread_ban_day=inputs.rb_ban,
            recent_sigs=inputs.recent_sigs,
            skip_cells=inputs.skip_cells,
            recency_by_item=inputs.recency_by_item,
        )

        # Optional ranked alternates: closest-to-ideal distinct menus, not
        # random diversification. Clamped so a caller can't ask the solver to
        # enumerate an unbounded number of near-optimal menus.
        n_alt = max(0, min(int(data.get('alternates', 0) or 0), MAX_ALTERNATES))
        nonveg_items = _get_nonveg_items(inputs.city)

        def _format(plan):
            return SolutionFormatter(
                plan, span_dates(plan_dates, inputs),
                theme_map=inputs.client_cfg.theme_map or None,
                nonveg_items=nonveg_items,
                served_dates=set(inputs.weekday_dates),
            ).to_dict()

        # The solver's own "I could not fully enforce this" lines are only
        # observable while it runs, so they are collected here and shipped with
        # the plan; /explain cannot recover them after the fact.
        relax = RelaxationCapture()
        try:
            with relax:
                if n_alt > 0:
                    plans, plan_dates = solver.solve(n_alternates=n_alt)
                else:
                    week_plan, plan_dates = solver.solve()
                    plans = [week_plan]
        except RuntimeError:
            # The cross-counter sync is best-effort and must never be what
            # makes a counter unsolvable (note 22). Individually eligible pins
            # can still over-constrain a day together: ICON Chn's Roti Combo
            # runs four colour cells and the primary pins three of them, so a
            # day whose pinned bread, gravy and dessert carry two colours
            # between them cannot reach the three distinct the city asks for.
            # Nothing catches that in advance — each pin is fine on its own —
            # so the fallback is to drop the sync and solve the counter as an
            # unsynced one, which is what it would have been without the
            # feature. A client's OWN constant pins are not touched.
            if not data.get('shared_items'):
                raise
            logger.warning(
                "%s counter %r: no plan with the shared-category pins; "
                "retrying without them so the counter still gets a menu.",
                inputs.client_name, counter_name,
            )
            metrics.incr('plan_shared_items_dropped_total')
            unsynced = dict(data)
            unsynced.pop('shared_items', None)
            inputs = _prepare_solver_inputs(unsynced, client_cfg=client_cfg)
            solver = MenuSolver(
                pools=inputs.pools,
                solver_config=inputs.cfg,
                menu_rules=inputs.rules,
                banned_by_date=inputs.banned,
                ricebread_ban_day=inputs.rb_ban,
                recent_sigs=inputs.recent_sigs,
                skip_cells=inputs.skip_cells,
                recency_by_item=inputs.recency_by_item,
            )
            relax = RelaxationCapture()
            with relax:
                if n_alt > 0:
                    plans, plan_dates = solver.solve(n_alternates=n_alt)
                else:
                    week_plan, plan_dates = solver.solve()
                    plans = [week_plan]
            pool_warnings = list(pool_warnings or []) + [
                "Cross-counter sync skipped for this counter: the shared "
                "dishes could not all be served here, so it was planned "
                "independently."
            ]

        response = {
            'success': True,
            'message': f'Menu plan generated for {inputs.client_name}',
            'solution': _format(plans[0]),
            'rule_diagnostics': diag_dicts,
            'summary': summary,
            'counter_mode': 'multi' if counter_count > 1 else 'single',
            'counter_count': counter_count,
            'counter_index': counter_index,
            'counter_name': counter_name,
            # Which service this plan is. Echoed so the planner can label the
            # set and hand the same value back to /save — the response is the
            # only place the caller learns what the server normalised it to.
            'meal': normalize_meal(data.get('meal')),
        }
        if len(plans) > 1:
            # Ranked best-first; the primary is already in `solution`.
            response['alternates'] = [_format(p) for p in plans[1:]]
        if pool_warnings:
            response['pool_warnings'] = pool_warnings
        # Regional days actually in force, and the picks that could not be.
        # Both absent on a plan nobody asked a region for, so an ordinary
        # response body is byte-for-byte what it was.
        if inputs.region_days:
            response['region_days'] = dict(inputs.region_days)
        if inputs.region_problems:
            response['region_problems'] = list(inputs.region_problems)
        # Rules the solve under-enforced rather than failed on. Pass these back
        # to /explain so the explanation says which rule did not hold — the
        # honesty channel, not decoration (design note 9c).
        if relax.records:
            response['relaxations'] = relax.records
        if solver.rule_failures:
            response['rule_warnings'] = solver.rule_failures
            _count_rule_failures(solver.rule_failures)
        metrics.incr('plan_requests_total', outcome='success')
        return jsonify(response)

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Solver failed: %s", e)
        # Counts infeasibility + exhausted-restarts from the CP-SAT path;
        # this is the SLO-relevant failure mode (vs 4xx, which is caller
        # input error).
        metrics.incr('plan_requests_total', outcome='solver_error')
        metrics.incr('solver_failures_total')
        body = {'success': False, 'error': str(e)}
        # Ship the pre-flight report with the failure. It passed the blocking
        # gate, but its warnings name the slots and rules under pressure, which
        # is what an admin needs to fix the config.
        if diag_dicts:
            body['rule_diagnostics'] = diag_dicts
        if summary:
            body['summary'] = summary
        return jsonify(body), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return _internal_error_response(500)
    except Exception as e:
        logger.error("Unexpected error in plan: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/regenerate', methods=['POST'])
@rate_limit("regenerate")
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

        _require_known_client(data.get('client_name'))
        _idx, _cname, _ccount, client_cfg = _resolve_counter(
            data.get('client_name'), data,
        )
        inputs = _prepare_solver_inputs(data, client_cfg=client_cfg)

        base_plan = {
            dt.date.fromisoformat(d_str): _items_from_day(slots)
            for d_str, slots in base_plan_raw.items()
        }
        replace_mask = {
            dt.date.fromisoformat(d_str): set(slot_list)
            for d_str, slot_list in replace_slots_raw.items()
        }
        # Optional: items already suggested for a cell this session, so repeated
        # regenerations keep giving something new instead of cycling A->B->A.
        # Shape: {iso_date: {slot_id: [item, …]}}.
        extra_forbidden = {}
        for d_str, slot_map in (data.get('exclude_items') or {}).items():
            try:
                d = dt.date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            for slot_id, items in (slot_map or {}).items():
                if items:
                    extra_forbidden[(d, str(slot_id))] = set(items)

        regen = MenuRegenerator(
            pools=inputs.pools,
            df=inputs.df,
            solver_config=inputs.cfg,
            menu_rules=inputs.rules,
            banned_by_date=inputs.banned,
            ricebread_ban_day=inputs.rb_ban,
            recent_sigs=inputs.recent_sigs,
            skip_cells=inputs.skip_cells,
            recency_by_item=inputs.recency_by_item,
        )

        week_plan, plan_dates = regen.regenerate(
            base_plan, replace_mask, extra_forbidden=extra_forbidden)

        formatter = SolutionFormatter(
            week_plan, span_dates(plan_dates, inputs),
            theme_map=inputs.client_cfg.theme_map or None,
            nonveg_items=_get_nonveg_items(inputs.city),
            served_dates=set(inputs.weekday_dates),
        )
        response = {
            'success': True,
            'message': f'Regenerated {sum(len(v) for v in replace_mask.values())} cells for {inputs.client_name}',
            'solution': formatter.to_dict(),
        }
        if regen.rule_failures:
            response['rule_warnings'] = regen.rule_failures
            _count_rule_failures(regen.rule_failures)
        metrics.incr('regenerate_requests_total', outcome='success')
        return jsonify(response)

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Regeneration failed: %s", e)
        metrics.incr('regenerate_requests_total', outcome='solver_error')
        metrics.incr('solver_failures_total')
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return _internal_error_response(500)
    except Exception as e:
        logger.error("Unexpected error in regenerate: %s", e, exc_info=True)
        return _internal_error_response(500)


#: Counter label used when reporting an unknown dish on the single-counter save
#: path, where there is no counter to name.
_SINGLE_COUNTER = 'plan'


def _saved_response(unknown, meal=None):
    """The /save body. `unknown_items` appears only when there is something to
    say, and `meal` only when it is not the default, so a clean single-service
    save is byte-for-byte what it always was."""
    body = {'success': True, 'message': 'Plan saved to history'}
    if meal and meal != DEFAULT_MEAL:
        body['meal'] = meal
        body['message'] = f'{meal.capitalize()} plan saved to history'
    if unknown:
        body['unknown_items'] = unknown
        body['warning'] = (
            f"{len(unknown)} dish name(s) were saved but match no item in this "
            f"client's city list, so the cooldown and freshness rules will not "
            f"recognise them."
        )
    return body


def _declared_constant_values(client_name):
    """Every literal a client's `constant_items` can stamp, lower-cased.

    These are legitimately off-ontology (note 9): "Mutton Biryani" and "Fish
    Tikka Masala" name dishes the veg-only list does not carry, are stamped
    verbatim post-solve, and reach `/save` like any other dish. So they must
    not be reported as unrecognised.

    A pin's value is a string, a `{weekday: value}` map, or a list that
    alternates by ISO week — all three flattened here, since which one fires on
    a given day is not the question.
    """
    def literals(spec):
        if isinstance(spec, str):
            yield spec
        elif isinstance(spec, list):
            for v in spec:
                yield from literals(v)
        elif isinstance(spec, dict):
            for k, v in spec.items():
                if not str(k).startswith('_'):
                    yield from literals(v)

    out = set()
    loader = MenuRuleLoader()
    for counter in (None, *_counter_names(client_name)):
        try:
            pins = loader.get_client_constant_items(client_name, counter)
        except Exception:  # noqa: BLE001 — a missing block is not an error here
            continue
        for slot, spec in (pins or {}).items():
            if str(slot).startswith('_'):
                continue
            out.update(v.strip().lower() for v in literals(spec) if v)
    return out


def _counter_names(client_name):
    try:
        return [c.counter_name for c in _get_client_loader()
                .get_client_configs(client_name) if c.counter_name]
    except Exception:  # noqa: BLE001 — validation must never block a save
        return []


def _canonicalise_saved_plan(client_name, counter_plans):
    """Rewrite each dish to the ontology's own spelling; report what will not.

    THE REASON THIS EXISTS. `menu_history` is not a write-only log — it is read
    back on every subsequent plan, by the item cooldown
    (`banned_items_by_date`), the freshness objective
    (`days_since_last_served`), the cross-week cadence rules
    (`selector_banned_by_date`) and the week signatures. Every one of those
    compares the stored string against the ontology's `item` column:
    `ItemCooldownMenuRule.pre_filter_pool` is literally
    ``pool['item'].isin(banned)``.

    `/save` used to store whatever it was handed. A plan this client's own
    `/plan` produced round-trips fine — `item_base` IS the ontology spelling —
    so the bug never showed on the normal path. Anything else fails SILENTLY
    and in the worst direction: a display name ("Dal Tadka") is stored as
    `dal tadka`, which matches no pool row, so the dish is never banned and
    never ages. The cooldown simply stops working for it, with nothing logged,
    no diagnostic, and a plausible menu every week.

    So each dish is resolved through the same space/underscore matching a
    `constant_items` pin uses, and the ontology's spelling is what gets stored.
    That turns the silent failure into a correct save rather than a warning
    about an incorrect one.

    What does NOT resolve is reported and stored as given — **never rejected**.
    Two reasons: an off-ontology pin is a real feature, and a plan the user has
    just spent a solve generating must not be lost to a name we failed to
    recognise. A wrong cooldown is recoverable; a discarded plan is not.

    Returns ``(counter_plans, unknown)`` where *unknown* is a sorted list of
    ``"<counter>/<slot>: <item>"`` strings.
    """
    try:
        city = _client_row(client_name)['city']
        known = ontology_repository.item_names(city)
    except Exception as exc:  # noqa: BLE001 — never block a save on a lookup
        logger.warning("Could not load %s's item list to check the saved "
                       "plan: %s", client_name, exc)
        return counter_plans, []
    if not known:
        return counter_plans, []
    pinned = _declared_constant_values(client_name)

    unknown, out = set(), []
    for counter_name, week_plan in counter_plans:
        fixed = {}
        for day, slots in week_plan.items():
            day_out = {}
            for slot_id, value in (slots or {}).items():
                base = strip_color_suffix(value if isinstance(value, str)
                                          else str(value))
                canonical = _canonical_item_name(base, known)
                if canonical is not None:
                    day_out[slot_id] = canonical
                    continue
                day_out[slot_id] = value
                if base.strip() and base.strip().lower() not in pinned:
                    unknown.add(f"{counter_name}/{slot_id}: {base.strip()}")
            fixed[day] = day_out
        out.append((counter_name, fixed))

    if unknown:
        logger.warning(
            "Saving %s: %d dish name(s) match no item in its city list and no "
            "declared constant, so the cooldown and freshness rules will not "
            "recognise them: %s",
            client_name, len(unknown), "; ".join(sorted(unknown)[:10]),
        )
    return out, sorted(unknown)


@app.route('/api/v1/save', methods=['POST'])
@rate_limit("write")
@require_write_token
def save_plan():
    try:
        data = request.get_json(silent=True) or {}
        client_name = data.get('client_name')
        week_start_str = data.get('week_start')

        _require_known_client(client_name)
        if not week_start_str:
            return jsonify({'success': False, 'error': 'week_start is required'}), 400
        week_start = dt.date.fromisoformat(week_start_str)
        # Which service this plan is. Part of the storage key, so a dinner save
        # replaces only the dinner rows for these dates; without it the second
        # save of a day silently deletes the first.
        meal = normalize_meal(data.get('meal'))

        from src.db import get_supabase
        sb = get_supabase()
        hm = HistoryManager()

        # Multi-cuisine: {counters: [{name, week_plan}, …]} — one nested
        # menu_history row per day; week signature taken from the primary
        # counter for a stable one-row-per-(client,week) record.
        counters_raw = data.get('counters')
        if counters_raw:
            counter_plans = []
            for c in counters_raw:
                wp = {
                    dt.date.fromisoformat(d_str): _items_from_day(day_data)
                    for d_str, day_data in (c.get('week_plan') or {}).items()
                }
                counter_plans.append((c.get('name') or 'Counter', wp))
            all_dates = sorted({d for _n, wp in counter_plans for d in wp.keys()})
            if not all_dates:
                return jsonify({'success': False, 'error': 'week_plan is required'}), 400
            # Canonicalise BEFORE the signature: the signature is what
            # `week_signature_cooldown` compares a future week against, so it
            # has to be computed over the same spellings that get stored.
            counter_plans, unknown = _canonicalise_saved_plan(
                client_name, counter_plans)
            primary_wp = counter_plans[0][1]
            sig = HistoryManager.compute_week_signature(
                primary_wp, all_dates, const_slots=CONST_SLOTS,
                strip_color_fn=strip_color_suffix,
            )
            hm.save_counters(counter_plans, all_dates, client_name, week_start, sig,
                             supabase_client=sb, strip_color_fn=strip_color_suffix,
                             meal=meal)
            return jsonify(_saved_response(unknown, meal=meal))

        # Single-cuisine (classic) path.
        week_plan_raw = data.get('week_plan', {})
        if not week_plan_raw:
            return jsonify({'success': False, 'error': 'week_plan is required'}), 400
        week_plan = {
            dt.date.fromisoformat(d_str): _items_from_day(day_data)
            for d_str, day_data in week_plan_raw.items()
        }
        dates = sorted(week_plan.keys())
        canonical, unknown = _canonicalise_saved_plan(
            client_name, [(_SINGLE_COUNTER, week_plan)])
        week_plan = canonical[0][1]
        sig = HistoryManager.compute_week_signature(
            week_plan, dates, const_slots=CONST_SLOTS,
            strip_color_fn=strip_color_suffix,
        )
        hm.save(week_plan, dates, client_name, week_start, sig,
                supabase_client=sb, strip_color_fn=strip_color_suffix, meal=meal)

        return jsonify(_saved_response(unknown, meal=meal))

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except (FileNotFoundError, OSError) as e:
        logger.error("Save failed: %s", e, exc_info=True)
        return _internal_error_response(500)
    except Exception as e:
        logger.error("Unexpected save error: %s", e, exc_info=True)
        return _internal_error_response(500)






@app.route('/api/v1/saved-plan', methods=['GET'])
def saved_plan():
    """Return the saved plan for a client + date range, if one exists.

    Query params:
        client_name (required): the client to look up.
        start_date  (optional): YYYY-MM-DD; defaults to today in
            APP_TZ.
        num_days    (optional): number of weekdays from start_date;
            defaults to 5. Sat/Sun are skipped, mirroring /plan.
        meal        (optional): 'lunch' (default) or 'dinner'. A site running
            both has two menus per date, and the result is keyed by date, so
            one has to be chosen.

    Response shape mirrors /plan so the UI can use one code path:
        {
          "success": True,
          "exists": <bool>,           # True iff every requested date
                                      # has at least one saved row.
          "covered_dates": [...],     # ISO date strings that DID have
                                      # saved rows (could be a strict
                                      # subset of the requested range).
          "source": "history",
          "solution": <SolutionFormatter.to_dict() output>,
        }

    When ``exists`` is False the ``solution`` only contains the days
    that were partially saved; the caller decides whether to fall back
    to /plan. We never call the solver from this endpoint — it's a
    pure read path.
    """
    try:
        client_name = request.args.get('client_name', '').strip()
        _require_known_client(client_name)

        start_date_str = request.args.get('start_date')
        num_days = max(
            MIN_NUM_DAYS,
            min(MAX_NUM_DAYS, int(request.args.get('num_days', 5))),
        )
        start_date = (
            dt.date.fromisoformat(start_date_str)
            if start_date_str else today_in_app_tz()
        )
        loader = _get_client_loader()
        row = _client_row(client_name)
        client_cfg = loader.get_client_configs_from_row(client_name, row)[0][1]
        city = row['city']
        # `all_dates` rather than `span_dates`: that name is now the imported
        # helper, and shadowing it here would read as a call site of it.
        all_dates = _weekdays_from(
            start_date, num_days, getattr(client_cfg, 'serve_weekends', False),
        )
        weekday_dates = _filter_dates_by_working_days(
            all_dates, getattr(client_cfg, 'working_days', None),
        )

        from src.db import get_supabase
        sb = get_supabase()
        # Only the served days can have a saved menu, but the table is rendered
        # over the whole span so a non-working day stays a blank column here
        # too — a saved plan and a fresh one must have the same shape.
        raw_saved = HistoryManager.load_saved_plan(
            sb, client_name, weekday_dates,
            meal=normalize_meal(request.args.get('meal')),
        )

        # Enrich with color suffix so the UI's renderer matches /plan — from the
        # client's own city list, so a Pune dish is matched against Pune items.
        df, _pools = _get_menu_data(city)
        enriched = _enrich_history_plan(raw_saved, df)

        formatter = SolutionFormatter(
            enriched, all_dates,
            theme_map=client_cfg.theme_map or None,
            nonveg_items=_get_nonveg_items(city),
            served_dates=set(weekday_dates),
        )
        covered = sorted(d.isoformat() for d in enriched.keys())
        exists = len(enriched) == len(weekday_dates) and len(enriched) > 0

        return jsonify({
            'success': True,
            'exists': exists,
            'covered_dates': covered,
            'source': 'history',
            'solution': formatter.to_dict(),
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to load saved plan: %s", e, exc_info=True)
        return _internal_error_response(500)


def _city_pool_tokens(only_city=None):
    """``{city: [pool tokens]}``, plus the union under ``''``.

    Pool tokens are per-city (they name pools inside one city's item list), so
    the editor needs to know which city a token belongs to.

    ``only_city`` restricts the work to ONE city, which is the whole point:
    computing the map for every city means parsing every city's workbook, and
    that is where `/editor-metadata` spent 4.8 s of cold start — three workbooks,
    4,956 rows, to answer a question about eight short strings. A caller that has
    already chosen a city needs exactly one of them. Passing an unknown city name
    yields an empty map rather than falling back to "all", so a typo cannot
    silently reintroduce the full load.
    """
    by_city: Dict[str, list] = {}
    union: Set[str] = set()
    wanted = ([c for c in AVAILABLE_CITIES if c == only_city] if only_city
              else list(AVAILABLE_CITIES))
    # Precomputed map first: answering "which pool tokens exist" by parsing every
    # workbook cost 4.8 s of cold start for ~8 short strings. `None` from the
    # helper means the file is absent or unreadable, in which case we fall back to
    # the workbooks — a fresh checkout is slow, never wrong.
    for city in wanted:
        cached = pool_tokens_for_city(city)
        if cached is not None:
            by_city[city] = sorted(cached)
            union |= set(cached)
            continue
        try:
            tokens = available_pool_tokens(_get_menu_data(city)[0])
        except Exception as exc:  # noqa: BLE001 — one unreadable city must not 500
            logger.warning("Could not read pool tokens for %s: %s", city, exc)
            continue
        by_city[city] = sorted(tokens)
        union |= tokens
    by_city[''] = sorted(union)
    return by_city


@app.route('/api/v1/editor-metadata', methods=['GET'])
def editor_metadata():
    """Return metadata needed by the customisation editor UI.

    ``?city=<name>`` scopes ``available_client_pools`` to that city's ontology;
    without it the list is the union across cities (a superset, so no valid
    token is ever hidden from the editor). ``client_pools_by_city`` always
    carries the per-city breakdown.
    """
    try:
        city = (request.args.get('city') or '').strip()
        # Scoped when a city is given: see _city_pool_tokens. Without one the
        # caller gets the cross-city union, which still costs every workbook —
        # the editor's first fetch happens before a city is chosen, so that path
        # is unavoidable until the UI is split further.
        pools_by_city = _city_pool_tokens(only_city=city or None)
        available = pools_by_city.get(city, pools_by_city[''])
        return jsonify({
            'success': True,
            'base_slot_names': list(BASE_SLOT_NAMES),
            'const_slots': list(CONST_SLOTS),
            'default_off_slots': list(DEFAULT_OFF_SLOTS),
            'default_theme_map': DEFAULT_THEME_MAP,
            'available_themes': AVAILABLE_THEMES,
            'available_cities': list(AVAILABLE_CITIES),
            'available_client_pools': available,
            'client_pools_by_city': {
                k: v for k, v in pools_by_city.items() if k
            },
            'default_item_cooldown_days': DEFAULT_ITEM_COOLDOWN_DAYS,
            'clients': _request_client_names(),
            'max_counters': MAX_COUNTERS,
        })
    except Exception as e:
        logger.error("Failed to load editor metadata: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/regions', methods=['GET'])
@rate_limit("diagnose")
def regions_for_city():
    """Regions a city's item list can theme a day with.

    ``?city=<name>`` is required in practice — without it the default city's
    list is measured, which is the same fallback `city_excel_path` makes
    everywhere else.

    Its own endpoint rather than a field on `/editor-metadata` for the reason
    note 21 records: that one already costs every city's workbook, and this
    needs one. The planner calls it only when somebody switches the regional
    toggle ON, so a user who never does pays nothing — the same argument
    `/explain` is a separate request.

    Every region is returned, themeable or not, each carrying its per-slot
    depth. The picker greys the thin ones out *with their counts* instead of
    hiding them, so an operator can see a region was weighed and rejected
    rather than forgotten.
    """
    try:
        city = (request.args.get('city') or '').strip() or None
        regions = ontology_repository.regions(city)
        return jsonify({
            'success': True,
            'city': city,
            'regions': [r.as_dict() for r in regions],
            'themeable': [r.name for r in regions if r.is_themeable],
            # False for every committed workbook today: the regional columns
            # arrived with the client's corrected city lists, which are not
            # installed. The planner hides the whole control on this.
            'available': any(r.is_themeable for r in regions),
            'theme_compatibility': {
                t: sorted(r.name for r in regions
                          if r.is_themeable and r.compatible_with(t))
                for t in AVAILABLE_THEMES
            },
        })
    except Exception as e:
        logger.error("Failed to measure regions: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/pool-preview', methods=['POST'])
@rate_limit("diagnose")
def pool_preview():
    """Preview the eligible item pool for a set of source pools (F5 config UI).

    Body: ``{"source_pools": ["infineon", ...], "city": "Pune"}``. ``common`` is
    always included. Returns the distinct eligible item count and a
    category-wise (course_type) breakdown so the editor can show live counts as
    the admin toggles pools. ``city`` selects which city's item list is
    counted — omit it for the default city.
    """
    try:
        data = request.get_json(silent=True) or {}
        sp = data.get('source_pools') or []
        if not isinstance(sp, list):
            return jsonify(
                {'success': False, 'error': 'source_pools must be a list'}), 400
        city = (data.get('city') or '').strip() or None
        df, _ = _get_menu_data(city)
        available = available_pool_tokens(df)
        requested = {normalize_name(t) for t in sp if normalize_name(t)}
        requested.discard('common')
        unknown = requested - available
        if unknown:
            return jsonify({
                'success': False,
                'error': (
                    f'Unknown client pool(s) for '
                    f'{city or "the default city"}: {sorted(unknown)}'
                ),
            }), 400
        active = get_active_pools(requested)
        # Through the repository, not `filter_eligible` directly: the full-pool
        # policy lives there (note 15), so counting it here meant the editor
        # previewed a narrowing the planner does not do. Pune showed it — the
        # preview said 512 dishes while a plan drew on all 1,315.
        eligible, _ = ontology_repository.filtered_menu_data(city, sorted(requested))
        by_cat = (
            eligible['course_type'].astype(str).str.lower()
            .value_counts().to_dict()
        )
        return jsonify({
            'success': True,
            'city': city,
            'active_pools': sorted(active),
            'eligible_item_count': int(len(eligible)),
            'category_counts': {k: int(v) for k, v in by_cat.items()},
        })
    except Exception as e:
        logger.error("pool-preview failed: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/client-config/<client_name>', methods=['GET'])
def get_client_config(client_name):
    """Return the full editable config for one client.

    Includes a ``version`` field + an ``ETag: "<version>"`` response
    header so callers can issue optimistic-concurrency-safe PUTs.
    """
    try:
        # The whole config is one document, so one read serves the whole
        # response: the counters list gives the mode, and the primary counter
        # (index 0) supplies the flat fields the editor still consumes
        # (active_base_slots / slot_counts / theme_map).
        row = _client_row(client_name)
        counters = row['counters']
        counter_mode = 'multi' if len(counters) > 1 else 'single'
        version = row['version']
        primary = counters[0]
        response = jsonify({
            'success': True,
            'name': client_name,
            'city': row['city'],
            'serve_weekends': row['serve_weekends'],
            # Which services this client runs, in the order they are eaten.
            # The planner solves one menu per entry and hands each the
            # earlier ones' dishes to avoid.
            'meals': row.get('meals') or list(DEFAULT_MEALS),
            'working_days': row['working_days'],
            'item_cooldown_days': row['item_cooldown_days'],
            'source_pools': row['source_pools'],
            'is_launch_site': row.get('is_launch_site', False),
            'active_base_slots': list(primary['categories']),
            'slot_counts': primary['slot_counts'],
            'theme_map': primary['theme_map'],
            'version': version,
            'counter_mode': counter_mode,
            'counters': counters,
            # Base slots this client serves identically across its counters. The
            # editor writes it to clients.shared_categories (DB); a client
            # configured only in client_rules.json (e.g. DXC) has none in the DB,
            # so fall back to the file value. The planner reads whichever wins to
            # sync the primary counter's dish into the others per day.
            'shared_categories': (
                row.get('shared_categories')
                or MenuRuleLoader().get_shared_categories(client_name)
            ),
            # Counters that opt OUT of that sync. File-only (no DB column, no
            # editor control): ICON Chn's Rice Combo is stated to have its own
            # menu, and the shared list is otherwise all-or-nothing per client.
            'shared_categories_excluded_counters':
                MenuRuleLoader().get_shared_category_exclusions(client_name),
            # Standing weekday -> region pattern. `{}` when nothing is stored
            # and when the column predates this feature, so the planner treats
            # both the same: no regional days until somebody picks one.
            'region_map': row.get('region_map') or {},
        })
        response.headers['ETag'] = f'"{version}"'
        return response
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Failed to load client config: %s", e, exc_info=True)
        return _internal_error_response(500)


_ETAG_RE = re.compile(r'^\s*(?:W/)?"?(\d+)"?\s*$')


def _expected_version(data: Dict[str, Any]) -> Optional[int]:
    """Extract the expected version from the request.

    Accepts either ``{"version": N}`` in the JSON body (preferred by our
    own UI) or an ``If-Match: "N"`` / ``If-Match: N`` header for HTTP
    clients that want to speak the standard idiom.
    """
    if 'version' in data:
        try:
            return int(data['version'])
        except (TypeError, ValueError):
            raise ValueError("version must be an integer")
    header = request.headers.get('If-Match', '').strip()
    if header:
        m = _ETAG_RE.match(header)
        if not m:
            raise ValueError("If-Match header must be a quoted integer")
        return int(m.group(1))
    return None


def _validated_working_days(raw):
    """Normalise ``working_days`` or raise ValueError. ``None`` clears it."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("working_days must be a list of weekday names or null")
    from src.constants import canonical_weekday
    out = []
    for value in raw:
        full = canonical_weekday(value)
        if not full:
            raise ValueError(
                f"working_days contains {value!r}, which is not a weekday. "
                f"Use full names or three-letter abbreviations."
            )
        if full not in out:
            out.append(full)
    return out or None


def _validated_cooldown_days(raw):
    """Normalise ``item_cooldown_days`` or raise ValueError. ``None`` = default."""
    if raw is None or raw == '':
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        raise ValueError("item_cooldown_days must be an integer or null")
    if days < 0:
        raise ValueError("item_cooldown_days must be >= 0")
    return days


def _validated_source_pools(raw, city=None):
    """Normalise ``source_pools`` against *city*'s ontology or raise ValueError.

    Validated per city on purpose: pool tokens live in one city's item list, so
    a Pune client configured with a Bangalore-only token would match nothing
    and silently serve the ``common`` pool alone.
    """
    sp = raw or []
    if not isinstance(sp, list):
        raise ValueError("source_pools must be a list of pool tokens")
    available = available_pool_tokens(_get_menu_data(city)[0])
    requested = {normalize_name(t) for t in sp if normalize_name(t)}
    requested.discard('common')
    unknown = requested - available
    if unknown:
        raise ValueError(
            f"Unknown client pool(s) for {city or 'the default city'}: "
            f"{sorted(unknown)}. Valid pools: {sorted(available)}"
        )
    return sorted(requested)


def _validated_region_map(raw, city=None):
    """Normalise a ``region_map`` against *city*'s item list or raise ValueError.

    Validated per city for the same reason as `_validated_source_pools`: a
    region lives in one city's list, so a Pune client storing "Tamil Nadu"
    would match nothing and quietly plan an ordinary week. Rejecting at the
    write is what makes that a 400 the operator sees rather than note 9's
    silent mismatch, where the plan still comes back and looks fine.

    An empty map is always valid — that is how a standing pattern is cleared.
    """
    from src.application.regions import normalize_region_map

    if raw in (None, {}, ''):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("region_map must be an object of weekday -> region")
    regions = ontology_repository.regions(city)
    themeable = {r.name for r in regions if r.is_themeable}
    cleaned = normalize_region_map(raw, regions)
    # Anything the normaliser dropped: a weekday nobody recognises, or a region
    # this city cannot theme. Both are worth a message — silently storing the
    # survivors would leave the operator believing they saved a Friday they did
    # not.
    asked = {str(k).strip().lower() for k, v in raw.items() if str(v or '').strip()}
    kept = {k for k in cleaned} | {k[:3] for k in cleaned}
    lost = sorted(a for a in asked if a not in kept)
    if lost:
        raise ValueError(
            f"Cannot set a regional day for {lost} in "
            f"{city or 'the default city'}: the weekday is unknown, or the "
            f"region is not one this city can theme. Available: "
            f"{sorted(themeable) or 'none — this city has no regional data'}"
        )
    return cleaned


@app.route('/api/v1/client-config/<client_name>', methods=['PUT'])
@rate_limit("write")
@require_write_token
def update_client_config(client_name):
    """Update a client's configuration (slots, slot counts, theme overrides).

    Requires an optimistic-concurrency version from the caller to avoid
    last-write-wins when two admins edit the same client. Either:
      * ``{"version": N}`` in the JSON body (what our Streamlit UI sends), or
      * ``If-Match: "N"`` header for standard HTTP clients.

    Responds 409 Conflict with the current version when the check fails.
    """
    from src.client.client_config import ConcurrentEditError

    try:
        data = request.get_json(silent=True) or {}
        loader = _get_client_loader()

        expected = _expected_version(data)
        if expected is None:
            return jsonify({
                'success': False,
                'error': (
                    'version is required (include "version" in the JSON '
                    'body or send an If-Match header with the ETag from '
                    'GET /client-config). This prevents silently '
                    'overwriting another admin\'s changes.'
                ),
            }), 400

        # Validate and normalise EVERYTHING before touching the database.
        #
        # This used to bump the version first and then run each field's setter
        # in turn, validating as it went — so a malformed `source_pools` (the
        # last field checked) returned 400 *after* city, serve_weekends,
        # working_days and item_cooldown_days had already been committed and the
        # version incremented. A single bad request deterministically left a
        # half-updated row whose bumped version then made the caller's retry
        # 409. Validate-then-write, in one statement, removes that entirely.
        fields: Dict[str, Any] = {}

        # Counter-aware path: ``counters`` is the full source of truth for the
        # client's cuisine setup. Otherwise, accept the legacy per-field shape
        # (active_base_slots / slot_counts / theme_map) and apply it to the
        # primary counter for backward compatibility.
        if 'counters' in data:
            fields['counters'] = loader.normalize_counters_for_write(
                data.get('counter_mode', 'single'), data['counters'],
            )
        elif any(k in data for k in ('active_base_slots', 'slot_counts', 'theme_map')):
            fields['counters'] = loader.primary_counter_patch(
                client_name,
                active_base_slots=data.get('active_base_slots'),
                slot_counts=data.get('slot_counts'),
                theme_map=data.get('theme_map'),
            )

        # City / weekend-service are plain client attributes (not per-counter);
        # update them when the caller includes them.
        if 'city' in data:
            fields['city'] = normalize_city(data.get('city'))
        if 'serve_weekends' in data:
            fields['serve_weekends'] = bool(data.get('serve_weekends'))
        if 'meals' in data:
            fields['meals'] = normalize_meals(data.get('meals'))
        if 'working_days' in data:
            fields['working_days'] = _validated_working_days(
                data.get('working_days'))
        if 'item_cooldown_days' in data:
            fields['item_cooldown_days'] = _validated_cooldown_days(
                data.get('item_cooldown_days'))
        if 'is_launch_site' in data:
            fields['is_launch_site'] = bool(data.get('is_launch_site'))
        if 'source_pools' in data:
            # Validate against the city the client will HAVE after this update
            # (the payload's, else the stored one) — a city change and a pool
            # change can arrive in the same PUT.
            fields['source_pools'] = _validated_source_pools(
                data.get('source_pools'),
                city=fields.get('city', _client_row(client_name)['city']),
            )
        if 'shared_categories' in data:
            # Base slots synced across counters (the editor's toggle+multiselect).
            # Normalisation (keep known slots only) happens in the config layer.
            fields['shared_categories'] = list(data.get('shared_categories') or [])
        if 'region_map' in data:
            # Validated against the city the client will HAVE after this write,
            # same as source_pools above and for the same reason: a city change
            # and a region change can arrive in one PUT. Rejected rather than
            # dropped — a stored region that matches nothing is note 9's silent
            # config mismatch, where the plan still comes back and looks fine.
            fields['region_map'] = _validated_region_map(
                data.get('region_map'),
                city=fields.get('city', _client_row(client_name)['city']),
            )

        new_version = loader.update_client_atomic(client_name, expected, fields)

        response = jsonify({
            'success': True,
            'message': f'Config updated for {client_name}',
            'version': new_version,
        })
        response.headers['ETag'] = f'"{new_version}"'
        return response
    except ConcurrentEditError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'current_version': e.current_version,
        }), 409
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Error updating client config: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/client', methods=['POST'])
@rate_limit("write")
@require_write_token
def create_client():
    """Create a new client.

    Two body shapes are accepted:
      * classic: ``{"name", "active_slots": [...]}`` — one implicit counter.
      * counter-aware: ``{"name", "counter_mode": "single"|"multi",
        "counters": [{name, categories, slot_counts, theme_map}, ...]}``.
    """
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'name is required'}), 400

        loader = _get_client_loader()

        # Validate and normalise EVERY field before the row is inserted.
        #
        # `source_pools` used to be validated *after* create_client() had
        # already committed the row, so `{"source_pools": ["typo"]}` answered
        # 400 while leaving a real client behind with no pools — and the
        # caller's retry then failed on the duplicate name. Same class of bug
        # the PUT handler had; same fix, one write.
        city = normalize_city(data.get('city'))
        serve_weekends = bool(data.get('serve_weekends', False))
        meals = normalize_meals(data.get('meals')) if 'meals' in data else None
        item_cooldown_days = _validated_cooldown_days(
            data.get('item_cooldown_days'))
        working_days = (
            _validated_working_days(data.get('working_days'))
            if 'working_days' in data else None
        )
        # F5: optional client item-pool config (validated against the ontology).
        source_pools = (
            _validated_source_pools(data.get('source_pools'), city=city)
            if 'source_pools' in data else None
        )
        # Launch view: a client created here while launch mode is on is a launch
        # site. The editor sends the flag; it defaults false everywhere else.
        is_launch_site = bool(data.get('is_launch_site', False))
        # Base slots synced across counters (the editor's toggle+multiselect).
        shared_categories = (
            list(data.get('shared_categories') or [])
            if 'shared_categories' in data else None
        )
        region_map = (
            _validated_region_map(data.get('region_map'), city=city)
            if 'region_map' in data else None
        )

        counters = data.get('counters')
        if counters:
            loader.create_client(
                name,
                counter_mode=data.get('counter_mode', 'single'),
                counters=counters,
                city=city,
                serve_weekends=serve_weekends,
                meals=meals,
                item_cooldown_days=item_cooldown_days,
                working_days=working_days,
                source_pools=source_pools,
                is_launch_site=is_launch_site,
                shared_categories=shared_categories,
                region_map=region_map,
            )
        else:
            active_slots = data.get('active_slots', list(BASE_SLOT_NAMES))
            loader.create_client(name, active_slots, city=city,
                                 serve_weekends=serve_weekends,
                                 meals=meals,
                                 item_cooldown_days=item_cooldown_days,
                                 working_days=working_days,
                                 source_pools=source_pools,
                                 is_launch_site=is_launch_site,
                                 shared_categories=shared_categories,
                                 region_map=region_map)

        return jsonify({'success': True, 'message': f'Client {name} created'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to create client: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/client/<client_name>', methods=['DELETE'])
@rate_limit("write")
@require_write_token
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
        return _internal_error_response(500)


@app.route('/api/v1/diagnose', methods=['POST'])
@rate_limit("diagnose")
def diagnose_plan():
    """Pre-flight rule diagnostic. Same body shape as /plan but never
    invokes the solver — returns structured ``rule_diagnostics`` so the
    UI can show *why* a plan would fail before the user spends solver
    budget.

    Replaces the old /validate-pools endpoint; pool-size warnings are
    folded into the same ``rule_diagnostics`` list (look for entries
    with ``rule_type == 'pool_size'``).

    Response::

        {
          "success": true,
          "rule_diagnostics": [{rule, rule_type, severity, phase,
                                message, suggestion, affected}, …],
          "summary": {errors, warnings, infos, would_succeed},
          "pool_warnings": [...]   # back-compat projection, one release
        }
    """
    try:
        data = request.get_json() or {}
        # Resolve `counter_index` exactly as /plan does. Without this the
        # endpoint built its inputs from the *primary* counter no matter which
        # counter was asked about, so every multi-counter client got a clean
        # bill of health for counter 0 while the counter actually being planned
        # was unsatisfiable — Amadeus's Chinese counter reported
        # "would_succeed: true" and then came back INFEASIBLE.
        _require_known_client(data.get('client_name'))
        counter_index, counter_name, counter_count, client_cfg = _resolve_counter(
            data.get('client_name'), data,
        )
        inputs = _prepare_solver_inputs(data, client_cfg=client_cfg)
        diagnostics, summary = run_preflight(inputs)
        _record_diag_metrics(diagnostics)
        diag_dicts = [d.to_dict() for d in diagnostics]
        body = {
            'success': True,
            'rule_diagnostics': diag_dicts,
            'summary': summary,
            'counter_index': counter_index,
            'counter_name': counter_name,
            'counter_count': counter_count,
        }
        pool_warnings = pool_warnings_projection(diagnostics)
        if pool_warnings:
            body['pool_warnings'] = pool_warnings
        return jsonify(body)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to run diagnostics: %s", e, exc_info=True)
        return _internal_error_response(500)


def _rule_notes(rules) -> Dict[str, str]:
    """``{base_slot: the client's own sentence}`` from each rule's ``_comment``.

    The `_comment` is where the client's own sentence is recorded; reusing it
    means the explanation quotes them back to themselves instead of inventing a
    phrasing for a rule it only half understands.

    A rule whose ``base_slot`` is a LIST is skipped: it constrains the plate
    rather than one slot ("a protein source somewhere"), so attributing it to a
    particular dish would be a claim the config does not support. First rule to
    name a slot wins, which makes the result deterministic in config order.
    """
    notes: Dict[str, str] = {}
    for rule in rules or []:
        cfg = getattr(rule, 'config', None)
        if not isinstance(cfg, dict):
            continue        # a stub, or the legacy bare-list rule form
        comment = cfg.get('_comment')
        slot = cfg.get('base_slot')
        if not comment or not slot or isinstance(slot, (list, tuple, set)):
            continue
        # The RULE NAME leads. `_comment` is not reliably a client-facing
        # sentence — for `bread` it is the client's own words, for
        # `nonveg_biryani_one_per_day` it is 400 characters of rationale about
        # counting days versus dishes — so the reader gets something short and
        # identifiable first and the prose second. "Dindigul Thalappakatti
        # Biryani — nonveg biryani one per day" is actionable on its own; the
        # rationale alone is not.
        name = str(cfg.get('name') or '').replace('_', ' ').strip()
        note = _first_sentence(str(comment))
        notes.setdefault(str(slot),
                         f'{name} — {note}' if name else note)
    return notes


#: How much of a `_comment` a reader gets. `_comment` is not one kind of text:
#: in some configs it IS the client's own sentence ("client asks for a millet
#: bread on south days") and in others it is developer rationale explaining why
#: the rule is written the way it is. `nonveg_biryani_one_per_day`'s runs to 400
#: characters about counting DAYS versus dishes — true, useful to whoever edits
#: the rule, and unreadable as the answer to "why is this biryani here".
_NOTE_CHARS = 160


def _first_sentence(text: str) -> str:
    """The lead sentence of a rule comment, capped — see `_NOTE_CHARS`.

    The first sentence is where the client's own words are when they are there
    at all; the rationale that follows is for the person editing the rule. Cut
    on a sentence boundary rather than mid-word so what a chef reads is a whole
    thought, and mark a truncation so nobody mistakes it for the full note.
    """
    clean = ' '.join(str(text).split())
    head = re.split(r'(?<=[.!?])\s+', clean)[0] if clean else ''
    if len(head) <= _NOTE_CHARS:
        return head
    return head[:_NOTE_CHARS].rsplit(' ', 1)[0] + '…'


@app.route('/api/v1/explain', methods=['POST'])
@rate_limit("diagnose")
def explain_menu():
    """Explain a plan the caller already has. Never solves, never fails a menu.

    Its own endpoint rather than part of /plan because /plan is the slow path
    and this is optional: a caller that does not want the explanation does not
    pay for it, and a failure here cannot cost anyone a menu.

    Body is /plan's, plus what only /plan could know::

        {client_name, start_date, num_days, counter_index?,
         solution: {...},            # a /plan response's `solution`
         relaxations: [...]}         # a /plan response's `relaxations`

    Response::

        {"success": true,
         "days": [{date, weekday, theme, dishes: {slot: {...}},
                   plate_profile: {...}, checks: [...], provenance: [...],
                   relaxations: [...], overview: str, overview_source: str,
                   bullets: [...], prose: str|null,
                   llm_used: bool, reason: str}],
         "llm_used": bool}

    ``prose`` is null whenever the model is off (the default), unreachable, or
    said something the validator would not stand behind; ``bullets`` are always
    present, so the feature degrades to the renderer rather than to nothing.
    """
    try:
        data = request.get_json() or {}
        _require_known_client(data.get('client_name'))
        solution = data.get('solution') or {}
        if not isinstance(solution, dict) or not solution:
            raise ValueError('solution is required and must be a non-empty object')

        counter_index, counter_name, counter_count, client_cfg = _resolve_counter(
            data.get('client_name'), data,
        )
        inputs = _prepare_solver_inputs(data, client_cfg=client_cfg)

        # `forced_items` is keyed by (date, slot_id) rather than by slot, but
        # `build_provenance` only reads the VALUES to learn which dish names are
        # pinned — and these are the pins the solver actually used, with weekday
        # maps and ISO-week alternation already resolved (note 9).
        pinned = {f'{d}:{s}': v for (d, s), v in
                  (getattr(inputs.cfg, 'forced_items', None) or {}).items()}
        # `colour_variety` mirrors a rule the solver enforces, so it has to be
        # given the same numbers or it disagrees with the menu it is describing
        # (design note 13's clamp). Both come off the counter's own config.
        cfg = inputs.cfg
        packs = build_plan_evidence(
            solution=solution,
            attrs=attrs_from_dataframe(inputs.df),
            client_name=inputs.client_name,
            counter_name=counter_name,
            city=inputs.city,
            recency=inputs.recency_by_item,
            constant_items=pinned,
            rule_notes=_rule_notes(inputs.rules),
            colour_target=getattr(cfg, 'min_distinct_colors_per_day', None),
            colour_slots=getattr(cfg, 'color_slots', None),
            # Only the verdicts fit to show a chef, by default. `all_checks`
            # opts a caller back in — that is the calibration path, which needs
            # the uncalibrated numbers to measure them.
            calibrated_only=not bool(data.get('all_checks')),
        )
        relaxations = data.get('relaxations')
        if isinstance(relaxations, list) and relaxations:
            attach_relaxations(packs, [r for r in relaxations if isinstance(r, dict)])

        rendered = explain_plan(packs)
        days = []
        for pack in packs:
            extra = rendered.get(pack['date'], {})
            days.append({
                'date': pack['date'],
                'weekday': pack['weekday'],
                'theme': pack['theme'],
                # The per-slot dishes with their attributes. The rendered menu
                # table already has the NAMES; what the explanation needs on top
                # is the colour and texture behind each verdict, so a reader can
                # see why `texture_contrast` said what it said instead of taking
                # it on trust.
                'dishes': pack['dishes'],
                'plate_profile': pack['plate_profile'],
                'checks': pack['checks'],
                # Which dishes complement each other and what the plate lacks —
                # the meal-level answer the per-dish `provenance` cannot give.
                'pairings': pack['pairings'],
                'provenance': pack['provenance'],
                'relaxations': pack['relaxations'],
                # The short paragraph a chef actually reads: what goes with
                # what on this plate, and what it lacks. The PRIMARY surface —
                # `bullets` below is the per-verdict breakdown for whoever is
                # auditing the ruleset, a different reader with a different
                # question.
                #
                # The model writes it when one is configured and its reply
                # passes `validate`, because PHRASING is the one part of this
                # a model is better at: `day_overview` joins facts with an
                # em dash and cannot vary a sentence. What it may SAY is
                # unchanged either way — every claim still comes from the
                # pack, the validator still rejects an unsourced number or an
                # invented dish, and `_reports_the_bad_news` still rejects a
                # reply that stays quiet about a gap. So this swaps who does
                # the wording, never who decides the facts.
                #
                # `day_overview` remains the fallback and is never skipped: no
                # key, a timeout, a rate limit or a rejected reply all land
                # here, and an explanation must never be why a menu fails to
                # render. `overview_source` says which one the reader got, so
                # a deployment can tell "the model is off" from "the model
                # keeps being rejected" without reading the logs.
                'overview': extra.get('prose') or day_overview(pack),
                'overview_source': 'model' if extra.get('prose') else 'rendered',
                'bullets': extra.get('bullets') or [],
                'prose': extra.get('prose'),
                'llm_used': bool(extra.get('llm_used')),
                'reason': extra.get('reason', ''),
            })
        return jsonify({
            'success': True,
            'days': days,
            'llm_used': any(d['llm_used'] for d in days),
            'counter_index': counter_index,
            'counter_name': counter_name,
            'counter_count': counter_count,
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to explain plan: %s", e, exc_info=True)
        return _internal_error_response(500)


# Set after the first /health call observes schema drift, cleared on
# the next non-drift result. Lets us log the loud "run the migration"
# ERROR once per occurrence rather than every 30s of uptime-monitor
# noise — a re-pageable signal needs to BE re-pageable.
_drift_logged = False


def _probe_supabase():
    """Cheap reachability + schema-drift check.

    A single ``select('name, version').limit(1)`` query against the
    ``clients`` table verifies, in one round-trip:

      1. Supabase is reachable / authenticated / not blocked by RLS.
      2. The Phase 2 #14 migration has been applied (the ``version``
         column exists on ``clients``).

    Returns ``(reachable: bool, schema_info: dict)``. The dict carries
    ``status`` ∈ {"ok", "drift_detected", "unknown"} and a list of
    ``missing`` ``"table.column"`` strings. Operators read it from the
    /health response body — uptime monitors only see the HTTP status,
    which stays 200 when drift is present (the app still serves via
    the runtime fallback in client_config.py).
    """
    global _drift_logged
    try:
        from src.db import get_supabase
        get_supabase().table('clients').select('name, version').limit(
            1,
        ).execute()
        if _drift_logged:
            logger.info(
                "Schema drift cleared: clients.version is now visible. "
                "Optimistic-concurrency on PUT /client-config is back in "
                "effect."
            )
            _drift_logged = False
        return True, {"status": "ok", "missing": []}
    except Exception as exc:  # noqa: BLE001 — both error classes converted to dict states
        # Distinguish "DB has no clients.version column" (caller needs
        # to apply the migration) from "Supabase is just unreachable"
        # (network / auth issue).
        from src.client.client_config import _is_undefined_column
        if _is_undefined_column(exc):
            if not _drift_logged:
                logger.error(
                    "Schema drift: clients.version column missing. "
                    "Re-run scripts/setup_all.sql in the Supabase "
                    "SQL editor (the ALTER TABLE ... ADD COLUMN IF NOT "
                    "EXISTS is idempotent). The editor + concurrency "
                    "code degrade gracefully until the column is "
                    "added, but optimistic-concurrency on PUT is "
                    "disabled in this state."
                )
                _drift_logged = True
            return True, {
                "status": "drift_detected",
                "missing": ["clients.version"],
            }
        logger.warning("Supabase health probe failed: %s", exc)
        return False, {"status": "unknown", "missing": []}


@app.route('/api/v1/metrics', methods=['GET'])
def metrics_snapshot():
    """Return a point-in-time snapshot of every in-process counter.

    Labels are collapsed into the key using Prometheus text-format
    conventions (``rule_failures_total{rule="cuisine"}``), so a future
    swap to the real prometheus_client stays a one-file change in
    ``api/metrics.py`` without the caller surface moving.
    """
    return jsonify({
        'success': True,
        'uptime_seconds': int(time.time() - _STARTED_AT),
        'counters': metrics.snapshot(),
    })


@app.route('/api/v1/health', methods=['GET'])
def health():
    """Liveness + readiness combined.

    Returns 200 with status=healthy when Supabase is reachable, 503
    with status=degraded when it isn't. Schema drift (e.g. the user
    deployed code that needs ``clients.version`` against an unmigrated
    database) is reported in the body's ``schema`` field but does NOT
    flip the HTTP status — the app keeps serving via the runtime
    fallback in client_config.py, and we don't want to wake operators
    at 3am for a "please run a migration" task. The error log written
    by ``_probe_supabase`` is the primary signal for that.
    """
    supabase_up, schema_info = _probe_supabase()
    body = {
        'status': 'healthy' if supabase_up else 'degraded',
        'version': APP_VERSION,
        'uptime_seconds': int(time.time() - _STARTED_AT),
        'supabase_reachable': supabase_up,
        'schema': schema_info,
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
