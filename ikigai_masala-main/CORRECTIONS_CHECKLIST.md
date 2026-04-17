# Corrections / Modifications Checklist

This is the direct list of items that should be corrected or modified,
ordered by priority.

## P0 — Must fix immediately (correctness / blockers)

1. **Fix undefined variable in frontend (`backend_ok`)**
   - File: `app.py`
   - Problem: `backend_ok` is referenced but never defined.
   - Fix: replace with a deterministic backend-health flag from `_ensure_backend_running()` flow.
   - Add a regression test/smoke check for sidebar client-loading path.

2. **Stabilize API behavior for tests/local runs**
   - Files: `src/db.py`, `api/app.py`, tests using API endpoints.
   - Problem: API endpoints depend on live Supabase availability and credentials.
   - Fix: introduce a provider abstraction (real Supabase vs fake/in-memory provider).
   - Goal: API tests should pass without external DB.

## P1 — High impact (architecture / maintainability)

3. **Split orchestration logic out of `api/app.py`**
   - Move request parsing, validation, history-context assembly, and solver orchestration into service modules.
   - Keep Flask handlers thin (transport-only).

4. **Harden rule execution semantics**
   - Classify rules into hard vs soft.
   - Hard-rule failures should fail request with clear diagnostics.
   - Soft-rule failures can log warnings.

5. **Add stable API error codes**
   - Current responses mostly return free-form strings.
   - Add machine-readable error code field (e.g. `error_code`) consistently.

## P2 — Code quality / hygiene

6. **Clear lint debt and enforce CI gating**
   - Start with Ruff E/F categories (undefined names, unused imports, etc.).
   - Add CI job that fails on new lint regressions.

7. **Reduce coupling in solver typing boundary**
   - Cycle exists at type import boundary between solver modules.
   - Remove back-reference by extracting shared protocols/types into a neutral module.

8. **Clean legacy/stale artifacts from active repo path**
   - Isolate or archive `Old menu app/` to avoid confusion and accidental usage.

## P3 — Traceability / performance improvements

9. **Introduce request-scoped tracing**
   - Add `request_id` through UI -> API -> solver logs.
   - Store solve telemetry (attempts, pool sizes, rule timing, infeasibility hints).

10. **Profile before optimizing solver internals**
   - Measure pre-filter and model-build hotspots with production-like data.
   - Apply memoization/caching only where proven useful.

## Suggested implementation order

- Sprint 1: #1 and #2
- Sprint 2: #3, #4, #5
- Sprint 3: #6, #7, #8
- Sprint 4: #9, #10
