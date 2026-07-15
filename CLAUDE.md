# CLAUDE.md — Repo Navigation Map

Purpose: let a Claude session locate code without reading whole files. Paths are relative to this file. `ikigai_masala-main/` is the only project.

> Keep this file in sync when you add/rename/move modules. If you change a path or symbol referenced below, update the corresponding line.

---

## 1. Top-level layout

```
ikigai_masala-main/          active project (Indian menu planner)
├── app.py                   Streamlit frontend; auto-spawns Flask backend
├── api/                     Flask REST backend
├── src/                     solver + rules + preprocessor + client/history/db
├── ui/                      Streamlit-side API client & formatters
├── customisation/           Streamlit editor UIs for per-client config
├── data/                    menu ontology (xlsx) + rule configs (json)
├── scripts/                 Supabase seeders + SQL schema
├── tests/                   pytest suite
├── pytest.ini, requirements.txt
└── ARCHITECTURE.md, QUICK_START.md, USAGE_GUIDE.md, OUTPUT_FORMAT.md
```

---

## 2. Entry points

| Command | File | What it does |
|---|---|---|
| `streamlit run app.py` | `ikigai_masala-main/app.py` | UI; auto-starts Flask on port 5000 |
| `flask --app api.app run` | `ikigai_masala-main/api/app.py` | API standalone |
| `python scripts/seed_supabase.py` | `ikigai_masala-main/scripts/seed_supabase.py` | seed clients from `data/configs/clients.json` |
| `pytest` | `ikigai_masala-main/pytest.ini` | run tests |

Secrets: `SUPABASE_URL`, `SUPABASE_KEY` in env or `.streamlit/secrets.toml`.

---

## 3. API surface (all in `ikigai_masala-main/api/app.py`)

| Method | Route | Purpose |
|---|---|---|
| GET  | `/api/v1/clients` | list clients |
| POST | `/api/v1/plan` | generate full menu |
| POST | `/api/v1/regenerate` | regenerate selected cells |
| POST | `/api/v1/save` | persist plan → history |
| GET  | `/api/v1/editor-metadata` | slot/theme metadata for editor |
| GET  | `/api/v1/client-config/<name>` | fetch client config |
| PUT  | `/api/v1/client-config/<name>` | update client config |
| POST | `/api/v1/client` | create client |
| DELETE | `/api/v1/client/<name>` | delete client |
| POST | `/api/v1/validate-pools` | dry-run pool build |
| GET  | `/api/v1/health` | health check |

Helpers:
- `api/concurrency.py` — `@solver_gate` queue; caps active solves (dynamic CP-SAT workers).
- `api/config.py` — path constants, day/time limits.
- `api/rate_limit.py` — per-IP token-bucket throttle on `/plan` + `/regenerate`.

No authentication: every endpoint is public (the auth feature was removed).

---

## 4. `src/` module map

### 4.1 `src/solver/` — CP-SAT solver
| File | Key symbols | Role |
|---|---|---|
| `menu_solver.py` | `MenuSolver.solve`, `SolverConfig`, `_Cell` | cell-based CP-SAT: one bool var per (day, slot, candidate) |
| `solver_context.py` | `SolverContext` | runtime bundle passed to rules |
| `solution_formatter.py` | `SolutionFormatter.to_dict` | solver output → API JSON |
| `regenerator.py` | `MenuRegenerator.regenerate`, `similarity_score` | locks fixed cells, re-solves selected ones |
| `_helpers.py` | `weekday_type_for_config`, `strip_color_suffix`, `items_from_day` | shared utilities |

### 4.2 `src/menu_rules/` — constraint system
Two-phase: `pre_filter_pool()` (cheap removals before CP-SAT vars), `apply()` (hard/soft constraints on model), `get_objective_terms()` (penalties/bonuses).

| File | Kind | Role |
|---|---|---|
| `base_menu_rule.py` | abstract | parent class |
| `menu_rule_loader.py` | loader | deserialize `data/configs/indian_menu_rules.json` |
| `cuisine_menu_rule.py` | hard | min cuisine variety |
| `color_variety_menu_rule.py` | hard | min distinct colors/day |
| `color_pairing_menu_rule.py` | hard | max same-color/day |
| `unique_items_menu_rule.py` | hard | no repeats within horizon |
| `coupling_menu_rule.py` | hard | item dependencies (e.g. curry↔rice) |
| `curd_side_menu_rule.py` | hard | fill curd side slot |
| `premium_menu_rule.py` | hard | min/max premium items |
| `welcome_drink_color_menu_rule.py` | hard | welcome drink color |
| `theme_day_menu_rule.py` | soft | prefer theme-matched items per day |
| `theme_slot_filter_rule.py` | pre-filter | drop non-theme items on theme-heavy days |
| `theme_fallback_penalty_rule.py` | soft | penalty when theme cannot be met |
| `theme_starter_preference_rule.py` | soft | bonus for theme-matching starters |
| `item_cooldown_menu_rule.py` | pre-filter | ban recently used items |
| `week_signature_cooldown_menu_rule.py` | soft | avoid recent week signatures |
| `ricebread_gap_menu_rule.py` | pre-filter | enforce N-day gap |
| `nonveg_biryani_weekly_rule.py` | pre-filter | ≤1 nonveg biryani/week |
| `nonveg_dry_preference_rule.py` | pre-filter | prefer dry nonveg certain days |
| `ingredient_ban_rule.py` | pre-filter | per-client banned ingredients (case-insensitive exact match on `key_ingredient`) |
| `item_frequency_rule.py` | CP-SAT | per-client weekly frequency cap via selector (flag/sub_category/item/key_ingredient) |
| `slot_day_restriction_rule.py` | skip-cells | per-client: skip a slot on certain weekdays (e.g. no nonveg_main on Tue/Thu) |

