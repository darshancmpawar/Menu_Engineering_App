# Architecture

```mermaid
graph TD
    subgraph UI ["Streamlit (app.py, customisation/, user_authentication/)"]
        MP[Menu Planner]
        CE[Customisation Editor]
        AU[Login / User Admin]
    end

    subgraph API ["Flask API (api/app.py)"]
        AUTH[/auth/login/]
        PLAN[/plan/]
        REGEN[/regenerate/]
        SAVE[/save/]
        CONFIG[/client-config/]
    end

    subgraph Core ["Engine (src/)"]
        POOLS[PoolBuilder]
        SOLVER[MenuSolver CP-SAT]
        RULES[MenuRules]
        HIST[HistoryManager]
        FMT[SolutionFormatter]
    end

    subgraph Data ["Data layer"]
        XLS[(data/raw/menu_items.xlsx)]
        CFG[(data/configs/*.json)]
        SUPA[(Supabase)]
    end

    UI -- HTTPS + Bearer --> API
    API --> Core
    POOLS --> XLS
    RULES --> CFG
    HIST --> SUPA
    SOLVER --> FMT
    API --> SUPA
```

## Layer overview

| Layer | Location | Responsibility |
|---|---|---|
| Frontend | `app.py`, `customisation/`, `user_authentication/`, `ui/` | Streamlit views, login form, API client |
| API | `api/app.py`, `api/auth.py`, `api/concurrency.py`, `api/logging_config.py`, `api/metrics.py` | REST surface, bearer-token auth, concurrent-solve gate, structured logging, in-process counters |
| Solver | `src/solver/` | CP-SAT model, multi-restart strategy, regeneration, solution formatting |
| Rules | `src/menu_rules/` | Hard/soft/pre-filter constraints, loaded from JSON |
| Preprocessor | `src/preprocessor/` | Excel ingest, column mapping, data cleanse, per-slot pool build |
| Client/History | `src/client/`, `src/history/` | Supabase-backed client config and menu history |
| Shared | `src/db.py`, `src/constants.py` | Supabase singleton, slot/flag constants |

## Key design choices

- **Cell-based CP-SAT:** one bool variable per `(day, slot, candidate item)`. Enables per-item bonuses / penalties and targeted regeneration.
- **Two-phase rules:**
  1. `pre_filter_pool()` — cheap removals before CP-SAT vars exist.
  2. `apply()` + `get_objective_terms()` — hard constraints and soft bonuses / penalties on the model.
- **Hard vs. soft severity:** rules declare `severity = HARD` (default) or `SOFT`. A hard rule that raises in `apply()` fails the solve instead of silently dropping the constraint; soft rules log + continue + surface in the response's `rule_warnings`.
- **No config cache:** `ClientConfigLoader` reads Supabase on every call so edits are live with no restart. Per-request memoization on Flask's `g` avoids the intra-request round trips.
- **Dynamic worker allocation:** `api/concurrency.py` caps concurrent solves (`MAX_RUNNING=2`) and tunes CP-SAT worker count to RAM (1 active → 9 workers, 2 active → 5 each).
- **History split:** `menu_history` is item-level (one row per `(date, slot, item)`), `week_signatures` is week-level (a deterministic `|`-delimited hash of a saved week). The former drives item cooldown; the latter drives week-signature cooldown.
- **Optimistic concurrency:** the `clients` table carries a `version` column. `GET /client-config` returns it as an ETag; `PUT` must send it back, mismatch returns 409 so two admins editing the same client can't last-write-wins.

## Key flows

### Login

```mermaid
sequenceDiagram
    participant U as User
    participant S as Streamlit
    participant F as Flask
    participant DB as Supabase

    U->>S: email + password
    S->>F: POST /api/v1/auth/login
    F->>DB: SELECT users WHERE email=...
    DB-->>F: row (or none)
    F->>F: bcrypt verify
    F->>F: issue_token (HMAC w/ API_SECRET_KEY)
    F-->>S: { token, role, profile_name }
    S->>S: store token in session_state
```

### Generate menu

```mermaid
sequenceDiagram
    participant S as Streamlit
    participant F as Flask
    participant L as ClientConfigLoader
    participant H as HistoryManager
    participant M as MenuSolver

    S->>F: POST /api/v1/plan (Bearer)
    F->>L: get_client(name) (Supabase)
    F->>H: load history from Supabase
    H-->>F: banned items, rice-bread bans, recent signatures
    F->>M: pools + config + rules + history context
    M->>M: pre_filter pools, build CP-SAT, solve (multi-restart)
    M-->>F: week_plan + rule_failures
    F-->>S: { solution, pool_warnings, rule_warnings }
```

### Save

Streamlit → `POST /api/v1/save` → `HistoryManager.save()` writes rows into `menu_history` and a row into `week_signatures`. Color suffixes (`(R)`, `(Y)`, …) are stripped before persistence so cooldown matching is color-agnostic.

### Regenerate

Streamlit → `POST /api/v1/regenerate` → `MenuRegenerator` locks every cell not marked for replacement and re-runs the solver. A similarity penalty steers the solver away from re-picking the same items.
