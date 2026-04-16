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
import threading

from flask import Flask, request, jsonify
from flask_cors import CORS

from api.concurrency import solver_gate, get_stats as _solver_stats

from api.config import (
    DEFAULT_EXCEL_PATH, MENU_RULES_CONFIG_PATH,
    API_HOST, API_PORT, DEBUG,
    MIN_NUM_DAYS, MAX_NUM_DAYS, MIN_TIME_LIMIT_SECONDS, MAX_TIME_LIMIT_SECONDS,
)
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

app = Flask(__name__)
CORS(app)

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


def _build_history_context(df, client_name, start_date, weekday_dates):
    """Shared helper to build history-based solver inputs from Supabase."""
    import pandas as pd
    from src.db import get_supabase

    hm = HistoryManager()
    sb = get_supabase()
    long_resp = sb.table('menu_history').select('*').execute()
    weeks_resp = sb.table('week_signatures').select('*').execute()
    long_df = pd.DataFrame(long_resp.data) if long_resp.data else None
    weeks_df = pd.DataFrame(weeks_resp.data) if weeks_resp.data else None
    hm.load_from_dataframes(long_df, weeks_df)
    hm = hm.filter_by_client(client_name)

    banned = hm.banned_items_by_date(weekday_dates, const_slots=CONST_SLOTS,
                                      repeatable_items=REPEATABLE_ITEM_BASES)
    ricebread_items = set(
        df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
    ) if 'is_rice_bread' in df.columns else set()
    rb_ban = hm.ricebread_ban_by_date(weekday_dates, ricebread_items)
    recent_sigs = hm.recent_week_signatures(start_date)
    return banned, rb_ban, recent_sigs


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