### 4.3 `src/preprocessor/` — data pipeline
Flow: `ExcelReader.read` → `ColumnMapper.apply` → `DataCleanser.clean` → `PoolBuilder.build_pools` → `ThemeFilter` (optional).

| File | Key symbols |
|---|---|
| `excel_reader.py` | `ExcelReader.read` |
| `column_mapper.py` | `ColumnMapper.apply` (alias detection, derived `key_eff`) |
| `data_cleanser.py` | `DataCleanser.clean` |
| `pool_builder.py` | `PoolBuilder.build_pools`, `_base_slot`, `_expand_slots_in_order` (expands `veg_dry` → `veg_dry__1, veg_dry__2`) |
| `theme_filter.py` | `ThemeFilter` |

### 4.4 `src/client/` — client config (Supabase, live reads)
- `client_config.py` → `ClientConfig` (dataclass), `ClientConfigLoader`, plus counter helpers `default_counter`, `normalize_counter`, `MAX_COUNTERS`.
- No in-memory cache; every read hits Supabase. Supabase tables: `clients`, `menu_categories`, `slot_count_overrides`, `theme_overrides`, `app_settings`.
- Default day themes: Mon=mix, Tue=chinese, Wed=biryani, Thu=south, Fri=north.
- **Cuisine counters** (no separate table): a client is `single` (one counter, classic) or `multi` (N counters, each with its own categories/frequency/theme_map). Stored in the single `clients.counters` JSONB column — `[]` for single clients (config read from the legacy `menu_category`/`slot_count_overrides`/`theme_overrides` tables, **no duplicated data**), the full ordered list for multi. Mode is *derived* (`multi` ⇔ `counters` non-empty). `get_counters_for_client` / `set_counters_for_client` read/write the canonical counter shape `{name, categories, slot_counts, theme_map}`. The **primary** counter (index 0) is always mirrored into `menu_category` + `slot_count_overrides` + `theme_overrides` so `MenuSolver` keeps working unchanged regardless of mode. All counter methods degrade gracefully (log + fall back to single) when the `clients.counters` column hasn't been migrated in.

### 4.5 `src/history/`
- `history_manager.py` → `HistoryManager.banned_items_by_date`, `.ricebread_ban_by_date`, `.recent_week_signatures`.
- Tables: `menu_history` (item×date), `week_signatures` (weekly hash).

### 4.6 `src/` top-level
- `constants.py` — `BASE_SLOT_NAMES`, `CONST_SLOTS`, `DISPLAY_SLOT_NAME`.
- `db.py` — `get_supabase()` (thread-safe singleton).

---

## 5. UI layer

### `ui/`
- `api_client.py` → `MenuApiClient` (HTTP wrapper used by Streamlit).
- `formatters.py` → `format_item_html`, `THEME_TAG_COLORS`, `THEME_ICONS`.

### `customisation/` (Streamlit editors) — Pulse light theme
- `main.py` → `render_customisation_editor` (dispatcher). Stepped flow: (1) select/create client → (2) Single vs Multi Cuisine Counter (+ number of counters) → (3) per-counter config. Builds the `counters` payload for `POST /client` and `PUT /client-config`.
- `counter_editor.py` → `render_counter_editor` — composes the 3 panels for one counter; returns `{name, categories, slot_counts, theme_map}`.
- `slot_editor.py`, `multi_slot_editor.py`, `theme_editor.py` — per-concern panels (categories / frequency / day themes), counter-scoped via a `key_prefix`.
- `pulse.py` → `PULSE_EDITOR_CSS`, `PULSE_THEME_COLORS` — the light (OP Lens) design tokens; injected by the editor. `app.py` skips the dark `ui/styles.py` `STYLES` while `view == "editor"`.

---

## 6. Data & config files

| Path | Purpose |
|---|---|
| `ikigai_masala-main/data/raw/menu_items.xlsx` | master ontology (~530 items; cols: item, course_type, sub_category, cuisine_family, item_color, key_ingredient, is_premium_veg, is_chinese_*, is_*_biryani, …) |
| `ikigai_masala-main/data/configs/indian_menu_rules.json` | rule config consumed by `MenuRuleLoader` |
| `ikigai_masala-main/data/configs/client_rules.json` | per-client custom rules (keyed by client name); loaded by `MenuRuleLoader.load_for_client()` |
| `ikigai_masala-main/data/configs/clients.json` | legacy client list; real source is Supabase |
| `ikigai_masala-main/scripts/create_tables.sql` | clients + config schema (incl. `clients.counters` JSONB for multi-cuisine counters) |
| `ikigai_masala-main/scripts/create_history_tables.sql` | history + signatures schema |

