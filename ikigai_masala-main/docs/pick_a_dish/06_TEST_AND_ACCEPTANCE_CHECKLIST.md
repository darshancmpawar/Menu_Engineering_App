# 06 · Test and acceptance checklist — Pick a dish

Status: **Draft** · written 13 Oct 2026

"Done" is defined here. Each row is pass/fail. A gate is a **measurement**, not "tests pass". Where a number is a `[proposal]`, the owner may change it after the first measurement.

Test locations follow the repo: API and rule tests under `tests/` (API-level tests can follow `tests/rules/test_theme_slot_pools.py::_solve`, which drives `/api/v1/*` through `fake_supabase`); UI pure-function tests under `tests/ui/`.

---

## 1. Gates

| Gate | Phase | Requirement | How measured | Pass? |
|---|---|---|---|---|
| **G0** | 0 | A recorded green baseline | `BASELINE.md` with real counts; golden `/plan` snapshots saved | ☐ |
| **G1** | 1 | Extracting the pinned-set function changes nothing | `/plan` JSON for the golden snapshots is **byte-identical** before and after; full suite green | ☐ |
| **G2** | 2 | A pick changes only the target cell and never solves | A-01 to A-14, A-21 pass; test asserts CP-SAT is not constructed on `/pick` | ☐ |
| **G3** | 3 | The audit detectors work and coverage is honest | A-15 to A-20, A-22 pass | ☐ |
| **G4** | 3 | `/pick` is fast `[proposal]` | server time over 5 counters (widest first): median under 2 s; record min, median, max | ☐ |
| **G5** | 4 | The embedded dish list is affordable `[proposal]` | JSON size under 300 KB per plan; Streamlit rerun time with Pick data vs without; no perceptible slowdown (record both). If it fails, switch to `GET /pick-candidates` | ☐ |
| **G6** | 4 | Auto mode is unchanged and nothing regressed | U-12 passes; `pytest tests -q` equals the Phase 0 baseline plus the new tests; slow all-clients sweep shows no new INFEASIBLE and no change in relaxation counts | ☐ |
| **G7** | 5 | Documents match the code | Every claim in the version document traced to code or a test; unverifiable claims listed | ☐ |

---

## 2. API and rule tests (`A-*`)

Fixtures: one Bangalore client (for example Zscaler) with a counter that has `veg_gravy`, `veg_dry`, `rice`, `dal`, `dessert`, a pinned staple row, and one pinned dessert on a mid-week day. Add a second counter or client with a `curd_side` slot for the repeatable-slot test.

### 2.1 Contract and integrity
| ID | Test | Expected |
|---|---|---|
| A-01 | Clean pick of a dish that fits | 200, `changed: true`, `exceptions: []`, dish in the cell |
| A-02 | Any pick | Every cell not named in `picks` is byte-identical to the request's `base_plan` |
| A-03 | Two picks in one request, the second invalid | 400; **neither** pick is applied (atomic) |
| A-04 | Pick the dish already in the cell | 200, `changed: false`, plan unchanged, no exception |

### 2.2 Guards
| ID | Test | Expected |
|---|---|---|
| A-05 | Pick on a staple cell (`white_rice`, `papad`, `pickle`, `chutney`) | 400 `pinned_cell` |
| A-06 | Pick on a `forced_items` pin and on a client-constant pin; `/regenerate` with a pinned cell in `replace_slots` | 400 `pinned_cell` each; `/regenerate` with no pinned cell is unchanged |
| A-07 | Dish that is not a dish of the cell's base slot in the city list; dish that does not exist | 400 `not_a_slot_dish` |

