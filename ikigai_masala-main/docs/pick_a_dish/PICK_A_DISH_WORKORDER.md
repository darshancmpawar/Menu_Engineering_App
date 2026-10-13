# Pick a dish (search override) — Work order for Claude Code

Repo `Menu_Engineering_App` (Ikigai Masala, v2.07.03) · written 13 Oct 2026
Design mockup: https://claude.ai/artifact/QmwjUF4X6dotuVLE1KNRGF (4 artboards: select one dish, pick mode, after-apply exceptions, locked/multi-select/collapsed states)

Facts below were read from the repo unless marked **[unverified]**. Nothing here has been run or built yet.

---

## 0. How to use this document

1. Read `CLAUDE.md`, `docs/repo_map.md` and `docs/api.md` first. Follow `CLAUDE.md`: smallest change that works, measure before deciding, a rule that cannot act must say so, mark simplifications with `ponytail:`.
2. Work the phases in §8 in order. Each ends with a gate. **At a failed gate, stop and report the measurement.**
3. Do not edit `data/raw/city_items/*.xlsx`.
4. Build the API first. The Streamlit component is temporary (the tool is migrating to Pulse), so the API contract must stand on its own.

---

## 1. Decisions (final, from the owner)

| # | Decision |
|---|---|
| D1 | On the regenerate control a toggle switches **Auto** (today's regenerate) to **Pick** (search by name, scoped to the cell's category) |
| D2 | A picked dish **may override and violate rules**. Violations are shown as warnings in an **expandable "Exceptions" section** |
| D3 | **Staple and pinned cells cannot be changed** by search or by regenerate |
| D4 | Search scope is the **city item list**, not the client's pool |
| D5 | **Hard rule: the same dish cannot appear twice in a week.** A pick that would repeat a dish already used that week is **blocked**, not warned. This is the one rule search cannot override |

---

## 2. What exists today (and what it means here)

