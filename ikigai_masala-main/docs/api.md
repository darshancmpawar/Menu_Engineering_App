# API reference

All endpoints are under `/api/v1` and are open — no authentication header is
required.

Requests and responses are JSON. Responses carry an `X-Request-ID` header —
accept or supply it to correlate traces across logs.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET    | `/health` | Liveness + readiness — see [health response](#health-response) |
| GET    | `/metrics` | In-process counter snapshot |
| GET    | `/clients` | List clients (`clients` = names; `clients_detail` = `[{name, city}]` for the city filter) |
| POST   | `/plan` | Generate a plan (optional `counter_index` picks the counter; response carries `counter_mode` / `counter_count` / `counter_index` / `counter_name`) |
| POST   | `/regenerate` | Regenerate selected cells (optional `counter_index`) |
| POST   | `/save` | Persist plan to history (overwrites the prior day rows for the same `(client, dates)`; multi-cuisine sends `counters: [{name, week_plan}]`) |
| GET    | `/saved-plan` | Return the saved plan for `(client_name, start_date, num_days)` if one exists — used by Streamlit's Generate flow to replay saved menus deterministically |
| POST   | `/diagnose` | Run the pre-flight rule diagnostics without invoking the solver (replaces the old `/validate-pools` surface) |
| GET    | `/editor-metadata` | Slot / theme / city metadata for the editor UI (`available_cities`, `default_off_slots`, `default_item_cooldown_days`, `available_client_pools`, `client_pools_by_city`). `?city=<name>` scopes `available_client_pools` to that city's item list; omitted, it is the union across cities |
| POST   | `/pool-preview` | F5: eligible distinct item count + category-wise counts for a set of `source_pools` (`common` always included). Optional `"city"` selects which city's item list is counted |
| GET    | `/client-config/<name>` | Read a client's config incl. `city`, `serve_weekends`, `item_cooldown_days`, `counters` (returns `ETag: "<version>"`) |
| PUT    | `/client-config/<name>` | Update a client's config incl. `city` / `serve_weekends` / `item_cooldown_days` / `counters` (requires `version` body field or `If-Match` header) |
| POST   | `/client` | Create a client (accepts `city`, `serve_weekends`, `item_cooldown_days`, `counters`) |
| DELETE | `/client/<name>` | Delete a client |

---

## Health response

`GET /api/v1/health` — 200 when healthy, 503 when degraded. Either way the
body carries enough to diagnose.

```json
{
  "status": "healthy",
  "version": "abc1234",
  "uptime_seconds": 42,
  "supabase_reachable": true,
  "queue": {
    "active_solves": 0, "queued": 0,
    "max_running": 2, "max_queued": 8,
    "workers_per_solve": 9
  }
}
```

---

## Metrics response

`GET /api/v1/metrics` — counters are monotonic and never reset in-process.
Counter names follow Prometheus conventions so a future swap to
`prometheus_client` is a one-file change in `api/metrics.py`.

```json
{
  "success": true,
  "uptime_seconds": 3621,
  "counters": {
    "plan_requests_total{outcome=\"success\"}": 14,
    "plan_requests_total{outcome=\"solver_error\"}": 1,
    "regenerate_requests_total{outcome=\"success\"}": 3,
    "solver_failures_total": 1,
    "rule_failures_total{rule=\"theme_day\"}": 2
  }
}
```

---

## Plan response

```json
{
  "success": true,
  "solution": {
    "2026-03-31": {
      "theme": "Mix of South + North",
      "day_type": "mix",
      "items": {
        "welcome_drink": { "display_name": "Welcome Drink",  "item": "masala_chaas(Y)", "item_base": "masala_chaas", "is_nonveg": false },
        "rice":          { "display_name": "Flavoured Rice",  "item": "jeera_rice(W)",   "item_base": "jeera_rice",   "is_nonveg": false },
        "nonveg_main":   { "display_name": "Nonveg Main",     "item": "chicken_65(R)",   "item_base": "chicken_65",   "is_nonveg": true }
      }
    }
  },
  "counter_mode": "single",
  "counter_count": 1,
  "counter_index": 0,
  "counter_name": "Counter 1",
  "pool_warnings": [
    "Chinese Tuesday 01 Apr: only 4 veg dry items available, need 3"
  ],
  "rule_warnings": [
    { "rule": "theme_starter_preference", "phase": "get_objective_terms",
      "error": "ValueError: ...", "attempt_seed": 1017 }
  ]
}
```

- `is_nonveg` on each item is derived from the ontology (`primary_protein`
  plus the `is_egg_dish` flag); the UI and Excel export colour those dishes red.
- The `counter_*` fields describe which cuisine counter this plan is for. For a
  single-cuisine client `counter_mode` is `"single"` and `counter_count` is 1;
  a multi-cuisine client is solved one counter at a time (`counter_index`).
- `rule_warnings` only appears when one or more soft rules failed during the
  winning solve attempt. Each entry carries `attempt_seed` so the failure can
  be reproduced.

---

## Saved-plan response

`GET /api/v1/saved-plan?client_name=<name>&start_date=YYYY-MM-DD&num_days=<n>`

Returns the same `solution` shape as `/plan`, sourced from `menu_history`
instead of the solver. Used by Streamlit's **Generate** button so a user
who has already saved a plan for the selected dates sees that exact plan
back, deterministically. Never invokes the solver.

```json
{
  "success": true,
  "exists": true,
  "covered_dates": ["2026-03-23", "2026-03-24"],
  "source": "history",
  "solution": {
    "2026-03-23": {
      "theme": "Mix of South + North",
      "day_type": "mix",
      "items": {
        "rice": { "display_name": "Flavoured Rice",
                  "item": "jeera_rice(Y)", "item_base": "jeera_rice", "is_nonveg": false }
      }
    }
  }
}
```

- `exists` is `true` iff **every** requested weekday has at least one
  saved row. `false` covers both "nothing saved" and "partially saved"
  cases — the Streamlit UI falls back to `POST /plan` when `exists` is
  false. `covered_dates` shows which dates did have rows, so a future
  UI revision can offer "load partial + generate the rest".
- Color suffixes (`(Y)`, `(R)`, …) on `item` are re-attached server-side
  by looking each `item_base` up in the loaded Excel ontology, so the
  UI's renderer doesn't need a code branch.
- The plan's `theme` / `day_type` come from the **current** client
  config — i.e. if the day-theme map was changed after the plan was
  saved, the loaded plan shows the new theme labels. The underlying
  items don't move.

---

## Pre-flight diagnostics

`POST /api/v1/diagnose` (and the same pass embedded in `POST /api/v1/plan`)
runs every registered rule's `diagnose()` method against the request's
client config + history + pool state, returning structured findings
**without running the CP-SAT solver**.

```json
{
  "success": true,
  "rule_diagnostics": [
    {
      "rule": "item_cooldown_20d",
      "rule_type": "item_cooldown",
      "severity": "error",
      "phase": "pre_filter",
      "message": "Item cooldown (20 days) banned all 8 starter candidates on 2026-05-13 (chinese). Pool is empty after cooldown.",
      "suggestion": "Lower cooldown_days for this rule, add more starter items to the ontology, or choose a later start date so recent history falls outside the cooldown window.",
      "affected": {
        "date": "2026-05-13", "slot": "starter", "day_type": "chinese",
        "banned_count": 8, "pool_size_before": 8, "pool_size_after": 0,
        "cooldown_days": 20
      }
    }
  ],
  "summary": {"errors": 1, "warnings": 3, "infos": 2, "would_succeed": false},
  "pool_warnings": ["Chinese Tuesday 13 May: only 0 starter items available, need 1"]
}
```

### Severity model

- `error` — solver would **fail**. `POST /api/v1/plan` short-circuits to **HTTP 422** before invoking CP-SAT.
- `warning` — solver may succeed but the configuration is risky (tight pools, silent fallback after a theme filter empties a pool, asymmetric coupling data).
- `info` — notable but expected (e.g. "cooldown banned 4/12 items, pool still healthy"; "ingredient ban removes 3 mushroom items").

`summary.would_succeed` is `false` iff any diagnostic carries `severity=error`.

Besides the per-rule checks, two synthetic passes run: `pool_size` (a slot's
pool is smaller than the count needed) and `color_variety` (a day has more
colour-bearing slots than `colours_available × max_same_color_per_day` can
fill — a provable colour infeasibility, `rule_type="color_variety"`, ERROR).

### /plan pre-flight gate (HTTP 422)

When `/api/v1/plan` runs and pre-flight finds at least one `error`:

```json
HTTP/1.1 422 Unprocessable Entity
{
  "success": false,
  "error": "rule_diagnostics_blocked",
  "message": "Pre-flight diagnostics found 1 blocking issue for Rippling; solver skipped.",
  "rule_diagnostics": [...],
  "summary": {"errors": 1, ...},
  "pool_warnings": [...]
}
```

`MenuApiClient._parse_response` recognises this envelope and raises
`RuleDiagnosticsBlockedError(diagnostics, summary)` — a subclass of
`RuntimeError` — so the Streamlit UI can render the diagnostics
expander directly without a second round-trip.

### pool_warnings (back-compat)

`pool_warnings` is now a string-projection of the `rule_diagnostics`
entries with `rule_type == "pool_size"`. The key stays in the response
for one release so older Streamlit builds keep rendering something;
new code should consume `rule_diagnostics` directly.

The old `POST /api/v1/validate-pools` endpoint is **removed** — its
surface is fully subsumed by `/diagnose`.

---

## Save semantics

`POST /api/v1/save` writes **overwrite** to `menu_history` and
`week_signatures`: the `menu_history` row for each `(client_name,
service_date)` (one JSONB document per day) and the `week_signatures` row for
`(client_name, week_start)` are replaced. Re-saving the same week therefore
overwrites the prior plan instead of accumulating. This is what makes the
Generate → load-from-history flow deterministic: the latest save is always the
canonical answer.

A single-cuisine save sends `week_plan` (a `{date: {slot: item}}` map); a
multi-cuisine save sends `counters: [{name, week_plan}]` and the day's `menu`
column stores a nested `{counter: {slot: item}}` document.

The single-shot retry policy in `MenuApiClient.save()` is unchanged —
even though server-side `/save` is now idempotent on retry, a popped
"Plan saved" toast on a silent second attempt is more confusing than
just bubbling the error and letting the user retry explicitly.

---

## Client-config concurrency

```
GET  /api/v1/client-config/<name>      -> {version: 3, city: "Pune", counters: [...], ...}   ETag: "3"
PUT  /api/v1/client-config/<name>      body {"version": 3, "counter_mode": "single", "counters": [...], "city": "Pune"}
  → 200 {version: 4, ...}   ETag: "4"
  → 409 {"current_version": 5, "error": "modified by another request..."}
```

Either include `"version": N` in the body (preferred by the Streamlit UI)
or send `If-Match: "N"` as a header — standard HTTP conditional-update idiom.
The body may carry the full `counters` list (source of truth for the cuisine
setup) and/or a `city`; a legacy per-field shape
(`active_base_slots` / `slot_counts` / `theme_map`) is also accepted and
applied to the primary counter.

---

## Error envelope

Failures return HTTP 4xx/5xx with:

```json
{ "success": false, "error": "<human-readable message>" }
```

- 400: validation failure (missing field, unknown client, malformed JSON)
- 409: optimistic concurrency conflict (on `PUT /client-config`)
- 500: unexpected server error — a generic message, never exception details
- 429: per-IP rate limit tripped (`/plan`: 10/min burst 10; `/regenerate`: 20/min burst 20). Response includes `Retry-After` and `retry_after_seconds`. `MenuApiClient` retries once with jitter automatically.
- 503: server at capacity (solver queue full) or supabase unreachable (on `/health`)
- 504: request timed out waiting in the solver queue

---

## Menu rules

Defined in `src/menu_rules/`, wired up from `data/configs/indian_menu_rules.json`.
Per-client overrides live in `data/configs/client_rules.json`.

### Generic rules

| Rule | Kind | Role |
|---|---|---|
| `cuisine` | hard | Minimum cuisine variety per day |
| `color_variety` | hard | Minimum distinct colors per day |
| `color_pairing` | hard | Maximum same-color items per day |
| `unique_items` | hard | No repeats within the horizon |
| `coupling` | hard | Item dependencies (curry ↔ rice, etc.) |
| `curd_side` | hard | Fill the curd-side slot |
| `premium` | hard | Per-horizon min / max for premium items |
| `welcome_drink_color` | hard | Color variety for welcome drinks |
| `welcome_drink_buttermilk` | hard | Buttermilk (`is_buttermilk`) on exactly N (default 2) welcome-drink days, solver-chosen, non-consecutive |
| `theme_day` | hard | Monday mix (≥1 south + ≥1 north) |
| `theme_slot_filter` | pre-filter | Narrow pools by day theme (chinese / biryani / south / north) |
| `item_cooldown` | pre-filter | Ban items used within N days (default 20; overridable per client via `clients.item_cooldown_days`) |
| `ricebread_gap` | pre-filter | Enforce N-day gap between rice-breads |
| `nonveg_biryani_weekly` | pre-filter | ≤1 nonveg biryani per week |
| `nonveg_dry_preference` | pre-filter | Prefer dry nonveg on certain days |
| `theme_starter_preference` | soft | Bonus for theme-matching starters |
| `theme_fallback_penalty` | soft | Penalty when a non-theme fallback is used |
| `week_signature_cooldown` | soft | Avoid re-running a recent week verbatim |

### Per-client rules

Stored per client in `data/configs/client_rules.json`, loaded fresh on every request:

| Rule | Kind | Role |
|---|---|---|
| `ingredient_ban` | pre-filter | Case-insensitive ban by `key_ingredient` **and** `primary_protein` (either field matching the banned token drops the item) |
| `item_frequency` | hard | Weekly frequency cap by flag / sub-category / item / ingredient |
| `slot_day_restriction` | skip-cells | Skip a slot on specific weekdays (e.g. no nonveg on Tue/Thu) |

Rule configs are validated at load time. Invalid configs (for example
`min_per_week > max_per_week`) are logged with the specific field names
that failed and skipped — the solver never sees them.

---

## Data model

### Supabase tables

The schema is **four tables** — a client's whole cuisine config is one JSON
document in `clients.counters`, not spread across normalized tables.

| Table | Columns | Purpose |
|---|---|---|
| `clients` | `name (pk)`, `counters (jsonb)`, `city`, `serve_weekends (bool)`, `item_cooldown_days (int, null)`, `source_pools (jsonb, null)`, `version`, `created_at` | Client registry. `source_pools` = F5 client item-pool tokens (common implicit; null → full ontology fallback, [] → common-only). `counters` = ordered list `[{name, categories, slot_counts, theme_map}]` (index 0 = primary). `city` = optional location. `serve_weekends` = also plan Sat/Sun. `item_cooldown_days` = per-client cooldown override (null = default 20). `version` = optimistic-concurrency counter. |
| `app_settings` | `key (pk)`, `value (jsonb)` | Misc tunables |
| `menu_history` | `client_name`, `service_date`, `menu (jsonb)`, `created_at`; PK `(client_name, service_date)` | One row per day; `menu = {slot: item_base}` (single) or `{counter: {slot: item_base}}` (multi) |
| `week_signatures` | `client_name`, `week_start`, `week_signature` | Week-level hash for week-signature cooldown |

### Slot expansion

Base slot names (e.g. `veg_dry`) get expanded to indexed slot ids (`veg_dry__1`,
`veg_dry__2`) based on the per-counter `slot_counts` in `clients.counters`.
Rules operate on the expanded ids; `_base_slot()` strips the suffix when needed.

### Default theme schedule

| Weekday | Theme |
|---|---|
| Monday | Mix (south + north) |
| Tuesday | Chinese |
| Wednesday | Biryani |
| Thursday | South Indian |
| Friday | North Indian |

Overridable per client (per counter) via the `theme_map` in `clients.counters`.
Available themes: `mix`, `chinese`, `biryani`, `south`, `north`, `continental`
(filtered off the `is_continental_*` flags), plus `chinese_continental` — a
weekly-alternating meta-theme resolved by ISO-week parity (even → chinese, odd
→ continental) before it reaches the pool filters.

### Optional & combination categories

Beyond the standard slots, several categories are **selectable but off by
default** (`default_off_slots`):

- `curd` — a plain-curd station (pool built from the `is_plain_curd` flag).
  Repeatable: exempt from unique-items and cooldown, so the same plain curd may
  recur every day. Mutually exclusive with `curd_side` (Curd / Raita) — a
  counter serves one yogurt side or the other, never both.
- `curd_rice` — a curd-rice station (pool built from the `is_curd_rice` flag).
- `dal_rasam`, `sambar_rasam`, `dal_sambar` — **combination categories**: one
  slot that splits across the week by course_type. Over 5 days: `dal_rasam` = 3
  dal + 2 rasam, `sambar_rasam` = 3 rasam + 2 sambar, `dal_sambar` = 3 dal + 2
  sambar (dal majority); longer weeks give the majority variant proportionally
  more days. Each combo is exempt from cuisine/theme filtering
  (`EXEMPT_FROM_CUISINE`) so its minority component survives on off-theme days.

### Weekend service

`clients.serve_weekends` (a plain bool, set in the editor). When true, plan
date generation includes Saturday/Sunday instead of skipping them, so a 6-day
plan from Monday covers Mon–Sat.

---

## Output formats

### UI theme badges

Cuisine-theme badges use the Pulse light-theme tints defined in
`ui/theme_tokens.py` (`PULSE_THEME_COLORS`), keyed by theme → (background tint,
foreground): `mix`, `chinese`, `biryani`, `south`, `north`. Editing the palette
in that one file re-colours both the planner and the customisation editor.

### Color suffixes

Items carry a single-letter color code from the ontology: `R`, `G`, `B`, `Y`,
`W`, `O`, `K`. Slot display labels come from `DISPLAY_SLOT_NAME`
(`rice` → "Flavoured Rice", `bread` → "Indian Bread", etc.).

### Excel download

The **Download Excel** button exports an `.xlsx` workbook — one sheet per
cuisine counter, each with a bold, filled, bordered header row, full black cell
borders, and non-veg dishes in red. Color suffixes are stripped and slot names
are display-formatted. The file is named `menu_<client>_<date-range>.xlsx`.