### 2.3 The week rule (D5)
| ID | Test | Expected |
|---|---|---|
| A-08 | Dish already in another cell of the same week in the plan | 400 `week_repeat`, `source: "plan"`, `on` is that date; plan unchanged |
| A-09 | Same dish picked for two cells in one request | 400 `week_repeat`, `source: "pick"` |
| A-10 | Dish served earlier in the same week in **saved history**, outside the plan's dates | 400 `week_repeat`, `source: "history"` |
| A-11 | **Self-block trap:** history rows for the **same dates** as the plan (the plan was saved earlier) | They are ignored; replacing a dish with a fresh dish is allowed |
| A-12 | Repeatable slots (`curd`, `curd_rice`) and rule-declared staples | Exempt: the same dish on two days is allowed |
| A-13 | A dish served 3 days ago in the same week | 400 `week_repeat` (not a 200 with a cooldown warning): D5 runs before the cooldown |
| A-14 | A dish served last week, inside the 21-day cooldown | 200 with a `cooldown` violation, **not** a block |

### 2.4 The audit
| ID | Test | Expected |
|---|---|---|
| A-15 | Dish inside the cooldown window, not same week | `cooldown` violation with `days_ago` and `window_days` |
| A-16 | Dish on the city list but not in the client's narrowed pool | `client_pool` violation |
| A-17 | Bread on a rice-bread-gap ban day | `ricebread_gap` violation |
| A-18 | A rule whose `pre_filter_pool` removes the dish (for example a theme filter) | `rule:<name>` violation, reported once |
| A-19 | A rule whose `pre_filter_pool` raises | Pick still succeeds; `not_checked` contains `rule:<name> (errored)` |
| A-20 | A pick that makes a passing plate check fail; and a check already failing before the pick | The first is reported as `plate:<check>`; the second is **not** reported |
| A-21 | One dish per base slot, picked and stamped | Colour suffix and ontology spelling match what the solver writes for that row; a later `/save` stores the ontology spelling |
| A-22 | Every 200 response | `checked` and `not_checked` present (arrays), with the entries in doc 04 §6 |

---

## 3. UI tests (`U-*`) and end-to-end (`E-*`)

| ID | Test | Expected |
|---|---|---|
| U-01 | `pick_request` called twice with the same nonce | Second returns `None` (replay-safe) |
| U-02 | `pick_request` splits the cell key on `|` into `(slot_id, iso)` | Correct pair, not swapped |
| U-03 | `day_cells` with a `manual` set | The cell carries `manual: true`; pinned and manual are independent |
| U-04 | Pinned cell | No selectable key / flag; cannot be picked or regenerated |
| U-05 | Search matching: exact, prefix, substring, underscores, multi-token | Order as doc 03 §5.2 |
| U-06 | Results ordering | Fits before warnings; locked rows last; current dish never listed |
| U-07 | Locked rows | Not selectable by click, Enter or arrow keys; arrow keys skip them |
| U-08 | Apply a warned pick, then Undo last | Original dish back; marker and Exceptions entry removed |
| U-09 | Pick, pick again in the same cell, Undo from the Exceptions entry | Restores the **original auto** dish |
| U-10 | Mode switch | Clears selection and closes the edit; plan unchanged |
| U-11 | Focus | Typing in the input does not rebuild the table; focus and caret survive keystrokes (component test or scripted manual check) |
| U-12 | Auto mode regression | Select, regenerate and Clear behave exactly as in the Phase 0 baseline |
| E-01 | End to end through `fake_supabase`: plan, pick (clean), pick (warned), pick (blocked week repeat), regenerate another cell, save | Pick locked in place after regenerate; blocked pick leaves plan unchanged; save stores ontology spellings |

---

## 4. Non-functional checks

| Check | Requirement |
|---|---|
| No solve on `/pick` | A test fails if `MenuSolver` or a CP-SAT model is constructed |
| No second pinned definition | Pinned logic exists once (the extracted function) |
| No silent substitution | A grep-style test: `/pick` code path never reaches the "solving the cell normally" fallback |
| Rule instance isolation | Audit uses fresh rule instances (repo note 27); a concurrency test is not required for v1 but the audit must not store state on shared rules |
| Docs lint | `docs/repo_map.md` rows stay one line; `docs/api.md` lists the new endpoint |

