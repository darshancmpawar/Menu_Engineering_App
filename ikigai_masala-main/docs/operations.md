# Operations

Day-2 stuff: how to test, how to debug a broken deploy, and what CI does.

---

## Testing

```bash
pytest                                    # default: fast unit + integration, skips @slow
pytest -v                                 # verbose
pytest tests/test_solver.py               # one file
pytest -m slow                            # only the real-Excel / full-pipeline tests
pytest -m ""                              # everything, including slow
pytest --cov=src --cov=api --cov-report=term-missing
```

Markers (defined in `pytest.ini`):

- `slow` — real Excel, real rules, multi-day solve. Skipped by default.
- `unit`, `integration` — available for future marking.

### Fixtures of note

Defined in `tests/conftest.py`:

- `project_root_path`, `sample_data_path`, `ensure_sample_data_exists`
- `fake_supabase` — installs an in-memory fake as the Supabase client so
  API and solver tests run without a live database.

---

## CI

`.github/workflows/ci.yml` runs three jobs in parallel on every PR:

- `pytest` — full suite (slow tests skipped).
- `ruff check --select=F,E9` — real-bug ruleset (undefined names, syntax
  errors, unused imports). Style rules are intentionally out of scope for
  now.
- `bandit -ll -r api src scripts` — medium+ severity security findings.

A fourth job — `slow-tests` — runs only on push to `main` and manual
`workflow_dispatch` triggers, so PR feedback stays fast.

### Coverage gate

The `pytest` CI job enforces `--cov-fail-under=82`. Configuration lives in
`.coveragerc`: measured surface is `api/`, `src/`, and `ui/`, and the
Streamlit-UI modules that can't be unit-tested (`ui/styles.py`,
`customisation/*`, `app.py`) are omitted. Current baseline ≈ 83.9%.

Local runs stay plain `pytest` (no coverage) for fast iteration. Measure
coverage locally the same way CI does:

```bash
pytest --cov --cov-report=term-missing
```

When a PR durably raises the baseline, bump the floor in
`.github/workflows/ci.yml` as part of the same change so the gate keeps
progressing upward instead of re-settling at the old number.

---

## Logs + metrics

### Structured logs

Set `LOG_FORMAT=json` to emit one JSON line per log record. Every line
carries `ts`, `level`, `logger`, `msg`, `request_id`, plus any caller-
supplied `extra=` fields. The API's access log lands on `logger="api.app"`
with `msg="http_request"` and fields `method`, `path`, `status`,
`duration_ms`, `remote_addr`.

Successful `/health` requests are intentionally quiet; failing ones show up.

### Metrics

`GET /api/v1/metrics` returns an in-process counter snapshot.
Counters populated by the API:

- `plan_requests_total{outcome="success"|"solver_error"}`
- `regenerate_requests_total{outcome="success"|"solver_error"}`
- `solver_failures_total`
- `rule_failures_total{rule=...}`

Counters reset only on process restart. No histograms or gauges yet —
`api/metrics.py` is deliberately tiny so a future swap to
`prometheus_client` / statsd stays a one-file change.

---

## Streamlit-side caches

Two small caches make the planner UI snappy without compromising
freshness:

- `MenuApiClient` is built via `@st.cache_resource` keyed by
  `backend_url` — the underlying `requests.Session` (and its connection
  pool) survives across Streamlit reruns instead of being torn down on
  every widget interaction.
