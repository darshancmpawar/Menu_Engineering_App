# API reference

All endpoints are under `/api/v1`. Every endpoint except `/health`, `/`, and
`/auth/login` requires an `Authorization: Bearer <token>` header.

Requests and responses are JSON. Responses carry an `X-Request-ID` header —
accept or supply it to correlate traces across logs.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST   | `/auth/login` | Exchange email + password for a bearer token |
| GET    | `/health` | Liveness + readiness — see [health response](#health-response) |
| GET    | `/metrics` | In-process counter snapshot (auth-gated) |
| GET    | `/clients` | List client names |
| POST   | `/plan` | Generate a plan |
| POST   | `/regenerate` | Regenerate selected cells |
| POST   | `/save` | Persist plan to history |
| POST   | `/validate-pools` | Dry-run pool sizes (no solve) |
| GET    | `/editor-metadata` | Slot / theme metadata for the editor UI |
| GET    | `/client-config/<name>` | Read a client's config (returns `ETag: "<version>"`) |
| PUT    | `/client-config/<name>` | Update a client's config (requires `version` body field or `If-Match` header) |
| POST   | `/client` | Create a client |
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
    "rule_failures_total{rule=\"theme_day\"}": 2,
    "legacy_sha256_verifications_total{result=\"success\"}": 0
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
        "welcome_drink": { "display_name": "Welcome Drink", "item": "masala_chaas(Y)", "item_base": "masala_chaas" },
        "rice":          { "display_name": "Flavor Rice",   "item": "jeera_rice(W)",   "item_base": "jeera_rice" }
      }
    }
  },
  "pool_warnings": [
    "Chinese Tuesday 01 Apr: only 4 veg dry items available, need 3"
  ],
  "rule_warnings": [
    { "rule": "theme_starter_preference", "phase": "get_objective_terms",
      "error": "ValueError: ...", "attempt_seed": 1017 }
  ]
}
```

`rule_warnings` only appears when one or more soft rules failed during the
winning solve attempt. Each entry carries `attempt_seed` so the failure can
be reproduced.

---

## Client-config concurrency

```
GET  /api/v1/client-config/<name>      -> {version: 3, ...}   ETag: "3"
PUT  /api/v1/client-config/<name>      body {"version": 3, "theme_map": {...}}
  → 200 {version: 4, ...}   ETag: "4"
  → 409 {"current_version": 5, "error": "modified by another request..."}
```

Either include `"version": N` in the body (preferred by the Streamlit UI)
or send `If-Match: "N"` as a header — standard HTTP conditional-update idiom.

---

## Error envelope

Failures return HTTP 4xx/5xx with:

```json
{ "success": false, "error": "<human-readable message>" }
```

- 400: validation failure (missing field, unknown client, malformed JSON)
- 401: missing / invalid token
- 403: insufficient role for an admin-only route
- 409: optimistic concurrency conflict (on `PUT /client-config`)
- 500: unexpected server error — a generic message, never exception details
- 429: per-principal rate limit tripped (`/plan`: 10/min burst 10; `/regenerate`: 20/min burst 20). Response includes `Retry-After` and `retry_after_seconds`. `MenuApiClient` retries once with jitter automatically.
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
| `theme_day` | hard | Monday mix (≥1 south + ≥1 north) |
| `theme_slot_filter` | pre-filter | Narrow pools by day theme (chinese / biryani / south / north) |
| `item_cooldown` | pre-filter | Ban items used within N days |
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
| `ingredient_ban` | pre-filter | Case-insensitive ban by `key_ingredient` |
| `item_frequency` | hard | Weekly frequency cap by flag / sub-category / item / ingredient |
| `slot_day_restriction` | skip-cells | Skip a slot on specific weekdays (e.g. no nonveg on Tue/Thu) |

Rule configs are validated at load time. Invalid configs (for example
`min_per_week > max_per_week`) are logged with the specific field names
that failed and skipped — the solver never sees them.

---

## Data model

### Supabase tables

| Table | Columns | Purpose |
|---|---|---|
| `clients` | `name (pk)`, `menu_category`, `version`, `created_at` | Client registry (version = optimistic-concurrency counter) |
| `menu_categories` | `name (pk)`, `slots (text[])` | Base-slot templates |
| `slot_count_overrides` | `client_name`, `slot`, `count` | e.g. `veg_dry = 2` |
| `theme_overrides` | `client_name`, `day`, `theme` | Per-day theme override |
| `app_settings` | `key`, `value` | Misc tunables |
| `users` | `email (pk)`, `profile_name`, `password_hash`, `role` | Auth (bcrypt + legacy SHA-256 fallback) |
| `menu_history` | `service_date`, `slot`, `item_base`, `client_name` | Item-level history |
| `week_signatures` | `week_start`, `week_signature`, `client_name` | Week-level hash |

### Slot expansion

Base slot names (e.g. `veg_dry`) get expanded to indexed slot ids (`veg_dry__1`,
`veg_dry__2`) based on `slot_count_overrides`. Rules operate on the expanded
ids; `_base_slot()` strips the suffix when needed.

### Default theme schedule

| Weekday | Theme |
|---|---|
| Monday | Mix (south + north) |
| Tuesday | Chinese |
| Wednesday | Biryani |
| Thursday | South Indian |
| Friday | North Indian |

Overridable per client via `theme_overrides`.

---

## Output formats

### UI theme badges

| Theme | Badge background |
|---|---|
| Mix | `#22543d` |
| Chinese | `#7c2d12` |
| Biryani | `#7f1d1d` |
| South | `#1e3a5f` |
| North | `#4c1d95` |

### Color suffixes

Items carry a single-letter color code from the ontology: `R`, `G`, `B`, `Y`,
`W`, `O`, `K`.

### CSV download

The **Download CSV** button exports a plain-text CSV, one slot per row, one
weekday per column. Color suffixes are stripped; slot names are display-
formatted (`veg_dry` → `Veg Dry`).