| Fact | Where | Consequence |
|---|---|---|
| Regenerate locks every cell not selected, forbids the old dish, then runs the full CP-SAT solve | `src/solver/regenerator.py`, `POST /api/v1/regenerate` | A normal solve **cannot** hold a rule-violating pick: the dish is filtered out of the cell pool or the model is infeasible |
| Cells are `slot_id|iso` keys. The table lets the user tick cells, then "Regenerate selected" | `ui/menu_table.py`, `ui/menu_table/index.html` | One new action (`pick`) goes back to Streamlit the same way |
| A component return value is **replayed on every rerun**; `regen_request` uses a nonce so one press is one request | `ui/menu_table.py::regen_request`, `app.py` | `pick_request` needs the same nonce guard |
| **Staples and client pins are the same set.** The solver stamps `CONST_SLOTS` (`white_rice`, `papad`, `pickle`, `chutney`) and `forced_items`/client constants and adds them to `pinned_cells`; the table already refuses to select them | `src/solver/menu_solver.py` (~lines 1395–1442), `index.html` (`c.pinned` has no `data-cell`) | D3 = "a cell in `pinned`". One marker in the real table, not two (the mockup's separate lock icon can collapse into the pin) |
| `/regenerate` accepts any cell in `replace_slots`; the pin rule is enforced **only in the UI** | `api/app.py::regenerate_cells` | Add a server-side guard (§5.3) |
| A pin naming a dish the pool filtered out is logged at INFO and "solved normally" | `menu_solver.py` (~line 722) | **Never** reuse that path for a user pick. It would answer 200 with a different dish than the one typed |
| Items carry a colour suffix: `veg_fried_rice(Y)`, from `_fmt_item_with_color(row, color_col)` | `menu_solver.py::_fmt_item_with_color` | A stamped pick must carry the same suffix |
| `recency_by_item` (days since last served) already reaches `MenuRegenerator` | `solve_inputs.py`, `/regenerate` | Source for the "served N days ago" chip |
| Plate-level checks exist (`run_checks`: colour variety, texture, spice arc, protein, ingredient echo, richness) | `src/explain/checks.py` | Reuse for the audit; compare before vs after |
| Rule hook `pre_filter_pool(pool, date, base_slot, day_type, filter_context)` removes items from a slot pool | `base_menu_rule.py` | Probe it with a one-row pool to learn which filter rules a pick would trip |
| No post-solve auditor evaluates `BaseMenuRule` constraints on a finished plan | grep of `src/`, `api/` | The Exceptions list cannot be complete in v1 (§6.3) |

---

## 3. Behaviour spec

### 3.1 Mode and clicks (supersedes the earlier "exactly one selected cell" design)
* The table header has a **table-level** `Auto | Pick` segmented control. Default **Auto**.
* **Auto:** clicking a pickable cell toggles selection, exactly as today; "Regenerate selected" is unchanged.
* **Pick:** clicking a pickable cell turns **that cell into a search input** (empty, focused). There is no separate panel and no "select one cell first" rule.
* Pickable = not pinned and not off. A click on a pinned cell, in either mode, shows the pinned message and does nothing else.
* Switching mode clears the selection and closes any open edit. Full detail, states, keyboard and strings: `pick_a_dish_docs/03_INTERACTION_SPEC.md`.

### 3.2 In-cell search
* The results panel is **in the page flow directly under the row** being edited (not floating, because the component lives in an iframe that sizes to its content).
* Heading: `<Slot> · <Day> <date> · replacing <dish>` and `Searching the <City> city list · <N> dishes`.
* Matching is client-side over the embedded list (§4.1), so there is **no Streamlit rerun per keystroke**.
* Matching: lower-case; split the query on whitespace; every token must be a substring of the dish's display name. Rank: whole-query prefix, then fewer warnings, then alphabetical. Up to 8 selectable results.
* Dishes already used that week (D5) are listed after the selectable results, disabled, with a lock chip "Already on `<Day>` · one per week", capped at 3; they are skipped by arrow keys and ignore click and Enter.
* Each result shows colour dot, display name, and a status chip (§3.3).
* Keyboard: Down/Up move through selectable results, Enter applies, Esc cancels.

### 3.3 Status chips (advisory, computed client-side from embedded data)
| Chip | Condition |
|---|---|
| Fits | none of the below |
| Served N days ago | `days_since < client item_cooldown_days` |
| Not in this client's pool | dish not in the client's narrowed pool for this base slot |

A warning chip never disables selection (D2). The only non-selectable state is the D5 lock (§3.2); it is not a warning and never appears in Exceptions. The authoritative check is the server audit on Apply (§5.2); the chips are a preview and may disagree with it. If they disagree, the server wins and the panel shows the server's list.

### 3.4 Apply
* Apply on **Enter** (highlighted result) or **click**. There is no confirmation footer: the chip already shows the warning, and Undo exists.
* The cell shows a **"chosen by you"** marker (pencil), amber when it has warnings. A banner/status line says what was applied; `Undo last pick` restores the previous plan from a session snapshot.

### 3.5 Exceptions panel (below the table)
* Collapsed by default when there are none; shows a count badge. Expanded entry per picked dish: dish, slot, date, "Replaced `<auto dish>`", one row per violated rule (name + detail), an optional **Reason** text field, `Undo this pick`.
* Say what was checked, e.g. "Checked: item cooldown, week repeat, client pool, theme/filter rules, plate checks." Do not imply every rule was evaluated (§6.3).

### 3.6 Locked cells
* A pinned cell has no `data-cell` (cannot be selected, so cannot be picked or regenerated). Tooltip: "Pinned by a client rule. Search and Regenerate can't change it."

### 3.7 Interactions with Auto
* A picked cell is a normal cell afterwards: it can be selected and auto-regenerated (that replaces the pick). Regenerating **other** cells locks the pick in place, because it is in `base_plan` (existing behaviour).
* After a pick, add the picked dish to the session `regen_seen` list for that cell so a later Auto does not flip back to it.

### 3.8 Out of scope for v1 (deliberate)
* Picking a dish **and** auto-regenerating the rest of the day around it in one action.
* Persisting exceptions or reasons into saved history (§6.4).
* Multiple picks in one Apply (the API accepts a map, the UI sends one).

---

## 4. Architecture

```
Streamlit page (app.py)
  ├─ builds, once per plan load (cached), per pickable slot:
  │     city dish list  { n: item_base, d: display, p: in_client_pool 0|1,
  │                       a: days_since_last|null, t: tags }
  └─ passes it to the component as an arg
Component (index.html)
  ├─ Auto | Pick toggle, search, chips        (all client-side, no rerun)
  └─ on Apply: setValue({action:"pick", cell, item, nonce})
Streamlit: pick_request(...)  → _apply_pick(...)
  └─ POST /api/v1/pick           (no CP-SAT solve, so no solver_gate)
        ├─ guard: cell pinned/staple/off → 400
        ├─ validate: item is a <slot> dish in the city list → else 400
        ├─ stamp item (+ colour suffix) into base_plan cell
        ├─ audit → exceptions[]
        └─ return solution (formatted), manual_cells, exceptions
  └─ update session block: plan, solution, manual, exceptions, undo snapshot
```

A pick **is not a solve**: every other cell is unchanged and was already valid. That makes it fast and keeps it out of the solver queue (`max_running 2`).

### 4.1 Embedded dish list
* Build from the **full city dataframe** (`ontology_repository.menu_data(city)`), mapped to base slots with the same logic `PoolBuilder` uses. **Do not** use `inputs.pools`: those are the client-narrowed pools (D4). **[unverified]** Confirm which of `inputs.pools` / `PoolBuilder` output is client-narrowed, and note city-wide policy cities (note 15) where they are identical.
* `p` = membership in the client's narrowed pool for that base slot. `a` = `inputs.recency_by_item` (None = not recently served).
* Size: Bangalore `veg_gravy` is 1,050 rows. Embedding every pickable slot is roughly a quarter of a megabyte, **[unverified]**, and Streamlit resends component args on every rerun. Cache with `st.cache_data` keyed by (client, city, dates). **Gate:** if measured rerun time rises noticeably, switch to the component fetching `GET /api/v1/pick-candidates` directly (CORS is already enabled via `flask_cors`).
* Send only for the plan's pickable base slots, and strip colour suffixes.

---

## 5. API

### 5.1 `POST /api/v1/pick` (new)

Request:
```json
{
  "client_name": "Zscaler", "counter_index": 0, "meal": "lunch",
  "start_date": "2026-11-02", "num_days": 5,
  "base_plan": { "2026-11-03": { "veg_gravy": "kadai_paneer(R)", "...": "..." } },
  "picks": { "2026-11-03": { "veg_gravy": "paneer_lababdar" } }
}
```
Response (200):
```json
{
  "success": true,
  "solution": { "...": "same shape as /regenerate, items carry is_manual" },
  "manual_cells": { "2026-11-03": ["veg_gravy"] },
  "exceptions": [{
    "date": "2026-11-03", "slot_id": "veg_gravy",
    "item": "paneer_lababdar", "replaced": "kadai_paneer",
    "violations": [
      {"code": "cooldown", "rule": "item_cooldown", "severity": "warning",
       "message": "Served 6 days ago (Wed 28 Oct). This client's window is 21 days."}
    ]
  }],
  "checked": ["cooldown", "client_pool", "pre_filter_rules", "plate_checks"],
  "not_checked": ["selector_frequency caps", "slot_composition", "colour constraints"]
}
```
Errors (400, never a silent fallback): unknown client; unknown or malformed date; **pinned/staple/const/off cell**; item not a `<slot>` dish in the city list; empty `picks`; **`week_repeat`** (D5): the dish is already used elsewhere in the same week, with `{"code":"week_repeat","on":"2026-11-02"}` in the body.
Rate limit: same class as `/diagnose` (cheap).

### 5.2 Server steps (new module `src/solver/picker.py`)
1. Resolve inputs the way `regenerate_cells` does (`_require_known_client`, `_resolve_counter`, `_prepare_solver_inputs`).
2. **Guard (D3):** compute the pinned set for the horizon **without solving** (§5.3). Reject any pick on a pinned cell.
3. **Validate category (D4):** `item_base` must be in the city list for that cell's base slot.
3b. **Enforce D5:** reject if the dish is in any other cell of the same week, in the plan **or in saved history** (see §6.5 for the week definition). `REPEATABLE_SLOTS` (curd, curd rice) and pinned staples are exempt. The UI lock is a convenience; this check is the rule.
4. **Stamp:** `base_plan[date][slot_id] = _fmt_item_with_color(row, cfg.color_col)`. Everything else stays byte-identical.
5. **Audit** (§6) the cell, comparing before and after; report only what the pick changed.
6. Format with `SolutionFormatter`, passing `pinned_cells` (recomputed) and the new `manual_cells`; add `is_manual` per item beside `is_pinned`, and a `manual_slots_from_solution` helper on the UI side using the existing `flagged_slots_from_solution`.

### 5.3 Pinned set without a solve
The pinned set is built **inside** `MenuSolver.solve` (stamping block, ~lines 1395–1442). Extract that block into a small pure function (dates, `cfg.const_slots`, `skip_cells`, `forced_items`, client constants → set of `(date, slot)`) and call it from both places.
**Gate:** a test proves `/plan` output is byte-identical before and after the extraction.

### 5.4 `/regenerate` guard
Reject (400) any `replace_slots` cell in the pinned set. This is server-side enforcement of D3 for regenerate; today only the UI prevents it.

### 5.5 `GET /api/v1/pick-candidates` (only if §4.1's size gate trips)
`?client_name=&city=&slots=veg_gravy,veg_dry&counter_index=` → `{slot: [{n,d,p,a,t}, ...]}`.

---

## 6. Audit (turns a pick into "Exceptions")

### 6.1 What v1 can detect
| Code | How |
|---|---|
| `cooldown` | `banned_by_date[date]` contains the item; message uses `recency_by_item` |
| `client_pool` | item not in `inputs.pools[base_slot]` |
| `ricebread_gap` | bread slot and `ricebread_ban_day[date]` |
| `<rule name>` (pre-filter rules) | for each rule, call `rule.pre_filter_pool(one_row_df, date, base_slot, day_type, filter_ctx)`; if the row is removed, the rule is violated. Build `filter_ctx` the way `_build_day_base_pool_cache` does (**[unverified]**: copy its keys: `cfg`, `banned_by_date`, `ricebread_ban_day`, `pools`, `extra_repeatable`, `extra_cooldown_exempt`) |
| plate checks | run `run_checks` on the day before and after; report a check that passed before and fails after |

### 6.1b The week rule is a block, not an exception
`week_repeat` is no longer an audit finding. It is enforced in §5.2 step 3b, so it can never appear in `violations`.
Note the interaction with cooldown: the 21-day cooldown stays an overridable warning, but a dish served earlier **this week** is also inside the cooldown window. The D5 check must therefore run first, so a same-week repeat is blocked rather than shown as a mere "served N days ago" warning.

### 6.2 Severity
All are `warning` in v1 (D2: override is allowed). Reserve `error` for nothing yet; do not invent a block.

### 6.5 Defining "a week" (needs the owner's answer, see §11)
* **Plan-level:** all cells in the plan on screen (the solver's `unique_items` already works this way across the horizon).
* **History-level:** dishes already served earlier in the same week by a previously saved plan. Read it from the same history the cooldown uses (`banned_by_date`/`recency_by_item`); it must include other counters and services where cooldown spans them.
* Default proposed: **ISO calendar week (Mon–Sun)**. The alternative, a rolling 7 days, blocks a Monday dish on the next Sunday. Both agree for a standard Mon–Fri plan.

### 6.3 What v1 cannot detect (say so in the UI)
Constraint-type rules that only exist inside the CP-SAT model: weekly frequency caps (e.g. `nonveg_biryani_once_per_week`), `slot_composition` (e.g. `veg_dry_north_south_pair`), colour constraints, etc. The response lists them under `not_checked`, and the panel text must reflect it. Silently omitting them would make the Exceptions list look complete when it is not.

### 6.4 v2 (separate work order, after the owner has used v1)
* **Per-rule feasibility probe:** build the model with all cells locked to the final plan, add one rule's constraints at a time, and attribute any INFEASIBLE to that rule. All cells fixed means each probe should be cheap. **[unverified]** Measure the cost across ~70 rules.
* **Persist exceptions and reasons** with the saved plan. History is one JSON row per day `{slot: item_base}`; adding a key changes a schema that cooldown readers explode. The mockup copy "saved with the plan" is **not true in v1**: either build persistence first or change the copy to "Picked by you".
* Pick plus auto-regenerate-around-it (needs the pick injected into the cell pool, since the pre-filters would otherwise drop it).

---

## 7. UI work

### 7.1 `ui/menu_table/index.html`
* State: `mode` (`auto`|`pick`), `pickCell`, `query`, `highlighted`.
* `data-act="mode"` segmented control (real `<button aria-pressed>`), table-level, always enabled.
* In-cell input (a combobox) and the in-flow results panel under the edited row, per `03_INTERACTION_SPEC.md`. **While Editing, typing updates only the results container** and re-measures height; the table is rebuilt only on Apply, Cancel, mode switch or cell click, because rebuilding on a keystroke would drop the input's focus.
* Cell flags: `c.manual`, `c.violations` (count); pencil icon, amber background when violations > 0. At most one trailing marker, in this order: tick (selected), warning, pencil (manual), redo (modified).
* On Apply: `setValue({action: "pick", cell, item, nonce: Date.now()})`, then clear selection.
* Exceptions panel and banner per artboards 3 and 4 (the panel can live in the component or in Streamlit below it; **prefer the component**, so expand/collapse is local and does not rerun).

### 7.2 `ui/menu_table.py`
* `day_cells(...)`: new `manual` set (keys `slot|iso`), same shape as `pinned`/`modified`.
* `menu_table(...)`: new args `dishes` (the embedded list), `exceptions`, `client_cooldown_days`.
* `pick_request(picked, last_nonce)`: mirror of `regen_request`, returns `{"nonce", "cell": (slot_id, iso), "item"}`, replay-safe.

### 7.3 `app.py`
* `_apply_pick(api, block_index, counter_index, slot_id, iso, item)`: call `api.pick(...)`, update the block (plan, solution, nonveg, pinned, **manual**, **exceptions**), push an undo snapshot, add to `regen_seen`, append to `changes_log` with `kind: "pick"`, `st.rerun()`. On error show `st.error` and leave the plan unchanged.
* Handle it next to `regen_request` (the replay-guard block, ~line 1499).

### 7.4 `ui/api_client.py`
* `pick(...)` mirroring `regenerate(...)`, same error mapping.

### 7.5 Pulse parity
Keep `/api/v1/pick` and the dish-list shape documented in `docs/api.md`. That contract is what the Pulse migration reuses; the component is the throwaway part.

---

## 8. Delivery phases

**Phase 0 — Baseline.** `pip install -r requirements.txt -r requirements-dev.txt` (needs `flask_cors`). Record the `pytest tests -q` baseline. **Gate:** green baseline.

**Phase 1 — Pinned set + guard (no new feature yet).** Extract the pure pinned-cells function (§5.3); add the `/regenerate` pinned guard (§5.4). **Gate:** `/plan` output byte-identical; guard test passes; the UI still cannot select pinned cells.

**Phase 2 — `/api/v1/pick` (stamp + category validation, empty audit).** **Gate:** a picked dish appears and every other cell is unchanged; pinned or wrong-category picks return 400.

**Phase 3 — Audit v1 (§6.1).** **Gate:** each detector has a test (cooldown, week repeat, client pool, a pre-filter rule, plate-check regression); `not_checked` is always returned.

**Phase 4 — Component and Streamlit wiring.** Embedded list (measure rerun cost at the §4.1 gate), toggle, search, chips, Apply, banner, Undo, Exceptions panel. **Gate:** end-to-end through `fake_supabase`, as `tests/rules/test_theme_slot_pools.py::_solve` does it.

**Phase 5 — Docs.** `docs/api.md`, `docs/repo_map.md` (add a design note), `version_control/` version doc per its README.

---

## 9. Tests

**API (`tests/api/test_pick.py`)**
* Pick lands in the cell with the colour suffix; all other cells byte-identical.
* Pick on a pinned cell, a staple slot, and an off day → 400.
* Pick of a dish not in the city list for that slot → 400.
* Pick that is a cooldown violation → 200 with `violations[0].code == "cooldown"`.
* Pick of a dish already elsewhere in the plan's week → **400 `week_repeat`**, plan unchanged.
* Pick of a dish served earlier this week in saved history → 400 `week_repeat`.
* Pick of a dish served last week (inside the 21-day cooldown) → 200 with a `cooldown` violation, not a block.
* Curd and curd rice (repeatable slots) are exempt from the week rule.
* Pick outside the client pool → `client_pool`.
* Clean pick → empty `violations`.
* `not_checked` present in every response.
* `/regenerate` with a pinned cell → 400; without one, unchanged.
* `/plan` byte-identical after the pinned-set extraction.

**UI pure functions (`tests/ui/`)**
* `pick_request` replays safely (same nonce returns None) and splits `slot|iso` on `|`.
* `day_cells` marks `manual`; a pinned cell has no selectable flag.

**Search matching:** exact beats prefix beats substring; underscores handled; fits before warnings; week-locked dishes are listed last and are not selectable by click, Enter or arrow keys.

---

## 10. Mockup vs what this order builds

| Mockup | What to build |
|---|---|
| Separate "Fixed" lock for staples and pin for client pins | One **pinned** marker for both (same set in the code) |
| "Picked by you · saved with the plan" | Change to "Picked by you" in v1 (no persistence), or build persistence first |
| Exceptions list reads as complete | Add the "Checked / not checked" line (§6.3) |
| Chips on every result | Advisory, from embedded data; the server audit is authoritative |
| "Already on Thu" as a warning that can be applied | Now a **locked** result (D5), enforced server-side as a 400 |
| Sample dishes, dates, "31 matches" | Illustrative only. "1,050 veg gravies" is the real Bangalore `veg_gravy` row count |

---

## 11. Open decisions for the owner

1. **Persist exceptions?** If yes, it needs a history schema change (separate order). If no, fix the mockup copy.
2. **Embed or fetch the dish list?** Default: embed and cache; switch only if the rerun gate trips.
3. **v2 audit coverage:** how important is it that frequency caps and slot composition appear in Exceptions?
4. **Define "a week" (D5).** ISO calendar week (default) or rolling 7 days? Should saved history from other counters and services count?
5. **Who may override?** The mockup assumes any planner. Say so if it should be restricted.

---

## 12. Verified vs unverified

**Verified (read from the repo):** regenerate's lock-and-solve flow; `locked`/`forbidden` handling; the pinned set (staples + forced items + client constants) and where it is built; `/regenerate` accepts any cell and the UI alone prevents pinned selection; the nonce replay pattern; `recency_by_item` reaching the regenerator; `run_checks`; `pre_filter_pool`'s signature; no existing post-solve rule auditor; Bangalore `veg_gravy` = 1,050 rows.

**Unverified:** the client-narrowed vs full-city split of `PoolBuilder` output; the exact `filter_ctx` keys the probe needs; embedded-list payload size and rerun cost; that stamping reproduces exactly what the solver would write for the colour suffix on every slot; per-rule probe cost for v2; Pulse's component model. Nothing here has been implemented or run.
