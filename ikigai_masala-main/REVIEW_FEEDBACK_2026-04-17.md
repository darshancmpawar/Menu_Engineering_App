# Technical Review Feedback (2026-04-17)

This report captures a direct code-quality and architecture review of the app,
including correctness, modularization, rule system quality, traceability,
optimization posture, and maintainability risks.

## What was checked

- Architecture and flow docs (`ARCHITECTURE.md`).
- Frontend entrypoint and UI flow (`app.py`).
- API orchestration and request lifecycle (`api/app.py`).
- Configuration/data access (`src/client/client_config.py`, `src/db.py`).
- Solver composition/modularity (`src/solver/menu_solver.py`, `src/solver/solver_context.py`).
- Rule loader and extension mechanism (`src/menu_rules/menu_rule_loader.py`).
- Test and lint signals (`pytest -q`, `ruff check .`).
- Import-graph circularity scan (custom AST script).

## High-confidence findings

### 1) There is at least one production-breaking bug in UI flow

- `app.py` references `backend_ok` in sidebar logic, but this symbol is never defined.
- This will raise a `NameError` when that branch executes.

Impact: severe reliability issue in the primary UI path.

### 2) Runtime depends hard on Supabase with weak local/test fallback

- `src/db.py` unconditionally expects either Streamlit secrets or env vars and then creates a live Supabase client.
- API endpoints call `ClientConfigLoader()` and history lookup paths that rely on real Supabase I/O.
- In non-provisioned environments this fails hard (observed in tests).

Impact: brittle local dev and CI behavior; reduced portability.

### 3) The test suite is strong in breadth but not fully green right now

- Pytest discovered 317 tests; 315 passed, 2 failed (`tests/test_api.py`).
- Failures are in API path assumptions (`/clients`, `/plan`) under current environment.

Impact: confidence is high overall, but release readiness is gated by API-env coupling.

### 4) Lint debt exists and includes real defects, not just style

- `ruff check .` reports an undefined name (`backend_ok`) and multiple unused imports.
- There are also several module-import-order and hygiene issues indicating codebase drift.

Impact: medium. Hygiene debt slows maintenance and can hide logic defects.

### 5) Circular import appears in static graph (likely non-runtime but still a smell)

- Static scan found cycle: `src.solver.menu_solver -> src.solver.solver_context -> src.solver.menu_solver`.
- This is currently softened by `TYPE_CHECKING`, but still indicates tight coupling in core solver internals.

Impact: low-medium today, can become high if type-only imports become runtime imports later.

## Modularization assessment

### What is good

- Clear major boundaries: UI (`ui/`, `customisation/`), API (`api/`), domain logic (`src/solver`, `src/menu_rules`, `src/preprocessor`), and auth (`user_authentication/`).
- Rule system is modular and extensible via a registry + JSON config (`MenuRuleLoader.RULE_CLASSES`).
- Solver extracted into reusable methods (`_build_cells`, `_solve_cpsat`, `_build_objective`, etc.), improving readability compared to monolithic CP-SAT scripts.

### Where it is over/under done

- **Under-modularized**: `api/app.py` carries too much orchestration responsibility (request parsing, history loading, config derivation, solver setup, response formatting).
- **Over-coupled**: solver internals and rule context depend on a wide shared context dict; this makes isolated reasoning/testing harder.
- **Legacy clutter**: separate `Old menu app/` tree exists alongside current app; this risks confusion and accidental drift.

Verdict: modularization is directionally good but not yet “clean architecture”. It is **partially correct, partially over-coupled in orchestration/core boundaries**.

## Rule system quality

- Rule-loader approach is solid and scalable.
- Per-client rule extension (`load_for_client`) is a good design choice.
- Risk: rule application catches broad errors and continues; this protects uptime but can silently degrade rule enforcement.

Recommendation: fail fast for hard constraints, soft-log only for optional/bonus rules.

## Traceability and observability

Current state is mixed:

- Positive: logging exists in API and auth.
- Gaps:
  - No request correlation IDs across frontend/API/solver logs.
  - No persisted solver diagnostics (attempt count, infeasible reasons by rule group, pool shrink reasons per slot/day).
  - Errors returned as strings without stable machine-readable error codes.

Recommendation: add structured logging + event IDs + error code taxonomy.

## Optimization/performance posture

- Solver uses multi-restart and capped candidate pools, which is a practical optimization.
- Pre-filter caching by `(day, base_slot)` is good.
- Potential hotspots remain in repeated DataFrame filtering and repeated pre_filter calls per rule per slot.

Recommendation: memoize rule-filter stages where deterministic; profile with real data before deeper refactors.

## Dead code / insignificant artifacts

- Unused imports across app, solver, tests, and helper modules (from Ruff output).
- Potentially stale/legacy folder (`Old menu app/`) in same repository scope.
- Misc scripts print-based output and weak integration with logging.

Recommendation: run periodic dead-code/lint cleanup and isolate archival assets.

## Direct, non-diplomatic overall verdict

- This app is **not bad**—core concept, rule architecture, and solver strategy are strong.
- But it is **not production-clean yet** due to a confirmed UI bug, environment-coupled API paths, and non-trivial hygiene debt.
- Biggest risk is not algorithm quality; it is operational robustness + maintainability under team scale.

## Priority improvements (ordered)

1. **Fix correctness first**
   - Remove/replace undefined `backend_ok` branch in `app.py`.
   - Add regression test for frontend backend-start path.

2. **Decouple infrastructure for reliability**
   - Add explicit DB provider interface with test/local fake implementation.
   - Move Supabase wiring to composition root; avoid hidden runtime globals where possible.

3. **Refactor API orchestration into services**
   - Extract input validation, history context building, and solver invocation into service modules.
   - Keep route handlers thin and declarative.

4. **Make rule enforcement explicit**
   - Categorize rules: hard/soft/optional.
   - Hard-rule apply failures should fail request with diagnostic payload.

5. **Improve traceability**
   - Introduce `request_id` propagated from UI -> API -> solver logs.
   - Capture and expose solve telemetry (attempt seeds, pool warning counts, rule timings).

6. **Hygiene and debt reduction**
   - Run and enforce Ruff in CI (at least F/E checks first).
   - Remove unused imports/variables and archival duplication from active code paths.

7. **Performance tuning after correctness/ops**
   - Add profiling hooks around pre-filter and CP-SAT build steps.
   - Optimize only measured hotspots.

## Suggested acceptance gates before calling this “clean”

- All tests pass in CI with no external Supabase dependency by default.
- Lint passes for undefined names and unused code classes.
- Frontend smoke test validates generate/list-client flow.
- API returns stable error codes, not only free-text strings.
- Solver telemetry available for post-mortem debugging.
