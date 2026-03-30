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
import traceback
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from api.config import (
    DEFAULT_EXCEL_PATH, CLIENTS_CONFIG_PATH, MENU_RULES_CONFIG_PATH,
    HISTORY_LONG_PATH, HISTORY_WEEKS_PATH, API_HOST, API_PORT, DEBUG,
    MIN_NUM_DAYS, MAX_NUM_DAYS, MIN_TIME_LIMIT_SECONDS, MAX_TIME_LIMIT_SECONDS,
)
from src.preprocessor import ExcelReader, DataCleanser, ColumnMapper
from src.preprocessor.pool_builder import PoolBuilder
from src.constants import BASE_SLOT_NAMES, CONST_SLOTS, REPEATABLE_ITEM_BASES
from src.client import ClientConfigLoader
from src.client.client_config import DEFAULT_THEME_MAP, AVAILABLE_THEMES
from src.history import HistoryManager
from src.menu_rules import MenuRuleLoader
from src.solver.menu_solver import MenuSolver, SolverConfig
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
                _client_loader = ClientConfigLoader(CLIENTS_CONFIG_PATH)
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


def _build_history_context(df, client_name, start_date, num_days):
    """Shared helper to build history-based solver inputs."""
    hm = HistoryManager().load(HISTORY_LONG_PATH, HISTORY_WEEKS_PATH)
    hm = hm.filter_by_client(client_name)

    dates = _weekdays_from(start_date, num_days)
    banned = hm.banned_items_by_date(dates, const_slots=CONST_SLOTS,
                                      repeatable_items=REPEATABLE_ITEM_BASES)
    ricebread_items = set(
        df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
    ) if 'is_rice_bread' in df.columns else set()
    rb_ban = hm.ricebread_ban_by_date(dates, ricebread_items)
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
    """Return only the base slots the client actually uses (excluding constants)."""
    return [s for s in client_cfg.active_slots if s not in CONST_SLOTS
            and '__' not in s]


def _build_solver_config(df, client_cfg, start_date, num_days, time_limit):
    """Shared helper to build SolverConfig."""
    weekday_dates = _weekdays_from(start_date, num_days)
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


@app.route('/api/v1/clients', methods=['GET'])
def list_clients():
    try:
        loader = _get_client_loader()
        return jsonify({'success': True, 'clients': loader.client_names})
    except (FileNotFoundError, ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/plan', methods=['POST'])
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
        rules = _get_menu_rules()

        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()

        banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, num_days)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit)

        solver = MenuSolver(
            pools=pools,
            solver_config=cfg,
            menu_rules=rules,
            banned_by_date=banned,
            ricebread_ban_day=rb_ban,
            recent_sigs=recent_sigs,
        )

        week_plan, plan_dates = solver.solve()

        formatter = SolutionFormatter(week_plan, plan_dates, theme_map=client_cfg.theme_map or None)
        return jsonify({
            'success': True,
            'message': f'Menu plan generated for {client_name}',
            'solution': formatter.to_dict(),
        })

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
        rules = _get_menu_rules()

        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()

        banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, num_days)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit)

        # Convert string date keys to date objects
        base_plan = {}
        for d_str, slots in base_plan_raw.items():
            # slots may be nested dicts from to_dict() — extract item strings
            day_items = {}
            for slot_id, val in slots.items():
                if isinstance(val, dict):
                    day_items[slot_id] = val.get('item', val.get('item_base', ''))
                else:
                    day_items[slot_id] = str(val)
            base_plan[dt.date.fromisoformat(d_str)] = day_items

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

        # Convert string date keys to date objects
        week_plan = {}
        for d_str, slots in week_plan_raw.items():
            week_plan[dt.date.fromisoformat(d_str)] = slots

        dates = sorted(week_plan.keys())
        week_start = dt.date.fromisoformat(week_start_str)

        sig = HistoryManager.compute_week_signature(week_plan, dates, const_slots=CONST_SLOTS)

        hm = HistoryManager()
        hm.save(week_plan, dates, client_name, week_start, sig,
                HISTORY_LONG_PATH, HISTORY_WEEKS_PATH)

        return jsonify({'success': True, 'message': 'Plan saved to history'})

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except (FileNotFoundError, OSError) as e:
        logger.error("Save failed: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


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
            'menu_categories': loader.menu_categories,
            'clients': loader.client_names,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client-config/<client_name>', methods=['GET'])
def get_client_config(client_name):
    """Return the full editable config for one client."""
    try:
        loader = _get_client_loader()
        cfg = loader.get_client(client_name)
        cat_slots = loader.get_slots_for_menu_category(cfg.menu_category)
        return jsonify({
            'success': True,
            'name': cfg.name,
            'menu_category': cfg.menu_category,
            'active_base_slots': [s for s in cat_slots if s not in CONST_SLOTS],
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
    global _client_loader
    try:
        data = request.get_json()
        loader = _get_client_loader()

        if 'active_base_slots' in data:
            loader.update_client_slots(client_name, data['active_base_slots'])
        if 'slot_counts' in data:
            loader.update_client_slot_counts(client_name, data['slot_counts'])
        if 'theme_map' in data:
            loader.update_client_theme_overrides(client_name, data['theme_map'])
        if 'menu_category' in data:
            loader.update_client_menu_category(client_name, data['menu_category'])

        # Reload to pick up changes
        with _init_lock:
            _client_loader = None

        return jsonify({'success': True, 'message': f'Config updated for {client_name}'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Error updating client config: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client', methods=['POST'])
def create_client():
    """Create a new client."""
    global _client_loader
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        menu_category = data.get('menu_category', '')
        if not name:
            return jsonify({'success': False, 'error': 'name is required'}), 400
        if not menu_category:
            return jsonify({'success': False, 'error': 'menu_category is required'}), 400

        loader = _get_client_loader()
        loader.create_client(name, menu_category)

        with _init_lock:
            _client_loader = None

        return jsonify({'success': True, 'message': f'Client {name} created'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/client/<client_name>', methods=['DELETE'])
def delete_client(client_name):
    """Delete a client."""
    global _client_loader
    try:
        loader = _get_client_loader()
        loader.delete_client(client_name)

        with _init_lock:
            _client_loader = None

        return jsonify({'success': True, 'message': f'Client {client_name} deleted'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})


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