- the client list (`list_clients_with_city()`, which also feeds the
  sidebar's city filter) is cached with `@st.cache_data` for 60 seconds
  so the picker doesn't hit the API on every rerun. The customisation
  editor's create / delete handlers call `st.cache_data.clear()` so a new
  or removed client shows up immediately rather than 60s later.

If a stale picker ever shows up in production despite this, the cause
is almost always a mutation that bypassed `customisation/main.py` —
add a `st.cache_data.clear()` call there or just wait 60s.

---

## Adding a city

A city has two files, both named after the city slug, both optional — a city
without them falls back to the default city (`bangalore`) for that half.

1. **Item list** → `data/raw/city_items/<slug>.xlsx`. Never hand-edit a raw
   workbook into place; run the normaliser, which forces the reference column
   set, coerces flags to 0/1 and reports what the list does not cover:

   ```bash
   python scripts/normalize_city_ontology.py pune ~/Downloads/pune_menu_items.xlsx --dry-run
   python scripts/normalize_city_ontology.py pune ~/Downloads/pune_menu_items.xlsx
   ```

   Then declare the categories the list covers in
   `data/raw/city_items/ontology_categories.json`. That declaration is what the
   mandatory-slot check is held to: a city absent from the file must cover
   *every* mandatory slot, which is right for a whole-product list and wrong for
   a city that serves no non-veg station.

2. **Ruleset** → `data/configs/city_rules/<slug>.json`. Either standalone or
   `"extends": "<other city>"` with `disable` + same-name overrides.

3. Set `clients.city` on the client (the editor's step 1). Nothing else changes:
   `/plan` resolves both files from that column.

`MENU_EXCEL_PATH` still pins ONE workbook for every city — useful for a
single-city deployment or a test fixture, and it also switches off the per-city
mandatory-slot declarations (the file's contents no longer follow from the city
name).

Worked example: `docs/pune_rulebook.md` maps `data/raw/source_workbooks/pune_menu_rulebook_101.xlsx`
R1–R70 onto `pune.json` and lists what is not encodable.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Process exits at startup with `Missing required environment variables` | `SUPABASE_URL` or `SUPABASE_KEY` unset / empty | Set in `.streamlit/secrets.toml` or the container env |
| UI shows an `APIError` or writes fail silently | `SUPABASE_KEY` is the publishable / anon key, not service-role | Replace with the `sb_secret_...` / service-role key |
| UI shows `Cannot reach API` | Port 5000 in use, or the spawned Flask thread crashed on startup | Kill the stale process; re-run `streamlit run app.py`. Spawned thread crashes also land in the Streamlit server logs. |
| `/health` returns 503 `status=degraded` | `supabase_reachable=false` — network, DNS, or Supabase itself down | Check the Supabase dashboard; verify URL + key |
| Requests fail with httpx `ReadTimeout` after exactly `SUPABASE_TIMEOUT_SECONDS` | Supabase is up but slow on this query | Bump `SUPABASE_TIMEOUT_SECONDS` (default 5) if your DB legitimately needs more time, but first check the Supabase dashboard for query/index pressure |
| `No feasible plan found (INFEASIBLE)` | Over-constrained rules vs available items, or per-client rule config incompatible | Check `pool_warnings` in the response, re-run with logs at INFO; check `/api/v1/metrics` for `rule_failures_total` |
| 503 `Server at capacity` under load | `solver_gate` queue full; this is the intended backpressure | Retry after a few seconds; clients with the built-in retry (`MenuApiClient`) handle this automatically |
| 504 `Request timed out waiting in queue` | Request waited > `QUEUE_TIMEOUT` (default 300s) | Retry; if it persists the solver is stuck — restart the process |
| 409 on `PUT /client-config` | Another editor changed the same client between your GET and PUT | Refresh the editor (the Streamlit UI does this on save failure) and re-apply |
| `Failed to load config for X: Internal server error` in the customisation editor | Logs say `clients.version column missing — falling back to version=1` (or a `clients.counters` / `clients.city` column-missing warning) | Re-run `scripts/setup_all.sql` in the Supabase SQL editor — it adds the `version`, `counters`, and `city` columns. The editor stays usable in fallback mode, but optimistic-concurrency on PUT (and saved cities) are disabled until the columns exist. |
| Any `Internal server error` toast in the UI | Generic catch-all wrapped a real exception | Read the response body — every 500 carries a `request_id`. Grep the access log (`logger="api.app", msg="http_request"`) for that id; the matching ERROR line a few rows earlier is the real exception with a traceback. |
| `Widening history lookback from 45 to N days` in logs | A per-client rule's `cooldown_days` > 30 triggered the dynamic widening | Informational. Keeps the Supabase window ≥ the longest rule cooldown. |
| `Slot 'X' has 0 items after mapping` at startup | A city ontology does not cover a category the mandatory check requires | If the city genuinely does not serve it, remove it from that city's list in `data/raw/city_items/ontology_categories.json`; if it should be there, the workbook's `course_type` mapping is broken (which is what this check exists to catch) |
| A client's menu draws dishes from the wrong city | `clients.city` unset or not in `AVAILABLE_CITIES`, so the default list is used | Set the city in the editor; `normalize_city` returns None for anything it does not recognise |

---

## Project layout

```
ikigai_masala-main/
├── app.py                    Streamlit entry (spawns Flask)
├── api/
│   ├── app.py                Flask API + request tracing
│   ├── concurrency.py        Solve gate + worker tuning
│   ├── logging_config.py     dictConfig + JSON formatter + ContextVar request_id
│   ├── metrics.py            In-process counters
│   └── config.py             Path/limit constants + env validation
├── src/
│   ├── db.py                 Supabase singleton
│   ├── constants.py
│   ├── solver/               CP-SAT solver, regenerator, formatter
│   ├── menu_rules/           Rule classes + loader
│   ├── preprocessor/         Excel → pools pipeline
│   ├── client/               ClientConfig(Loader), ConcurrentEditError
│   └── history/              HistoryManager
├── ui/                       API client (with retry) + formatters
├── customisation/            Streamlit editor UIs
├── data/
│   ├── raw/city_items/<city>.xlsx   one item list per city + ontology_categories.json
│   └── configs/city_rules/<city>.json  one ruleset per city (+ client_rules.json)
├── scripts/                  Supabase seeders + SQL schema
├── tests/                    Pytest suite
├── docs/                     setup, architecture, api, operations
├── pytest.ini
├── requirements.txt          runtime
└── requirements-dev.txt      runtime + pytest + ruff + bandit
```

For a file-level symbol map optimised for Claude sessions, see
`../CLAUDE.md` at the repo root.
