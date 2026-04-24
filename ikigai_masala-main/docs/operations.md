# Operations

Day-2 stuff: how to test, how to debug a broken deploy, how to roll the
legacy-hash kill switch, and what CI does.

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
- `bandit -ll -r api src user_authentication scripts` — medium+ severity
  security findings.

A fourth job — `slow-tests` — runs only on push to `main` and manual
`workflow_dispatch` triggers, so PR feedback stays fast.

### Coverage gate

The `pytest` CI job enforces `--cov-fail-under=82`. Configuration lives in
`.coveragerc`: measured surface is `api/`, `src/`, `ui/`,
`user_authentication/`, and the Streamlit-UI modules that can't be
unit-tested (`ui/styles.py`, `user_authentication/login_ui.py`,
`user_authentication/session.py`, `user_authentication/user_manager_ui.py`,
`customisation/*`, `app.py`) are omitted. Current baseline ≈ 83.8%.

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
`duration_ms`, `user`, `remote_addr`.

Successful `/health` requests are intentionally quiet; failing ones show up.

### Metrics

`GET /api/v1/metrics` (auth-gated) returns an in-process counter snapshot.
Counters populated by the API:

- `plan_requests_total{outcome="success"|"solver_error"}`
- `regenerate_requests_total{outcome="success"|"solver_error"}`
- `solver_failures_total`
- `rule_failures_total{rule=...}`
- `legacy_sha256_verifications_total{result="success"|"fail"|"disabled"}`
- `auth_legacy_upgrades_total{outcome="success"|"fail"}`

Counters reset only on process restart. No histograms or gauges yet —
`api/metrics.py` is deliberately tiny so a future swap to
`prometheus_client` / statsd stays a one-file change.

---

## Legacy password-hash kill switch

`users.password_hash` currently accepts both bcrypt (current) and a
pre-bcrypt SHA-256 format. The goal is to reach a state where no user
still has a legacy hash, flip the kill switch, and eventually delete the
verification code entirely.

**Playbook:**

1. Watch `legacy_sha256_verifications_total{result="success"}` in
   `/api/v1/metrics`. Every successful login on a legacy hash also triggers
   a warning in the logs.
2. Successful logins transparently rehash to bcrypt —
   `auth_legacy_upgrades_total{outcome="success"}` tracks the drain.
   Failed upgrades (RLS, permission errors) land on `outcome="fail"` and
   log a warning so they don't silently stall.
3. Once the `result="success"` counter stays at 0 long enough to be
   confident, set `AUTH_DISABLE_LEGACY_SHA256=true` in the environment.
   Legacy verifies now return False even for the right password;
   `result="disabled"` counts them so you can see how many users still
   had legacy rows at flip time.
4. If anyone complains, they're a user who never logged in during the
   drain window. Reset their password via the user-management UI. If the
   count stays at 0 for another rotation, cut the PR that deletes
   `_is_legacy_sha256` / `_verify_legacy_sha256`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Process exits at startup with `Missing required environment variables` | `API_SECRET_KEY`, `SUPABASE_URL`, or `SUPABASE_KEY` unset / empty | Set in `.streamlit/secrets.toml` or the container env |
| UI shows `Login error (APIError)` or writes fail silently | `SUPABASE_KEY` is the publishable / anon key, not service-role | Replace with the `sb_secret_...` / service-role key |
| UI shows `Invalid credentials` for a user you just created | Typo in password, or the row was inserted with a malformed hash | Reset via the user-management UI |
| UI shows `Cannot reach API` | Port 5000 in use, or the spawned Flask thread crashed on startup | Kill the stale process; re-run `streamlit run app.py`. Spawned thread crashes also land in the Streamlit server logs. |
| `/health` returns 503 `status=degraded` | `supabase_reachable=false` — network, DNS, or Supabase itself down | Check the Supabase dashboard; verify URL + key |
| `No feasible plan found (INFEASIBLE)` | Over-constrained rules vs available items, or per-client rule config incompatible | Check `pool_warnings` in the response, re-run with logs at INFO; check `/api/v1/metrics` for `rule_failures_total` |
| 503 `Server at capacity` under load | `solver_gate` queue full; this is the intended backpressure | Retry after a few seconds; clients with the built-in retry (`MenuApiClient`) handle this automatically |
| 504 `Request timed out waiting in queue` | Request waited > `QUEUE_TIMEOUT` (default 300s) | Retry; if it persists the solver is stuck — restart the process |
| 409 on `PUT /client-config` | Another admin edited the same client between your GET and PUT | Refresh the editor (the Streamlit UI does this on save failure) and re-apply |
| `Widening history lookback from 45 to N days` in logs | A per-client rule's `cooldown_days` > 30 triggered the dynamic widening | Informational. Keeps the Supabase window ≥ the longest rule cooldown. |

---

## Project layout

```
ikigai_masala-main/
├── app.py                    Streamlit entry (spawns Flask)
├── api/
│   ├── app.py                Flask API + request tracing
│   ├── auth.py               Bearer-token signing / verification
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
├── user_authentication/      Login UI, AuthManager, session helpers
├── data/
│   ├── raw/menu_items.xlsx
│   └── configs/*.json
├── scripts/                  Supabase seeders + SQL schema
├── tests/                    Pytest suite
├── docs/                     setup, architecture, api, operations
├── pytest.ini
├── requirements.txt          runtime
└── requirements-dev.txt      runtime + pytest + ruff + bandit
```

For a file-level symbol map optimised for Claude sessions, see
`../CLAUDE.md` at the repo root.