@app.route('/api/v1/clients', methods=['GET'])
def list_clients():
    try:
        loader = _get_client_loader()
        return jsonify({'success': True, 'clients': loader.client_names})
    except (FileNotFoundError, ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/plan', methods=['POST'])
@solver_gate
def plan_menu():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        start_date_str = data.get('start_date')
        num_days = max(MIN_NUM_DAYS, min(MAX_NUM_DAYS, int(data.get('num_days', 5))))
        time_limit = max(MIN_TIME_LIMIT_SECONDS, min(MAX_TIME_LIMIT_SECONDS, int(data.get('time_limit_seconds', 240))))

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400

        loader = _get_client_loader()
        client_cfg = loader.get_client(client_name)

        df, pools = _get_menu_data()

        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()
        weekday_dates = _weekdays_from(start_date, num_days)

        rules, skip_cells = _rules_and_skip_for_client(client_name, weekday_dates)

        banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, weekday_dates)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit, weekday_dates)

        # Pre-solve pool validation
        pool_warnings = _validate_pools(pools, cfg, rules, weekday_dates, skip_cells=skip_cells)

        solver = MenuSolver(
            pools=pools,
            solver_config=cfg,
            menu_rules=rules,
            banned_by_date=banned,
            ricebread_ban_day=rb_ban,
            recent_sigs=recent_sigs,
            skip_cells=skip_cells,
        )

        week_plan, plan_dates = solver.solve()

        formatter = SolutionFormatter(week_plan, plan_dates, theme_map=client_cfg.theme_map or None)
        response = {
            'success': True,
            'message': f'Menu plan generated for {client_name}',
            'solution': formatter.to_dict(),
        }
        if pool_warnings:
            response['pool_warnings'] = pool_warnings
        return jsonify(response)

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Solver failed: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error("Unexpected error in plan: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.route('/api/v1/regenerate', methods=['POST'])
@solver_gate
def regenerate_cells():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        base_plan_raw = data.get('base_plan', {})
        replace_slots_raw = data.get('replace_slots', {})
        start_date_str = data.get('start_date')
        num_days = max(MIN_NUM_DAYS, min(MAX_NUM_DAYS, int(data.get('num_days', 5))))
        time_limit = max(MIN_TIME_LIMIT_SECONDS, min(MAX_TIME_LIMIT_SECONDS, int(data.get('time_limit_seconds', 240))))

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400
        if not base_plan_raw:
            return jsonify({'success': False, 'error': 'base_plan is required'}), 400
        if not replace_slots_raw:
            return jsonify({'success': False, 'error': 'replace_slots is required'}), 400

        loader = _get_client_loader()
        client_cfg = loader.get_client(client_name)

        df, pools = _get_menu_data()

        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()
        weekday_dates = _weekdays_from(start_date, num_days)

        rules, skip_cells = _rules_and_skip_for_client(client_name, weekday_dates)

        banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, weekday_dates)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit, weekday_dates)

        # Convert string date keys to date objects, extracting items from solution format
        base_plan = {
            dt.date.fromisoformat(d_str): _items_from_day(slots)
            for d_str, slots in base_plan_raw.items()
        }

        replace_mask = {}
        for d_str, slot_list in replace_slots_raw.items():
            replace_mask[dt.date.fromisoformat(d_str)] = set(slot_list)

        regen = MenuRegenerator(
            pools=pools,
            df=df,
            solver_config=cfg,
            menu_rules=rules,
            banned_by_date=banned,
            ricebread_ban_day=rb_ban,
            recent_sigs=recent_sigs,
            skip_cells=skip_cells,
        )

        week_plan, plan_dates = regen.regenerate(base_plan, replace_mask)

        formatter = SolutionFormatter(week_plan, plan_dates, theme_map=client_cfg.theme_map or None)
        return jsonify({
            'success': True,
            'message': f'Regenerated {sum(len(v) for v in replace_mask.values())} cells for {client_name}',
            'solution': formatter.to_dict(),
        })

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Regeneration failed: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error("Unexpected error in regenerate: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.route('/api/v1/save', methods=['POST'])
def save_plan():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        week_plan_raw = data.get('week_plan', {})
        week_start_str = data.get('week_start')

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400
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
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error("Unexpected save error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.route('/api/v1/editor-metadata', methods=['GET'])
def editor_metadata():
    """Return metadata needed by the customisation editor UI."""
    try:
        loader = _get_client_loader()
        return jsonify({
            'success': True,
            'base_slot_names': list(BASE_SLOT_NAMES),
            'const_slots': list(CONST_SLOTS),
            'default_theme_map': DEFAULT_THEME_MAP,
            'available_themes': AVAILABLE_THEMES,
            'clients': loader.client_names,
            'menu_categories': loader.menu_categories,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client-config/<client_name>', methods=['GET'])
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client-config/<client_name>', methods=['PUT'])
def update_client_config(client_name):
    """Update a client's configuration (slots, slot counts, theme overrides)."""
    try:
        data = request.get_json()
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client', methods=['POST'])
def create_client():
    """Create a new client."""
    try:
        data = request.get_json()
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client/<client_name>', methods=['DELETE'])
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
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/validate-pools', methods=['POST'])
def validate_pools():
    """Check pool sizes after theme filtering — returns warnings without running solver."""
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        start_date_str = data.get('start_date')
        num_days = max(MIN_NUM_DAYS, min(MAX_NUM_DAYS, int(data.get('num_days', 5))))

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400

        loader = _get_client_loader()
        client_cfg = loader.get_client(client_name)
        df, pools = _get_menu_data()
        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()
        weekday_dates = _weekdays_from(start_date, num_days)
        rules, skip_cells = _rules_and_skip_for_client(client_name, weekday_dates)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, 180, weekday_dates)

        warnings = _validate_pools(pools, cfg, rules, weekday_dates, skip_cells=skip_cells)
        return jsonify({'success': True, 'warnings': warnings})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', **_solver_stats()})


@app.route('/')
def root():
    return jsonify({
        'name': 'Ikigai Masala Menu Planning API',
        'version': '2.0',
        'docs': '/api/v1/clients',
    })


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.run(host=API_HOST, port=API_PORT, debug=DEBUG)
