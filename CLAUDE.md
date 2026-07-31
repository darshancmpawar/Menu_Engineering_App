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
├── data/                    per-city menu ontologies (raw/city_items/*.xlsx) + rule configs (configs/city_rules/*.json)
├── scripts/                 Supabase seeders + SQL schema
├── tests/                   pytest suite
├── pytest.ini, requirements.txt
├── README.md                overview + quick start
└── docs/                    setup.md, architecture.md, api.md, operations.md, client_logics.md, pune_rulebook.md
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
| GET  | `/api/v1/clients` | list clients (`clients` = names; `clients_detail` = `[{name, city}]` for the sidebar city filter) |
| POST | `/api/v1/plan` | generate full menu (optional `counter_index` picks which counter to solve; optional `alternates` 0..`MAX_ALTERNATES`=4 → ranked near-optimal distinct menus in an `alternates` list, primary stays in `solution`; response carries `counter_mode`/`counter_count`/`counter_index`/`counter_name`; each item carries `is_nonveg`) |
| POST | `/api/v1/regenerate` | regenerate selected cells (optional `counter_index`; items carry `is_nonveg`) |
| POST | `/api/v1/save` | persist plan → history (single `week_plan`, or multi `counters: [{name, week_plan}]` → nested `menu_history`) |
| GET  | `/api/v1/editor-metadata` | slot/theme/**city** metadata for editor (`available_cities`, `default_off_slots`, `default_item_cooldown_days`, `available_client_pools`, `client_pools_by_city`). Optional `?city=` scopes `available_client_pools` to that city's item list; without it the list is the union across cities (a superset, so no valid token is hidden) |
| POST | `/api/v1/pool-preview` | F5: eligible distinct item count + category-wise counts for a set of `source_pools` (common always included). Optional `city` selects which city's item list is counted |
| GET  | `/api/v1/client-config/<name>` | fetch client config (incl. `city`, `serve_weekends`, `item_cooldown_days`, `source_pools`) |
| PUT  | `/api/v1/client-config/<name>` | update client config (accepts `city`, `serve_weekends`, `item_cooldown_days`, `source_pools`) |
| POST | `/api/v1/client` | create client (accepts `city`, `serve_weekends`, `item_cooldown_days`, `source_pools`) |
| DELETE | `/api/v1/client/<name>` | delete client |
| POST | `/api/v1/diagnose` | dry-run pre-flight: run every rule's `diagnose()` + built-in pool/colour diagnostics; returns structured `rule_diagnostics` + `summary` + `counter_index`/`counter_name`/`counter_count` (the same pass `/plan` runs as its 422 gate). **Honours `counter_index`** — it used to build its inputs from the primary counter regardless, so every multi-counter client got a clean bill of health for counter 0 while the counter being planned was unsatisfiable |
| GET  | `/api/v1/saved-plan` | fetch a previously saved plan from history |
| GET  | `/api/v1/metrics` | Prometheus-style metrics scrape |
| GET  | `/api/v1/health` | health check |

Helpers:
- `api/concurrency.py` — `@solver_gate` queue; caps active solves (dynamic CP-SAT workers).
- `api/config.py` — path constants, day/time limits, **per-city ontology resolution** (`city_excel_path`, `city_required_slots`, `CITY_ITEMS_DIR`, `DEFAULT_ONTOLOGY_CITY`).
- `api/rate_limit.py` — per-IP token-bucket throttle on `/plan` + `/regenerate`.

Hardening (all opt-in / non-breaking):
- `MAX_CONTENT_LENGTH_BYTES` (default 2 MB) caps request bodies; an over-limit
  body is rejected in `before_request` so the status is 413 rather than a 500
  swallowed by an endpoint's broad `except Exception`.
- `API_WRITE_TOKEN` (env, unset by default) gates the mutating endpoints via
  `@require_write_token` — `X-API-Key` or `Authorization: Bearer`. Unset means
  the API behaves exactly as before (open), so this changes nothing until an
  operator opts in. Reads are never gated.
- Rate-limit buckets: `plan` 10/min, `regenerate` 20/min, `write` 30/min
  (save / create / delete / config PUT), `diagnose` 20/min (also `/pool-preview`).

Beyond the optional write token there is no per-user authentication: reads are
public and the deployment relies on the network perimeter.

---

## 4. `src/` module map

### 4.1 `src/solver/` — CP-SAT solver
| File | Key symbols | Role |
|---|---|---|
| `menu_solver.py` | `MenuSolver.solve`, `SolverConfig`, `_Cell` | cell-based CP-SAT: one bool var per (day, slot, candidate) |
| `solver_context.py` | `SolverContext` | runtime bundle passed to rules |
| `solution_formatter.py` | `SolutionFormatter.to_dict` | solver output → API JSON (tags each item `is_nonveg` from a passed nonveg name-set) |
| `regenerator.py` | `MenuRegenerator.regenerate`, `similarity_score` | locks fixed cells, re-solves selected ones |
| `_helpers.py` | `weekday_type_for_config`, `strip_color_suffix`, `items_from_day`, `cell_is_skipped` | shared utilities. `cell_is_skipped(skip_cells, date, slot_id)` is the single skip predicate for `MenuSolver._build_cells` + `MenuRegenerator`: `skip_cells` holds `(date, base_slot)` entries (skip every expansion — what `slot_day_restriction` emits) **and** `(date, slot_id)` entries (skip one expansion — how a client constant pins `nonveg_main__2` while `__1` stays solved) |

### 4.2 `src/menu_rules/` — constraint system
Two-phase: `pre_filter_pool()` (cheap removals before CP-SAT vars), `apply()` (hard/soft constraints on model), `get_objective_terms()` (penalties/bonuses).

| File | Kind | Role |
|---|---|---|
| `base_menu_rule.py` | abstract | parent class |
| `menu_rule_loader.py` | loader | deserialize a rules JSON; `load_for_city(city)` resolves `data/configs/city_rules/<city>.json` + its `extends` chain (override by rule `name`, `disable` list), falling back to `DEFAULT_CITY`; `load_for_client()` merges per-client `{disable, rules, constant_items}` over the city list by name (legacy list form still works) |
| `cuisine_menu_rule.py` | hard | min cuisine variety |
| `color_rules.py` | hard + params | `ColorPairingMenuRule` (two named slots may not share a colour on a day) · `WelcomeDrinkColorMenuRule` (no repeat welcome-drink colour on adjacent days) · **`ColorVarietyMenuRule`** — adds no constraints; it carries the *per-city numbers* for the built-in colour block (`min_distinct_per_day`(`_chinese`/`_biryani`), `max_same_color_per_day`, `max_same_color_reach`, `max_colors_at_reach`, `ignore_rice_gravy_color_diff_on_chinese_day`), read by `api._build_solver_config` via `solver_overrides()` against the `_RULE_OVERRIDABLE_CFG_FIELDS` allow-list. Bangalore wants 4 distinct with one colour allowed to reach 3 (the SolverConfig defaults, so it ships no such rule); Pune's rulebook R1/R2 want 3 distinct and a flat cap of 2, which is why the numbers had to leave `SolverConfig` |
| `unique_items_menu_rule.py` | hard | no repeats within horizon |
| `coupling_menu_rule.py` | hard | deep-fried rice/bread/veg-dry family (rulebook 34-42): liquid rice ⇒ deep-fried veg_dry/starter (scoped to active slots); deep-fried veg_dry ⇒ rice-bread + liquid rice; rice-bread ⇒ liquid rice; dosa bread + active nonveg ⇒ SI chicken gravy (availability-guarded); rice-bread & deep-fried veg_dry each ≤1 day/wk. All conditional upper bounds (never mandates, never INFEASIBLE). The old rice-bread⇔deep-fried-starter link is retired (rulebook §5) |
| `curd_side_menu_rule.py` | hard | fill curd/raita slot (biryani/pulao→raita, else→curd); the `curd_side` slot is displayed as "Curd / Raita" |
| `premium_menu_rule.py` | hard | broad premium min/max/day cap — **retired from the default ruleset** (rulebook §5/45-46); class kept for configs that still want it. Default now uses two `selector_frequency` exact-1 rules: `premium_veg_gravy_exactly_one` (`is_premium_gravy`@veg_gravy) + `premium_veg_dry_exactly_one` (`is_premium_veg_dry`@veg_dry) |
| `welcome_drink_color_menu_rule.py` | hard | welcome drink color |
| `welcome_drink_buttermilk_rule.py` | hard | buttermilk (`is_buttermilk`) on exactly N (default 2) welcome-drink days, solver-chosen, non-consecutive |
| `theme_day_menu_rule.py` | soft | prefer theme-matched items per day |
| `theme_slot_filter_rule.py` | pre-filter | drop non-theme items on theme-heavy days (chinese/**continental**/biryani/south/north); config `exempt_slots` unioned with `EXEMPT_FROM_CUISINE`. **Cuisine exclusivity**: chinese/continental dishes appear ONLY on their own theme day, and only for cuisine-main slots (`_CUISINE_MAIN_SLOTS` = rice/veg_gravy/veg_dry/starter/nonveg_main); universal slots keep incidental tags. On a continental day the continental veg is the **gravy** — `veg_dry` is never continental (stays a normal Indian dish), so a continental day = continental rice/starter/nonveg/gravy + one Indian veg_dry |
| `theme_fallback_penalty_rule.py` | soft | penalty when theme cannot be met |
| `theme_starter_preference_rule.py` | soft | bonus for theme-matching starters |
| `item_cooldown_menu_rule.py` | pre-filter | ban recently used items |
| `week_signature_cooldown_menu_rule.py` | soft | avoid recent week signatures |
| `ricebread_gap_menu_rule.py` | pre-filter | enforce N-day gap |
| `nonveg_biryani_weekly_rule.py` | pre-filter | ≤1 nonveg biryani/week |
| `nonveg_dry_preference_rule.py` | pre-filter | prefer dry nonveg on the 2nd nonveg slot — **retired from the default ruleset** (superseded by the `slot_composition` 2-nonveg pair, which it conflicted with on chinese/biryani days); class kept for configs that still want the simple slot-2 dry heuristic |
| `ingredient_ban_rule.py` | pre-filter | per-client banned ingredients (case-insensitive exact match on `key_ingredient` **and** `primary_protein` — e.g. a mushroom ban catches both fields) |
| `item_frequency_rule.py` | CP-SAT | per-client weekly frequency cap via selector (flag/sub_category/item/key_ingredient/primary_protein) |
| `selector_frequency_rule.py` | CP-SAT | **generic Phase-1 rule type**: selector-driven horizon count (max/min/exact days, day-level) + `non_consecutive` + `daily_max` (per-day occurrence cap) + **`allowed_day_types`** (forbid the selector outright on days of other themes; skipped when the ban would empty a cell). `allowed_day_types` is what keeps a themed dish on its themed day — a `mix` day is not narrowed by the theme filter at all, so a counter could serve biryani on Monday and none on its actual biryani day. Selector = flag/sub_category/item/key_ingredient/primary_protein/course_type/cuisine_family. min/exact auto-capped to placeable (availability + non-consecutive aware) so it never forces INFEASIBLE. Config-driven in the per-city rulesets (`data/configs/city_rules/<city>.json`) |
| `attribute_grouping_rule.py` | CP-SAT | **generic Phase-3 rule type**: group a slot's candidates by an attribute (`group_by` = any column, e.g. item_color/key_ingredient) and constrain each distinct value: `non_consecutive` (same value not on adjacent days — rulebook 79 dal-colour) and/or `max_per_group` (each value ≤N days/horizon — rulebook 82 sambar key-ingredient, an empty-history stand-in for the 15-day rolling window). Caps only; never INFEASIBLE on its own |
| `soft_preference_rule.py` | CP-SAT soft | **generic Phase-4 soft rule type** (objective-only, never INFEASIBLE): `mode` = `different_day` (penalise two selectors same day — premiums apart, #3), `avoid_consecutive` (penalise selector on adjacent days — regional nonveg/rice, #14-17), `avoid_attribute_repeat` (penalise a slot repeating an attribute value — key-ingredient variety, #1). `priority` (high/medium/low) selects a weight from `constants.OBJECTIVE_TIER_WEIGHTS` (theme 1e15 > high 1e12 > medium 1e9 > low 1e6, each ~1000× the next) so soft rules apply lexicographically — a higher-priority rule is never sacrificed for a pile of lower ones (rulebook §7). `weight` overrides. Hard rules stay guaranteed (they're constraints); random tie-break (~1e3/cell) sits below LOW |
| `slot_composition_rule.py` | CP-SAT | **generic Phase-3 rule type**: composes a slot family *per day*, switchable on the day's theme. `base_slot` + a self-gate on the counter's configured slot count: **`min_slot_count`/`max_slot_count` (preferred, a range)** or legacy `requires_slot_count` (exact). The exact form silently excluded every counter serving *more* than the stated number — a 3-dish nonveg counter got no composition at all, so its biryani-theme days came back with no biryani while non-biryani days got two; the shipped ruleset uses the range form and a test pins that. The range also keeps two compositions off the same slot family: `nonveg_main_daily_pair` is `2-4` and `nonveg_main_five_dish` is `5+`, so a 5-dish station (biryani + gravy + dry + kebab + egg daily) composes without the pair also demanding cells. A test asserts at most one nonveg composition is active per slot count. `days_forced_by_composition()` exports what a composition mandates so frequency caps can detect the contradiction. `components` (default) + `components_by_theme` (per-theme override), each a `{selector, count}` list using the `selector_frequency` grammar; per day it adds `sum(matching vars) >= count` (≥, so two `count:1` components across two cells = exactly one of each, but a missing component drops instead of forcing INFEASIBLE). `count` also capped to per-day availability (auto-relax). Base ruleset uses it for the 2-nonveg pair (biryani day → biryani+gravy, chinese day → chinese+gravy, else dry+gravy) and the 2-veg_dry pair (north+south). Needs the theme-filter union (note 16) so the paired regional gravy survives on chinese/biryani days |
| `slot_day_restriction_rule.py` | skip-cells | per-client: skip a slot on certain weekdays (e.g. no nonveg_main on Tue/Thu) |
| `repeatable_items_rule.py` | declarative | **some dishes in a slot are staples, not variety**: `base_slot` + `selector` (+ `exclude`) marks matching items exempt from `unique_items` **and** from the item-cooldown history ban. Permits repetition; never forces it (that's `fixed_daily_item`). Same `repeatable_item_flags()` hook, so `MenuSolver._declared_repeatable()` → `context['extra_repeatable']` feeds both consumers from one declaration. Exists because `REPEATABLE_ITEM_FLAGS_BY_SLOT` is global and staple-ness is regional: Pune's rulebook R36 says plain chapati/phulka may run on consecutive days (its bread pool is those two dishes, so without the exemption the 20-day cooldown empties the slot in week 2), while a Bangalore bread slot rotating naans and parathas wants the no-repeat rule kept |
| `fixed_daily_item_rule.py` | CP-SAT | **one slot's dish is the SAME every day**: `base_slot` + `selector` (+ optional `exclude`). Encoded as one bool per matching candidate plus `sum(that item's vars on day d) == z_i`, so an item is used on every day or none; an item unavailable on some day is excluded rather than made INFEASIBLE. Also exposes `repeatable_item_flags()`, which `MenuSolver._declared_repeatable()` collects into `context['extra_repeatable']` and `unique_items` folds into its repeatable set — so the rule creating a repetition and the rule forbidding one cannot disagree, and the exemption stays scoped to the client that asked for it (unlike the ontology-wide `REPEATABLE_ITEM_FLAGS_BY_SLOT`). L&T's non-veg station uses it for the daily egg; its kebab is already fixed by having one eligible item |

### 4.3 `src/preprocessor/` — data pipeline
Flow: `ExcelReader.read` → `ColumnMapper.apply` → `DataCleanser.clean` → `PoolBuilder.build_pools`. Theme filtering is **not** here — it lives in the rules layer (`src/menu_rules/theme_rules.py::ThemeSlotFilterRule`) so it can run per (date, slot) with the day's theme.

| File | Key symbols |
|---|---|
| `excel_reader.py` | `ExcelReader.read` |
| `column_mapper.py` | `ColumnMapper.apply` (alias detection, derived `key_eff`) |
| `data_cleanser.py` | `DataCleanser.clean` |
| `pool_builder.py` | `PoolBuilder.build_pools(df, required_slots=None)`, `_base_slot`, `_expand_slots_in_order` (expands `veg_dry` → `veg_dry__1, veg_dry__2`), `_nonveg_mask` (build_pools drops non-veg items from every slot except `nonveg_main`). `required_slots` = base slots that must come out non-empty; `None` means every mandatory one (right for a whole-product ontology), a **city** ontology passes its declared set from `city_items/ontology_categories.json`, `set()` skips the check |
| `client_pool_filter.py` | `parse_client_pools`, `get_active_pools`, `item_is_eligible`, `filter_eligible`, `available_pool_tokens` — F5 client-based item-pool eligibility (pure) |

### 4.4 `src/client/` — client config (Supabase, live reads)
- `client_config.py` → `ClientConfig` (dataclass, incl. `serve_weekends`), `ClientConfigLoader`, plus counter helpers `default_counter`, `normalize_counter`, `MAX_COUNTERS`. Per-category frequency is bounded by `_MIN_SLOT_COUNT`/`_MAX_SLOT_COUNT` (1..**5**); `customisation/multi_slot_editor.py` imports both so the editor can never offer a value the loader would clamp. The ceiling was 3, which made a real counter unconfigurable — a non-veg station serving biryani + gravy + dry + kebab + egg needs 5 `nonveg_main` slots and the editor answered "outside the allowed range". City: `AVAILABLE_CITIES` + `normalize_city`; a client's `city` is a plain `clients.city` column (not per-counter). `serve_weekends` is a plain `clients.serve_weekends` bool (Sat/Sun coverage). `item_cooldown_days` (`clients.item_cooldown_days`, nullable; None = `DEFAULT_ITEM_COOLDOWN_DAYS`=20) overrides the item-cooldown window per client. All read/written via `get_client_city`/`set_client_city`/`get_client_serve_weekends`/`set_client_serve_weekends`/`get_client_item_cooldown_days`/`set_client_item_cooldown_days`/`create_client(...)`. `AVAILABLE_THEMES` includes `continental` + the weekly-alternating `chinese_continental`.
- No in-memory cache; every read hits Supabase. Reads are **consolidated**: `get_client_row(name)` selects every config column in one query and `api.app._client_row()` memoises it on Flask's `g` for the request, so `GET /client-config` costs 1 round trip (was 7) and `/plan` 2 (was 6). `get_client_configs_from_row(name, row)` builds the per-counter `ClientConfig` list from an already-read row. Writes are **atomic**: `update_client_atomic(name, expected_version, fields)` applies every field plus the version bump in ONE conditional `UPDATE` (`WHERE name=? AND version=?`), replacing a bump-then-N-setters sequence in which a validation failure part-way left the row half-written with the version already incremented. `normalize_counters_for_write()` / `primary_counter_patch()` are the write-free validation halves used to check the whole payload before anything is persisted. `create_client()` is validate-then-insert for the same reason: it takes `working_days` and `source_pools` directly so they are part of the one INSERT — they used to be applied by follow-up setters *after* the row existed, so a rejected pool token answered 400 while leaving a real client behind with no pools (and the retry then failed on the duplicate name). There is no standalone version-bump helper: bumping `version` separately from the fields it guards is the ordering that bug came from, so `update_client_atomic` is the only write path.
- `ClientConfig.counter_name` records which counter a config came from, so per-counter rule overrides can be scoped. Supabase tables (consolidated to 4): `clients`, `app_settings`, `menu_history`, `week_signatures`.
- **F5 client item pools**: `clients.source_pools` (JSONB, nullable) stores the ontology `client`-column pool tokens this client draws from; `common` is implicit. `get_client_source_pools` returns `None` (column missing → callers use the full ontology), `[]` (unset → common-only), or the token list. `set_client_source_pools` normalizes/dedupes and strips `common`.
- Default day themes: Mon=mix, Tue=chinese, Wed=biryani, Thu=south, Fri=north.
- **Client config is one JSON document.** `clients.counters` (JSONB) is the single source of truth — an ordered, non-empty list `[{name, categories, slot_counts, theme_map}, …]`. `counters[0]` is the **primary** counter that `MenuSolver` plans from (`get_client` derives `ClientConfig` from it); extra entries are additional cuisine stations. `get_client_configs` yields one `ClientConfig` per counter — the API solves each independently (client-orchestrated: the planner calls `/plan` once per counter with `counter_index`), and the planner renders one table per counter (tabs) with per-counter regenerate/clear + a shared save/download. Mode is *derived*: `single` ⇔ 1 counter, `multi` ⇔ 2+. `get_counters_for_client` / `get_counter_setup` / `set_counters_for_client` / `update_primary_counter` read/write it. The old normalized `menu_categories` / `slot_count_overrides` / `theme_overrides` tables were folded into this column (premature normalization — config was always read/written per-client, never cross-client). The loader keeps a guarded `_legacy_primary_counter` fallback for a database that hasn't run `scripts/setup_all.sql` yet.

### 4.5 `src/history/`
- `history_manager.py` → `HistoryManager.banned_items_by_date`, `.ricebread_ban_by_date`, `.recent_week_signatures`, `.explode_history_rows`.
- Tables: `menu_history` — **one JSONB row per (client, service_date)**, `menu = {slot: item_base}` (PK on `(client_name, service_date)`); cooldown readers `explode_history_rows()` it into per-item rows in memory. `week_signatures` — weekly hash for week-level cooldowns.

### 4.6 `src/` top-level
- `constants.py` — `REPEATABLE_ITEM_FLAGS_BY_SLOT` + `repeatable_row(row, base_slot)` (staple dishes: the SAME dish may recur daily in that slot, exempt from `unique_items` and the item-cooldown ban — the 20-day window governs ordinary dishes, not staples; keyed **by slot** because `is_tandoor` also marks tandoor breads, and a flat flag list let butter naan repeat all week in `bread`), `BASE_SLOT_NAMES`, `CONST_SLOTS`, `DEFAULT_OFF_SLOTS` (selectable-but-off-by-default: `curd`/`curd_rice` + combos), `COMBO_CATEGORIES` + `combo_minority_count` (dal_rasam/sambar_rasam/dal_sambar day-split), `DISPLAY_SLOT_NAME`, `DISPLAY_SLOT_ORDER` (single canonical order for the config editor + rendered menu — `slot_sort_key` and `slot_editor` both rank by it; welcome_drink→…→dessert→other veg→**nonveg_main last**, white_rice interleaved after rice), `NONVEG_PROTEINS`/`NONVEG_SLOT` (non-veg dishes may appear only in `nonveg_main`). Every combo key must also be in `EXEMPT_FROM_CUISINE` (its minority component is often a different cuisine that would otherwise be theme-filtered off on off-theme days).
- `db.py` — `get_supabase()` (thread-safe singleton).

---

## 5. UI layer

### `ui/`
- `api_client.py` → `MenuApiClient` (HTTP wrapper used by Streamlit; no auth — endpoints are public).
- `formatters.py` → `format_item_html(item, is_nonveg=…)`, `nonveg_slots_from_solution`, `display_label_for_slot_id`, `THEME_TAG_COLORS`, `THEME_ICONS`.
- `app.py` planner: sidebar has a single-select **City** filter (default "All", options = cities present among clients) that narrows the Client picker via `/clients` `clients_detail`; menu table renders non-veg dishes red (`.item-nonveg`, driven off `primary_protein` incl. egg); **Download Excel** (openpyxl, `_plan_xlsx`) — one sheet per counter, bold bordered headers, red non-veg; filename `menu_<client>_<date-range>.xlsx` (`_download_filename`). A **City** metric card shows the client's city.

### `customisation/` (Streamlit editors) — Pulse light theme
- `main.py` → `render_customisation_editor` (dispatcher). Stepped flow: (1) select/create client **+ pick city** → (2) Single vs Multi Cuisine Counter (+ number of counters) → (3) per-counter config. Builds the `counters` + `city` payload for `POST /client` and `PUT /client-config`.
- `counter_editor.py` → `render_counter_editor` — composes the 3 panels for one counter; returns `{name, categories, slot_counts, theme_map}`.
- `slot_editor.py`, `multi_slot_editor.py`, `theme_editor.py` — per-concern panels (categories / frequency / day themes), counter-scoped via a `key_prefix`.
- `pulse.py` → `PULSE_EDITOR_CSS`, `PULSE_THEME_COLORS` — the light (OP Lens) design tokens; injected by the editor. `app.py` skips the dark `ui/styles.py` `STYLES` while `view == "editor"`.

---

## 6. Data & config files

| Path | Purpose |
|---|---|
| `ikigai_masala-main/data/raw/city_items/<city>.xlsx` | **per-city item ontologies** — one file per city slug, selected from `clients.city`. `bangalore.xlsx` is the master **rule-ready** ontology (4,321 items; item_id key; cols incl. course_type, sub_category, cuisine_family, item_color, key_ingredient, primary_protein, is_premium_veg/_veg_dry, is_chinese_*/is_continental_*/is_*_biryani, is_liquid_dessert, welcome-drink subtypes (is_lassi/is_milkshake/is_soda_drink/is_cooler_drink/… + drink_rule_group), is_lentil_based/is_whole_legume_based/is_legume_salad, is_pulao, is_grill, is_dosa(_family), is_oil_based_bread, is_black_chana_gravy/is_kabuli_chana_gravy, plus quality signals classification_confidence/is_rule_ready/rule_data_note) and the fallback for any city without its own file. `pune.xlsx` = 274 items, all-veg, same 133 columns. Resolution + caching: `api/config.py::city_excel_path` / `city_required_slots`, `api/app.py::_get_menu_data(city)` |
| `ikigai_masala-main/data/raw/city_items/ontology_categories.json` | which base slots each city's ontology is **expected** to cover. `PoolBuilder.build_pools(df, required_slots=…)` raises on an empty required slot (a mapping regression), and a city list legitimately covers only what that city serves — Pune has no non-veg/sambar/rasam/starter/soup. A city absent from this file requires every mandatory slot (the pre-per-city behaviour) |
| `ikigai_masala-main/data/configs/city_rules/<city>.json` | **per-city rulesets** (one file per city: `bangalore.json` = the reference ruleset, `pune.json` = a standalone transcription of the Pune rulebook — see `docs/pune_rulebook.md` — plus `chennai`/`hyderabad`/`ncr` which still extend Bangalore). A file may `"extends": "<city>"` to inherit + override by rule `name` (and `"disable": [names]`). Loaded via `MenuRuleLoader.load_for_city(city)`; `CITY_RULES_DIR` + `DEFAULT_CITY='bangalore'` (the fallback for any city without its own file) live in `menu_rule_loader.py`. The API caches one ruleset per client's `city` |
| `ikigai_masala-main/data/configs/client_rules.json` | per-client overrides keyed by client name: `{disable, rules, constant_items}` (or legacy rule list); merged by `MenuRuleLoader.load_for_client()` |
| `ikigai_masala-main/data/configs/clients.json` | legacy client list; real source is Supabase |
| `ikigai_masala-main/scripts/normalize_city_ontology.py` | turns a raw city workbook into `data/raw/city_items/<city>.xlsx`: column set + order forced to the reference ontology's, `is_*` flags coerced to 0/1, text trimmed, `client` pool column set (default `common` — a city list tagging every row with one client name carries no per-client information and would leave a `source_pools: []` client with zero items; `--client-pool keep` opts out). Reports the categories the list does not cover. `--dry-run` writes nothing |
| `ikigai_masala-main/scripts/setup_all.sql` | **master** idempotent schema: creates every table + applies the counter migration in one run (supersedes running the two files below separately) |
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
| `test_slot_composition.py` | theme-filter union + slot composition |
| `test_prefilter_integration.py` | multi-rule pre-filter chain |
| `test_history_manager.py` | cooldowns & signatures |
| `test_client_config.py` | Supabase-backed config |
| `test_formatters.py`, `test_helpers.py`, `test_solution_formatter.py` | UI/utility layers |
| `test_city_ontology.py` | per-city ontology resolution + caching, `build_pools(required_slots=…)`, and the shipped Pune file (columns, declared categories, all-veg, `common`-only pools) |
| `test_normalize_city_ontology.py` | the normaliser's pure `normalize()` + a check that re-running it on the committed Pune workbook is a no-op (so nobody wonders whether it was hand-edited) |
| `test_pune_rules.py` | the Pune ruleset (every rule valid, named to an R-number, and actually matching Pune items — inert ones are listed explicitly) + the two new rule types |
| `test_pune_plan.py` | Pune end-to-end: every dish comes from the Pune list, the menu obeys R1/R2/R3/R12/R13/R19/R25/R28/R33/R43/R51, and week 2 still has bread after week 1 is in history (R36's payoff) |
| `client_fixtures.py` | snapshot of the live `clients` table — **all 43 clients / 57 counters** (`CLIENTS`) + `APP_SETTINGS`. Regenerate when the live table changes shape |
| `test_all_clients_generate.py` | **`@slow`** whole-fleet sweep: every counter in `client_fixtures.CLIENTS` must return a plan, plus named cases for working_days, pinned constants, day restrictions and starved slots |
| `test_p0_fixes.py` | fast stand-ins for the sweep's assertions (no solve, no Excel) so regressions still fail on a PR |

Run: `pytest` from `ikigai_masala-main/`. `pytest.ini` sets `-m "not slow"`, so the
57-counter sweep and the constraint-integration solves are **deselected by
default** — run `pytest -m slow` (CI does this on push-to-main and on dispatch)
to exercise them.

---

## 9. Non-obvious design notes

1. **Cell-based CP-SAT**: one bool var per (day, slot, candidate) — enables per-item penalties and similarity-driven regeneration.
2. **Two-phase rules**: pre-filter eliminates items before the model is built (fast), then `apply()` adds CP-SAT constraints. When writing a new rule, decide which phase fits.
3. **No config cache**: `ClientConfigLoader` reads Supabase on every call — live edits, no restart. Don't add caching without thinking through invalidation.
4. **Dynamic worker allocation** in `api/concurrency.py`: 1 active solve → 9 workers; 2 active → 5 each. Tuned for ~1 GB RAM.
5. **Theme dispatch**: global weekday→theme map, per-client overridable via each counter's `theme_map` in `clients.counters`. Themes: mix/chinese/biryani/south/north/**continental** + **`chinese_continental`** (meta-theme resolved per ISO-week parity in `weekday_type_for_config` → even=chinese, odd=continental). Solver honors it via `theme_*` rules.
10. **Weekend service**: `clients.serve_weekends` — when set, `_weekdays_from` stops skipping Sat/Sun so plans cover them.
12. **Per-client item cooldown**: `clients.item_cooldown_days` (None=default 20). `api._apply_item_cooldown_override` rebuilds a fresh `item_cooldown` rule (never mutates the cached shared list) and the value is passed to `banned_items_by_date`; `_effective_history_window` widens the history query to match.
17. **One item ontology per city, selected from `clients.city`** — the same shape the rules already had. `api/config.py::city_excel_path(city)` resolves `data/raw/city_items/<slug>.xlsx`, falling back to `DEFAULT_EXCEL_PATH` (Bangalore) for a city with no file, so adding a city to `AVAILABLE_CITIES` never breaks planning. `MENU_EXCEL_PATH` still pins ONE workbook for every city (single-city deployments, tests) and then also switches off the per-city category declarations, because the file's contents no longer follow from the city name. **The caches are keyed by resolved path, not city name** (`_menu_data_by_path`, `_nonveg_items_by_path`, and `(path, pool tokens)` for `_filtered_cache`): Chennai/Hyderabad/NCR share Bangalore's file, and keying by city would hold four copies of a 4,300-row df — while keying the F5 pool cache by tokens alone (as it was) would hand a Pune client Bangalore's `common` pool. Everything derived from the ontology is city-scoped too: `_get_nonveg_items(city)` (Pune is all-veg, so nothing renders red) and `_ontology_item_names(city)` (a `constant_items` pin naming a dish only another city carries stays a stamped constant instead of becoming a candidate with no pool row). `/pool-preview` takes an optional `city`; `/editor-metadata` returns the union of tokens plus a `client_pools_by_city` breakdown, and `_validated_source_pools` validates against the city the client will have after the write.
15. **Client item pools (F5)**: the ontology `client` column tags each item with comma-separated pool tokens (exact-match, case-insensitive — never substring). A client's eligible universe = items in `common ∪ clients.source_pools`, deduped by `item_id`. `api._menu_data_for_client` filters the cached full df to that subset and rebuilds per-slot pools (cached per active-pool set) **before** `build_pools`, so the existing rule pipeline (theme/cooldown/ingredient_ban/…) runs on the merged pool — a borrowed item still obeys the target client's rules. `common` (always included) covers every mandatory slot, so filtering never empties one. When `source_pools` is `None` (pre-migration/column missing) the full ontology is used (unchanged behavior). Per-client *rules* keyed to the pool identity are intentionally out of scope for now.
16. **Two-nonveg daily composition + theme-filter union**: the base ruleset's `slot_composition` rules (`nonveg_main_daily_pair`, `veg_dry_north_south_pair`) compose a counter's *pair* of nonveg mains / veg dries per day by theme. They self-gate on `requires_slot_count`, so single-slot counters are unaffected. Crucially, `ThemeSlotFilterRule` normally narrows `nonveg_main` to one cuisine on chinese/biryani/south/north days (chinese-gravy-only, biryani-only, …), which would delete the paired north/south chicken gravy before the solver sees it. So `_augment_nonveg_pair` (theme_rules.py) keeps `themed ∪ north/south-chicken-gravy` for `nonveg_main` **only when `cfg.slot_counts['nonveg_main'] >= 2`** (`_has_multi_nonveg`); single-nonveg counters keep the strict themed pool. At **>= 3** it also keeps `_NONVEG_STRUCTURAL_FLAGS` (dry / tandoor / egg): the filter's job is to guarantee the *themed* dish is available, not to make every dish themed, and narrowing a 5-dish station to biryani + chicken gravy left it 0 dry and 2 egg items against a composition wanting one of each daily. The themed dish is still guaranteed — the composition rule mandates it. The composition rule then places one themed dish + one regional gravy.
18. **Staple-ness is regional, so it is declared by a rule, not a constant.** `REPEATABLE_ITEM_FLAGS_BY_SLOT` (constants) is global and correct for the chicken kebab; the new `repeatable_items` rule type puts the same declaration in a **city or client** ruleset. Pune's rulebook R36 states plain chapati/phulka may run on consecutive days — its bread pool is exactly those two dishes, so under the 20-day cooldown week 2 would have no bread at all — while a Bangalore bread slot rotating naans and parathas wants the no-repeat rule intact. Both consumers read one declaration: `MenuSolver._declared_repeatable()` → `context['extra_repeatable']`, which `unique_items` folds into its repeatable set **and** (new) `item_cooldown.pre_filter_pool` exempts from history bans. Wiring only unique_items is the trap: the exemption then reads as applied while the cooldown still starves the slot a week later. `ItemCooldownMenuRule.diagnose()` reads the same declarations via `_peer_rules` so the pre-flight report and the solve agree — without that, a 2-item bread slot with both dishes in history is reported as a blocking ERROR the solver would not have hit.
13. **Colour variety is dynamic + diagnosable**: its numbers now come from the city ruleset (`color_variety` rule → `solver_overrides()` → `SolverConfig`); Bangalore ships none and keeps the defaults below. The built-in colour rule (`MenuSolver._add_color_constraints`) clamps `min_distinct` to `min(4, colour-slots, colours-present)` so small counters (e.g. a 2-slot Chinese station) aren't trivially INFEASIBLE. `diagnostics.color_variety_diagnostics` pre-flags the *provable* residual (`colours_available × max_same_color < colour_cells`) as an ERROR before the solver runs. **Asymmetric per-colour cap (rulebook 89-91)**: every colour ≤ `max_same_color_per_day` (=2, rule 90) EXCEPT up to `max_colors_at_reach` (=1) colour may reach `max_same_color_reach` (=3) — encoded as `sum(colour) <= soft_cap + (reach-soft_cap)*b` with a reach-bool `b` and `sum(b) <= max_colors_at_reach`. Rice≠gravy colour holds unless `ignore_rice_gravy_color_diff_on_chinese_day` (rule 92); colour-counted slots = `cfg.color_slots` (excludes white_rice/curd, rule 93).
14. **Solver time budget is a total, not per-attempt**: `MenuSolver.solve` enforces a wall-clock `deadline` across the ≤8 restart attempts (each capped at `min(slice, remaining)`), so `time_limit_sec` bounds total wall-clock (was `max(20, total/8)` × 8 ⇒ up to 160s for a 60s request).
11. **Optional/combo categories**: `curd` (plain-curd station, pool from `is_plain_curd`; in `REPEATABLE_SLOTS` so it's exempt from unique_items + cooldown and may recur daily), `curd_rice` (pool from `is_curd_rice` flag) and combos `dal_rasam`/`sambar_rasam`/`dal_sambar` (dal majority) are base slots in `DEFAULT_OFF_SLOTS` (selectable, off by default). `curd` and `curd_side` (displayed "Curd / Raita") are the two yogurt-side options and are mutually exclusive per counter (`MUTUALLY_EXCLUSIVE_SLOT_GROUPS`, enforced in `ClientConfigLoader._validate_counters`); `curd_rice` is independent. Combos split one slot across the week by course_type (majority/minority via `combo_minority_count`, applied per-day in `MenuSolver._build_cells` via `_combo_day_variant`). Optional slots are skipped by the mandatory-pool validation. A combo must be listed in `EXEMPT_FROM_CUISINE` or its minority component (often a different cuisine) gets theme-filtered out on off-theme days and the split silently collapses to all-majority.
6. **History split**: `menu_history` is one JSON document per client-day (`menu={slot:item}`), exploded to item-level in memory for cooldowns; `week_signatures` is a weekly hash for week-level cooldowns.
7. **Supabase is the source of truth** for clients, history, overrides — Flask and Streamlit both read it directly.
8. **Slot expansion**: base slot names like `veg_dry` get expanded to indexed slots `veg_dry__1`, `veg_dry__2` in `PoolBuilder._expand_slots_in_order`. Rules operate on expanded names.
9b. **Per-counter rule scoping**: a `client_rules.json` block may carry a `counters` map — `{"counters": {"<counter name>": {disable, rules, constant_items}}}` — layered over the client-level entry. A rule that only applies to one station (L&T's `Non Veg Lunch` is themed biryani daily, so the weekly nonveg-biryani cap is dropped there) stays scoped instead of silently switching off for the client's other counters. `load_for_client(client, generic, counter_name)` and `get_client_constant_items(client, counter_name)` take the counter.
9c. **Rules are never relaxed just to return a menu**: an over-constrained counter fails with a message naming the tightest slots, because the useful output is the conflict, not a plan that abandoned the rules. The single exception is *provable arithmetic impossibility* — a slot with fewer distinct eligible items than days to fill (`unique_items_menu_rule.starved_slots`) — where uniqueness is lifted for that one slot only, a HIGH-tier repeat penalty still maximises variety, and `diagnose()` reports it. Frequency targets cap to `min(placeable_days, distinct_matching_items)`: counting placeable days alone asked for two liquid desserts from a pool holding one. Every config-driven rule type (`selector_frequency`, `slot_composition`, `attribute_grouping`, `unique_items`, `curd_side`) implements `diagnose()`, so an inert or under-enforced rule is reported rather than silently dropped. Worked example of why the exception is arithmetic and not a fallback: `common` holds exactly 4 distinct `curd_rice` items, so a common-only client running that station over 5 days must repeat one. The other 9 `curd_rice` items in the ontology are client-specific health variants (millet / brown-rice / dry-fruit) belonging to `healthineers`/`continental`/`cloudera` — attaching one of those pools to fix the count would import a whole unrelated client's menu, so the right resolution is a 5th `common` item, which is what the diagnostic asks for.

9e. **A frequency cap can be *forced* past, and that must be detected, not discovered as INFEASIBLE**: `max`/`max_per_week` was assumed "only tightens, never wrong". It is wrong whenever the counter cannot avoid the selector on more days than the cap allows, and there are two ways that happens — the theme filter leaves the slot nothing else (`SelectorFrequencyRule._forced_days`), or a `slot_composition` mandates a matching item (`slot_composition_rule.days_forced_by_composition`, cross-checked via `_peer_rules`). Both are provable from the pools, so they are ERRORs and `/plan` answers 422 naming the rule, the day count and three concrete fixes. Worked examples: Amadeus's Chinese counter is themed `chinese_continental` every weekday, so on an odd ISO week all five days resolve to *continental* and the theme filter narrows `rice` to continental rice — five forced days against `continental_rice_weekly`'s `max: 1`, INFEASIBLE on 9 of 14 start dates while `/diagnose` said `would_succeed: true`. Siemens Technology's non-veg counter is the composition variant: two biryani-theme days each get a mandatory biryani against `nonveg_biryani_once_per_week`. Note `max` counts **days**, not dishes — a counter with 2+ nonveg slots could satisfy the weekly cap by stacking two biryanis onto one day, which is what `nonveg_biryani_one_per_day` (`daily_max: 1`) exists to stop.

9g. **Some dishes are staples, not variety slots — model that instead of relaxing the rule that wants them daily**: L&T's 5-dish non-veg station needs a kebab every day, and only one kebab is eligible for a common-only client. Read as an ordinary dish that is a five-distinct-items shortfall; read correctly, the chicken kebab is a **staple** like steamed rice — the same dish daily — so it is exempt from `unique_items` and the cooldown ban and one item covers the week. That is what `REPEATABLE_ITEM_FLAGS_BY_SLOT` encodes. Separately, `_horizon_limited_components()` + `_add_horizon_floors()` still handle a *genuine* shortfall in a non-staple component (distinct items < days it is required, which per-day availability never reveals) by replacing the per-day mandate with an at-least-N-days floor via `OnlyEnforceIf` indicators — same bug class as the `selector_frequency` distinct-items cap (note 9c), one rule type later. A staple component is skipped by that check entirely.

9f. **Sweep more than one start date**: `chinese_continental` resolves per ISO-week parity, so satisfiability is date-dependent and a mid-week start spans two ISO weeks (the theme flips inside a single horizon). The all-clients sweep originally used one Monday of an even week and passed Amadeus's Chinese counter while it was failing on most real start dates. `test_every_counter_generates_on_other_start_dates` covers an odd-week Monday and a Wednesday, and accepts 200 **or** a 422 that names a rule and a fix — an unexplained 500 is the failure it exists to catch.

9d. **Diagnostics are aggregated per slot, not per (day, slot)**: `theme_slot_filter`'s narrowing INFO fired once per themed day per slot — 811 entries across the 56 counters, each captioned "No action needed" — which buried the 10 real WARNINGs. It now emits one line per slot carrying the day count and the resulting pool range (283 entries, same information). When adding a `diagnose()`, aggregate before appending: the list is read by a human deciding whether to fix data.
9. **Per-client custom rules**: `data/configs/client_rules.json` stores per-client overrides keyed by client name. Shape is `{disable: [city_rule_names], rules: [...], constant_items: {slot: value|{weekday: value}}}` (legacy bare list still works as `{rules: list}`). `load_for_client()` merges by rule `name` via the same `_merge_rule_dicts` used for city `extends` — same name overrides, `disable` drops. `constant_items` are honoured **two ways, chosen by whether the dish exists in the ontology**: a pin naming a real item becomes `SolverConfig.forced_items[(date, slot_id)]` and its cell stays in the model with candidates narrowed to that dish, so every other rule sees it (its colour counts toward colour variety, its cuisine toward cuisine variety, and unique_items stops a duplicate elsewhere); a pin naming a dish the ontology does not carry ("Mutton Biryani", "Fish Tikka Masala" — the ontology holds only chicken + egg for non-veg) has nothing to narrow to, so its cell is skipped and the text is stamped verbatim post-solve. Adding the dish to `menu_items.xlsx` switches the same pin over to the solver with no config change. Mutually-exclusive sibling slots are removed either way. `api._canonical_item_name` does the space/underscore matching. Client `working_days` (DB column) filters the plan horizon (e.g. Quince = Wed/Thu/Fri).

---

## 10. Dependencies

Solver `ortools` · data `pandas numpy openpyxl` · web `flask flask-cors requests` · db `supabase python-dotenv` · UI `streamlit` · tests `pytest pytest-cov`.

---

## 11. Editing rules for this file

- When adding a new rule file under `src/menu_rules/`, append a row to §4.2.
- When adding an endpoint in `api/app.py`, append a row to §3.
- When moving or renaming a module, update its row in §4 and any mention in §7.
- Keep rows to one line. This file is optimized for fast scanning, not prose.
