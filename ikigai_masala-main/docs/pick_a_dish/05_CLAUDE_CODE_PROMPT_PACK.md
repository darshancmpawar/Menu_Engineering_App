# 05 · Claude Code prompt pack — Pick a dish

Status: **Draft** · written 13 Oct 2026

How to use: copy the documents into the repo first (suggested path `ikigai_masala-main/docs/pick_a_dish/`: files 01–04 and 06, plus `PICK_A_DISH_WORKORDER.md`). Start a fresh Claude Code session per phase. Paste the **kickoff prompt** once, then **one phase prompt**. Do not paste several phases at once: each ends at a gate that needs your decision.

---

## A. Kickoff prompt (paste at the start of every session)

```
You are working in the Menu_Engineering_App repo (Ikigai Masala, ikigai_masala-main/).
We are building the "pick a dish" feature: on the menu table, a planner switches the
control from Auto to Pick and searches the CITY item list to put a specific dish in a cell.

Read these, in this order, before doing anything:
1. CLAUDE.md and docs/repo_map.md (notes 9, 27, 28, 31, 32, 39 especially)
2. docs/pick_a_dish/01_DECISION_LOG.md   (D1-D5 are FIXED. O1-O8 are open: do not guess them)
3. docs/pick_a_dish/PICK_A_DISH_WORKORDER.md
4. docs/pick_a_dish/02_API_CONTRACT.md, 03_INTERACTION_SPEC.md, 04_RULES_AND_AUDIT_SPEC.md,
   06_TEST_AND_ACCEPTANCE_CHECKLIST.md

Ground rules:
- Follow CLAUDE.md: smallest change that works, measure before deciding, a rule that cannot
  act must say so, mark simplifications with a `ponytail:` comment naming the ceiling.
- Never edit data/raw/city_items/*.xlsx.
- A pick is NOT a solve. Never reuse the "pinned dish not eligible, solve normally" path:
  a pick never silently becomes a different dish.
- Do exactly the phase I name. At the end of the phase, run its gate from doc 06, report
  the result, and STOP. Do not start the next phase.
- Anything marked [unverified] in the docs must be verified (read the code, run it) before
  you rely on it. Report what you found, including when it contradicts the docs.
- If a gate fails, stop and show me the measurement. Do not work around it.

Reply first with: (a) the files you read, (b) any contradiction between the docs and the
code, (c) your plan for this phase in under 15 lines. Wait for my "go".
```

---

## B. Phase prompts

### Phase 0 · Baseline (no behaviour change)

```
PHASE 0 - baseline.
Goal: a green, recorded starting point.
Do:
1. pip install -r requirements.txt -r requirements-dev.txt (flask_cors is needed by 4 tests).
2. Run `pytest tests -q`. Record the pass/fail/skip counts in docs/pick_a_dish/BASELINE.md.
3. Run the slow all-clients sweep once (`pytest tests/test_all_clients_generate.py -m slow`)
   and record its result and duration. If it is too slow for this environment, say so and
   record what you ran instead.
4. Capture a golden snapshot: solve 3 clients x 1 start date through /api/v1/plan with a
   fixed seed and save the JSON under tests/data/golden_pick/ for gate G1.
Do not change any source file.
Gate G0: BASELINE.md exists and the numbers are real. Report and stop.
```

### Phase 1 · Pinned set and the `/regenerate` guard

```
PHASE 1 - pinned set and regenerate guard (doc 04 section 2.3, doc 02 section 3).
Goal: one pure function that says which cells are pinned, usable without a solve.
Do:
1. In src/solver/menu_solver.py, the stamping block at the end of solve() builds
   `pinned` (CONST_SLOTS, forced_items, client constants). Extract it into a small pure
   function (dates, cfg.const_slots, skip_cells, forced_items, client constants -> set of
   (date, slot_id)). Call it from solve(). Behaviour must not change.
2. In api/app.py regenerate_cells(): if any replace_slots cell is pinned, return 400 with
   {"success": false, "code": "pinned_cell", "error": ..., "details": ...} and solve nothing.
3. Tests: unit test for the pure function; regenerate rejects a pinned cell; regenerate with
   no pinned cell is unchanged.
Gate G1: /plan output for the Phase 0 golden snapshots is BYTE-IDENTICAL, and all existing
tests still pass. Report the diff result and stop.
```

### Phase 2 · `/api/v1/pick` without the audit