---

## 5. Manual QA script (run by a person, in the real Streamlit app)

Setup: a Bangalore client with a 5-day plan, one pinned dessert, the staple rows, and at least one dish served within the last 21 days (check history).

| # | Step | Expected | ☐ |
|---|---|---|---|
| 1 | Open the table. Mode shows **Auto** | Same as before this feature | ☐ |
| 2 | Select two dishes, press Regenerate selected | Behaves as before | ☐ |
| 3 | Switch to **Pick** | Selection clears; status says to click a dish | ☐ |
| 4 | Click a veg gravy cell | The cell becomes an empty, focused input; results open under its row | ☐ |
| 5 | Type `paneer` slowly | Results update on every key; the input never loses focus | ☐ |
| 6 | Look at a result for a dish already on another day this week | It is greyed, listed after the others, with the lock chip; click and Enter do nothing | ☐ |
| 7 | Arrow down through the results | The highlight skips locked results | ☐ |
| 8 | Pick a dish with "Fits" | Cell shows the pencil marker, neutral; status says it fits every check | ☐ |
| 9 | Pick a dish with a cooldown chip | Cell turns amber; Exceptions section appears with the warning | ☐ |
| 10 | Pick a dish that is not in the client's pool | Warning for the pool; applied | ☐ |
| 11 | Read the line under Exceptions | It names what was checked and what was **not** checked | ☐ |
| 12 | Press Esc during an edit | Edit closes; plan unchanged; focus back on the cell | ☐ |
| 13 | Click the pinned dessert and a staple | Pinned message; nothing changes (in Pick **and** Auto) | ☐ |
| 14 | Undo last pick | Dish, marker and Exceptions entry revert | ☐ |
| 15 | Select a picked cell in Auto and regenerate it | Pick replaced; marker gone | ☐ |
| 16 | Regenerate a different cell | The pick stays | ☐ |
| 17 | Save the plan, reload it | Dishes saved with ontology spellings; note that exceptions are **not** restored (decision O3) | ☐ |
| 18 | Try the same actions from a second browser tab with a stale plan | Server rejects a pinned or week-repeat pick with a clear message | ☐ |
| 19 | Keyboard only | Every step above is possible without a mouse | ☐ |
| 20 | Phone width | The input is not hidden by the on-screen keyboard `[unverified]` | ☐ |

---

## 6. Measurement sheets

### 6.1 G4: `/pick` server time (seconds)
| Counter | City | Slots | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |

### 6.2 G5: dish-list payload and rerun time
| City | Pickable slots | Dishes embedded | JSON size (KB) | Rerun without data (s) | Rerun with data (s) |
|---|---|---|---|---|---|
| | | | | | |

### 6.3 G6: regression comparison
| Measure | Phase 0 | After Phase 4 | Same? |
|---|---|---|---|
| `pytest tests -q` passed / failed / skipped | | | ☐ |
| All-clients sweep: INFEASIBLE count | | | ☐ |
| All-clients sweep: relaxation counts | | | ☐ |
| Golden `/plan` snapshots byte-identical | | | ☐ |

---

## 7. Definition of done

All of the following:

1. Gates G0 to G7 pass and are recorded.
2. A-01 to A-22, U-01 to U-12 and E-01 pass; the manual script is signed.
3. Every `[unverified]` item in docs 01 to 04 is either verified (with the finding written next to it) or explicitly deferred by the owner.
4. Open questions O1, O2, O7, O8 have owner answers; O3 matches the on-screen copy.
5. The mockup corrections in doc 03 §11 are made.

---

## 8. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Developer (builder) | | ☐ Ready for review | |
| Reviewer | | ☐ Gates verified | |
| Owner | | ☐ Accepts behaviour (decisions D1–D5, O1–O8) | |
| Project Manager (version approval) | | ☐ Approves the version number | |