---

## 7. Call graphs (typical flows)

### Generate menu
```
Streamlit app.py
  → MenuApiClient.plan()  [ui/api_client.py]
  → POST /api/v1/plan     [api/app.py]
    → @solver_gate                                      [api/concurrency.py]
    → ClientConfigLoader.get_client()                   [src/client/client_config.py]
    → ExcelReader → ColumnMapper → DataCleanser → PoolBuilder  [src/preprocessor/]
    → MenuRuleLoader.load_from_file()                   [src/menu_rules/menu_rule_loader.py]
    → HistoryManager (Supabase)                         [src/history/history_manager.py]
    → MenuSolver.solve()                                [src/solver/menu_solver.py]
        for each (day, slot): rule.pre_filter_pool()
        build CP-SAT model, add rule.apply() constraints
        optimize sum(get_objective_terms())
    → SolutionFormatter.to_dict()                       [src/solver/solution_formatter.py]
  ← JSON → Streamlit table
```

### Regenerate cells
```
POST /api/v1/regenerate  [api/app.py]
  → MenuRegenerator.regenerate(base_plan, replace_mask)  [src/solver/regenerator.py]
    lock untouched cells, re-run MenuSolver.solve()
    rank by similarity_score()
```

### Save to history
```
POST /api/v1/save  [api/app.py]
  → HistoryManager.save() → Supabase (menu_history, week_signatures)
```

### Edit client config
```
Streamlit customisation/* → PUT /api/v1/client-config/<name>  [api/app.py]
  → ClientConfigLoader.update_*() → Supabase
  (live reads elsewhere; no restart)
```

---

## 8. Tests (`ikigai_masala-main/tests/`)

| File | Target |
|---|---|
| `conftest.py` | fixtures (project_root, sample data path) |
| `test_api.py` | Flask endpoints |
| `test_solver.py` / n/a — see `test_rule_constraints.py` | solver + constraint integration |
| `test_menu_rules.py`, `test_rule_constraints.py` | rule behavior |
| `test_menu_rule_loader.py` | JSON deserialization |
| `test_pool_builder.py` | pool & slot expansion |
| `test_column_mapper.py` | alias/normalize/derived cols |
| `test_theme_filter.py` | theme filtering |
| `test_prefilter_integration.py` | multi-rule pre-filter chain |
| `test_history_manager.py` | cooldowns & signatures |
| `test_client_config.py` | Supabase-backed config |
| `test_formatters.py`, `test_helpers.py`, `test_solution_formatter.py` | UI/utility layers |

Run: `pytest` from `ikigai_masala-main/`.

---

## 9. Non-obvious design notes

1. **Cell-based CP-SAT**: one bool var per (day, slot, candidate) — enables per-item penalties and similarity-driven regeneration.
2. **Two-phase rules**: pre-filter eliminates items before the model is built (fast), then `apply()` adds CP-SAT constraints. When writing a new rule, decide which phase fits.
3. **No config cache**: `ClientConfigLoader` reads Supabase on every call — live edits, no restart. Don't add caching without thinking through invalidation.
4. **Dynamic worker allocation** in `api/concurrency.py`: 1 active solve → 9 workers; 2 active → 5 each. Tuned for ~1 GB RAM.
5. **Theme dispatch**: global weekday→theme map, per-client overridable via `theme_overrides` table. Solver honors it via `theme_*` rules.
6. **History split**: `menu_history` is item-level; `week_signatures` is a weekly hash for week-level cooldowns.
7. **Supabase is the source of truth** for clients, history, overrides — Flask and Streamlit both read it directly.
8. **Slot expansion**: base slot names like `veg_dry` get expanded to indexed slots `veg_dry__1`, `veg_dry__2` in `PoolBuilder._expand_slots_in_order`. Rules operate on expanded names.
9. **Per-client custom rules**: `data/configs/client_rules.json` stores extra rules per client (keyed by client name). Loaded fresh per request by `MenuRuleLoader.load_for_client()`. Three types: `ingredient_ban` (pre-filter), `item_frequency` (CP-SAT cardinality cap), `slot_day_restriction` (skip slot on certain weekdays via `skip_cells` kwarg on `MenuSolver`). Generic rules are cached globally; per-client rules are appended per request.

---

## 10. Dependencies

Solver `ortools` · data `pandas numpy openpyxl` · web `flask flask-cors requests` · db `supabase python-dotenv` · UI `streamlit` · tests `pytest pytest-cov`.

---

## 11. Editing rules for this file

- When adding a new rule file under `src/menu_rules/`, append a row to §4.2.
- When adding an endpoint in `api/app.py`, append a row to §3.
- When moving or renaming a module, update its row in §4 and any mention in §7.
- Keep rows to one line. This file is optimized for fast scanning, not prose.