```
PHASE 2 - POST /api/v1/pick, stamping and guards only (doc 02, doc 04 sections 2-4).
Precondition: open questions O1, O2, O7 and O8 in doc 01 must show an OWNER ANSWER, not a
"proposed default". If any still shows a default, STOP and ask me. Do not choose for me.
Do:
1. New module src/solver/picker.py: validate, guard, stamp. New route /api/v1/pick in
   api/app.py with @rate_limit("diagnose") and NO @solver_gate.
2. Guards in the order of doc 02 section 2.2: shape, client/counter, dates, cell exists,
   pinned (Phase 1 function), category (city list, NOT the client-narrowed pools),
   week rule (doc 04 section 3), then stamp.
3. The week rule includes saved history. Read history through the same source the cooldown
   uses. Exclude history rows whose dates are inside the plan's dates (doc 04 section 3.3).
   Verify, and report, how multi-counter history is stored before writing the check.
4. Stamp with the solver's colour-suffix helper. Return the formatted solution with is_manual.
5. audit is NOT implemented yet: return "exceptions": [], and the checked/not_checked lists
   as {"checked": [], "not_checked": ["audit not implemented"]}.
Tests: doc 06 A-01 to A-14, A-21 (A-21 for every base slot).
Gate G2: all those tests pass; a pick changes ONLY the target cell; /pick never calls CP-SAT.
Report and stop.
```

### Phase 3 · Audit v1

```
PHASE 3 - the audit (doc 04 sections 5-6).
Do:
1. Implement detectors in order: cooldown, client_pool, ricebread_gap, pre_filter rule probe,
   plate-check regression. Build filter_ctx exactly as _build_day_base_pool_cache does (read it
   first and report the keys). Build the day's dish dicts the way /explain does.
2. A rule that raises is skipped and named in not_checked. Never fatal.
3. checked and not_checked are ALWAYS present in the response.
4. Report only what the pick changed (a plate check failing before the pick is not reported).
Tests: doc 06 A-15 to A-20, A-22.
Gate G3: tests pass. Gate G4: measure /pick server time on 5 counters (the widest first) and
report min/median/max. If the median is over 2 seconds, STOP and show the breakdown.
```

### Phase 4 · Component and Streamlit wiring

```
PHASE 4 - UI (doc 03; doc 02 for the client call).
Do, in this order:
1. ui/api_client.py: pick(...) mirroring regenerate(...).
2. ui/menu_table.py: `manual` set in day_cells; pick_request() with the same nonce guard as
   regen_request; menu_table() gains dishes, exceptions, client_cooldown_days args.
3. app.py: _apply_pick(): call api.pick, update the block (plan, solution, nonveg, pinned,
   manual, exceptions), push an undo snapshot, add to regen_seen, append to changes_log with
   kind "pick", st.rerun(). On error show st.error and leave the plan unchanged.
4. Dish list: build from the full city dataframe (D4), cached per client/city/dates. Measure
   its JSON size and the rerun time before and after (gate G5). If it fails the gate, switch
   to GET /api/v1/pick-candidates (doc 02 section 4) and tell me.
5. ui/menu_table/index.html: mode toggle, in-cell input, results panel under the row, locked
   results, keyboard map, combobox attributes, Exceptions section with the coverage line.
   CRITICAL: while Editing, typing updates only the results container (and re-measures
   height). Never rebuild the table on a keystroke or the input loses focus.
6. Auto mode must behave exactly as before.
Tests: doc 06 U-01 to U-12 and the end-to-end test E-01 through fake_supabase.
Gates: G5 (payload and rerun), G6 (Auto unchanged, existing tests green).
Then give me the manual QA script results from doc 06 section 5. Report and stop.
```

### Phase 5 · Docs and release

```
PHASE 5 - docs and release (docs/pick_a_dish/07_RELEASE_AND_DOCS.md).
Do:
1. Add the endpoint rows and sections to docs/api.md.
2. Add the /api/v1/pick row (section 3) and src/solver/picker.py row (section 4) to
   docs/repo_map.md, and the design note (next free number) from doc 07. Keep rows to one line.
3. Add the architecture paragraph to docs/architecture.md.
4. Draft the version document under version_control/versions/phase-2/ per
   version_control/README.md, as STATUS Draft. Do NOT tag or finalize: the version number needs
   Project Manager approval (doc 01, O6).
5. Update CURRENT.md only if I tell you the version is approved.
Gate G7: every claim in the version document matches what the code does. List any claim you
could not verify. Report and stop.
```

---

## C. Stop-and-report template (use when a gate fails)

```
GATE <id> FAILED.
Measured: <numbers or test output>
Expected: <the gate's requirement>
What I think is the cause: <one paragraph, labelled as a hypothesis>
Options: (1) <option> - cost <x>, (2) <option> - cost <y>
I have not changed anything to work around this.
```

---

## D. Review prompt (after any phase)

```
Review the diff of this phase against docs 02, 03 and 04 only. List: (1) every place the code
disagrees with the docs, (2) every [unverified] item you did not verify, (3) any path where a
pick could silently become a different dish, (4) any new behaviour not described in the docs.
Do not fix anything. Report.
```

---

## E. Rules for the person driving the session

* One phase per session; start the next only after you have read the gate report.
* Answer open questions in doc 01 **before** Phase 2. If you do not, Claude Code is instructed to stop and ask.
* Treat `[unverified]` as work to do, not as a fact.
* Never accept "tests pass" as a gate on its own; each gate names a measurement.
