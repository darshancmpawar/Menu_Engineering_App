# 04 · Rules and audit spec — Pick a dish

Status: **Draft** · written 13 Oct 2026 · implements decisions D2, D3, D4, D5 (doc 01)

This document says exactly **what stops a pick, what only warns, and what is not checked**. The API shapes are in doc 02; the screen is in doc 03.

---

## 1. Principles

1. A pick is **not a solve**. Every other cell is already valid; the pick is stamped into one cell and then audited (decision D2).
2. There are exactly two kinds of outcome: a **block** (HTTP 400, nothing applied) and a **warning** (HTTP 200, listed in Exceptions). In v1 the blocks are: unknown cell, pinned cell, wrong category, and the one-dish-per-week rule.
3. Search can override every rule except D5 and D3.
4. A pick **never silently becomes a different dish**.
5. The audit is **honest about its coverage**: the response always lists what it did not check (§6).
6. Report only what the pick **changed**: a plate check that already failed before the pick is not blamed on it.

---

## 2. Guards (blocks other than the week rule)

### 2.1 Category (decision D4)
The dish must be a dish of the cell's **base slot** in the **city list**: the full city dataframe (`ontology_repository.menu_data(city)`) mapped to base slots with the same logic `PoolBuilder` uses. Not the client-narrowed pools. Failure: `not_a_slot_dish`.
`[unverified]` Which `PoolBuilder` output is client-narrowed; confirm before use. Cities that plan from the whole list (repo note 15) make the two identical.

### 2.2 Cell exists and is servable
The `(date, slot_id)` must be in `base_plan`, inside the planned horizon, and not an off day (a blank "Not served" column). Failure: `unknown_cell` or `bad_date`.

### 2.3 Pinned set (decision D3)
A cell is pinned when the solver did not choose it:

* `CONST_SLOTS` staples (`white_rice`, `papad`, `pickle`, `chutney`), unless a `slot_day_restriction` removes them for that day;
* `forced_items` (a client constant naming a real ontology dish, solved but restricted to one candidate);
* client constants stamped after the solve.

Today this set is built **inside** `MenuSolver.solve` (the stamping block near the end, ~lines 1395–1442) and read back as `solver.pinned_cells`. A pick makes no solve, so:

* **Extract** that block into a small pure function: dates, `cfg.const_slots`, `skip_cells`, `forced_items`, client constants → set of `(date, slot_id)`. Call it from both the solver and the picker.
* **Guard test:** `/plan` output is byte-identical before and after the extraction (doc 06, gate G1).
* The same function powers the `/regenerate` guard: any pinned cell in `replace_slots` returns `pinned_cell`.

---

## 3. The week rule (decision D5)

> The same dish cannot appear twice in a week. A pick that would repeat it is **blocked**.

### 3.1 Definition (answers to O1, O2, O7, O8 pending; defaults shown)

| Aspect | Default | Notes |
|---|---|---|
| "Same dish" | exact normalised `item_base` (`_norm_str` of the item with the colour suffix stripped) | O8: confirm whether dish-fold variants need handling |
| "A week" | ISO calendar week, `date.isocalendar()[:2]` | O1: rolling 7 days is the alternative |
| Where a repeat is searched | (a) every **other** cell in `base_plan` in the same week, (b) the other picks in the same request, (c) saved history in the same week (§3.3) | O2 |
| Exempt | slots in `REPEATABLE_SLOTS` (`curd`, `curd_rice`), and rule-declared staples (the repeatable-items declarations the solver passes as `extra_repeatable`) | O7 |
| The target cell itself | never counts against itself | Replacing a dish with itself is a no-op, not a repeat |

Pinned cells **do count** as uses of a dish. The solver treats a pinned dish as visible to every other rule, "so it cannot be duplicated elsewhere".

### 3.2 Algorithm

```
week(d)  = d.isocalendar()[:2]
used     = {}                                   # item_base -> [(date, source)]
for each cell (d, slot) in base_plan with week(d) == week(target):
    if (d, slot) is the target cell:            continue
    if base_slot(slot) in REPEATABLE_SLOTS:     continue
    if item in rule-declared staples:           continue
    used[item].append((d, "plan"))
for each other pick (d2, slot2, item2) in this request, already accepted:
    used[item2].append((d2, "pick"))
for each saved-history row in the same week whose date is NOT in the plan's dates:
    used[item].append((date, "history"))
if candidate in used:  BLOCK  week_repeat  with the earliest date and its source
```

### 3.3 Saved history, and the trap in it

* Read it from the **same history source the cooldown uses** (`HistoryManager`; `banned_by_date` and `recency_by_item` come from it). Do not invent a second reader.
* **Exclude history rows whose dates fall inside the current plan's dates.** The plan on screen may already have been saved; saving overwrites per (client, dates). Counting those rows would make every dish block itself and its siblings.
* Include history dates in the same week that are **outside** the plan (for example Mon and Tue before a plan that starts on Wednesday).
* The 21-day cooldown query has **no meal filter on purpose**: lunch and dinner share a window (repo note 39). Do not add one. Whether the week rule counts the other service is O2; the default follows the cooldown.
* `[unverified]` How multi-counter plans are stored (`{counter: {slot: item}}` nested JSON) and whether other counters should count. Resolve in Phase 2 before writing the check.

### 3.4 Order

D5 runs **before** the cooldown audit. A dish served earlier this week is also inside the 21-day cooldown, so without that order it would appear as a mere "served N days ago" warning and be allowed.

### 3.5 Messages

| Source | `error` text |
|---|---|
| `plan` | `<Dish> is already on <Day> <date>. A dish can't repeat in a week.` |
| `pick` | `You picked <Dish> twice in one request. A dish can't repeat in a week.` |
| `history` | `<Dish> was served on <Day> <date> in a saved plan. A dish can't repeat in a week.` |

### 3.6 The client lock is a convenience
The component locks results using the plan on screen. The server check is the rule. If they disagree (history), the server wins and the component locks that dish for the rest of the edit.

---

## 4. Stamping

1. Look up the dish's row in the city dataframe.
2. Write `base_plan[date][slot_id] = _fmt_item_with_color(row, cfg.color_col)`, the helper the solver uses (`src/solver/menu_solver.py`), so the item carries the same colour suffix a solved dish would.
3. Leave every other cell byte-identical.
4. The stored spelling is the ontology's, so a later `/save` writes what the cooldown and freshness readers expect (repo note 28: a display name stored as `dal tadka` matches no pool row and never ages).
5. Format the result through `SolutionFormatter`, passing the **recomputed** pinned cells and the new manual cells; add `is_manual` per item beside `is_pinned`.
`[unverified]` That stamping reproduces the colour suffix on every slot. Test one dish per base slot (doc 06).

---

## 5. Audit: what produces a warning

Run on the picked cell, in this order. All findings are `severity: "warning"` (D2). Only findings **caused by the pick** are reported.

| # | Code | Detector | Data source | Message |
|---|---|---|---|---|
| 1 | `cooldown` | The item is in `banned_by_date[date]`, unless the item is cooldown-exempt (`extra_cooldown_exempt`, `REPEATABLE_SLOTS`) | `inputs.banned`, `inputs.recency_by_item` | `Served <N> days ago (<Day> <date>). This client's window is <W> days.` |
| 2 | `client_pool` | The item is **not** in `inputs.pools[base_slot]['item']` | `inputs.pools` (client-narrowed) | `On the <City> city list, but not in <Client>'s dish pool.` |
| 3 | `ricebread_gap` | Base slot is `bread` and `ricebread_ban_day[date]` is true | `inputs.rb_ban` | `Bread isn't allowed on <Day>: the rice-bread gap rule.` |
| 4 | `rule:<name>` | Call each loaded rule's `pre_filter_pool(one_row_df, date, base_slot, day_type, filter_ctx)`. If the row is **removed**, that rule is violated | `inputs.rules` | `<rule.get_description()>`, or a short phrase from the rule's config comment if present |
| 5 | `plate:<check>` | Run `run_checks` on the day before and after. Report a check that **passed before and fails after** | `src/explain/checks.py` | `<check name>: <detail>` |

### 5.1 The pre-filter probe (row 4)

* `filter_ctx` has the keys the solver builds in `_build_day_base_pool_cache`: `cfg`, `banned_by_date`, `ricebread_ban_day`, `pools`, `extra_repeatable`, `extra_cooldown_exempt`. `[unverified]` copy the exact construction; read that function first.
* `day_type` is `_weekday_type_cfg(date, theme_map)`.
* A rule that **raises** is skipped and named in `not_checked` (`rule:<name> (errored)`), never fatal. Losing a constraint silently is worse than naming it.
* A rule that changes the row without removing it is ignored.
* Rows 1–3 may overlap with rule probes (some cooldown logic is a rule). Report each violated thing once, preferring the specific code.

### 5.2 Plate checks (row 5)

* Build the day's dish dicts the way `/explain` does (`build_dishes` / `attrs_from_dataframe` in `src/explain/evidence.py`). `[unverified]` exact signatures; read first.
* Compare before and after for the picked day only. A check already failing before the pick is **not** reported.

### 5.3 What the user sees
Each violation has a `code`, the rule's name, one sentence of detail, and optional `details`. The Exceptions entry shows the detail text (doc 03 §7).

---

## 6. Coverage: what is and is not checked

The response always carries both lists (even when empty).

| `checked` entry | Meaning |
|---|---|
| `cooldown` | row 1 |
| `client_pool` | row 2 |
| `ricebread_gap` | row 3 |
| `pre_filter_rules` | row 4, every loaded rule that has a `pre_filter_pool` |
| `plate_checks` | row 5 |

| `not_checked` entry | Why |
|---|---|
| `selector_frequency caps` | Weekly and horizon caps (for example `nonveg_biryani_once_per_week`) exist only as CP-SAT constraints |
| `slot_composition` | Composition rules (for example `veg_dry_north_south_pair`) are model constraints |
| `colour constraints` | Colour variety is a model constraint |
| `rule:<name> (errored)` | A pre-filter probe failed |

The UI prints this as one line under the Exceptions list (doc 03 §7). A pick that breaks a weekly cap will **not** appear in Exceptions in v1, and the planner is told so on screen.

---

## 7. Order of evaluation

1. Request shape, client, counter, dates (doc 02 §2.2 steps 1–3)
2. Cell exists and is servable (§2.2)
3. **Pinned guard** (§2.3)
4. **Category guard** (§2.1)
5. **Week rule** (§3), the last block
6. Stamp (§4)
7. Audit rows 1–5 (§5)
8. Format and return (doc 02 §2.3)

Any block in steps 1–5 returns 400 with nothing applied. Steps 6–8 never block.

---

## 8. v2: closing the coverage gap (separate order, not v1)

Goal: have Exceptions list weekly caps, composition and colour constraints too.

1. **Per-rule feasibility probe.** Build the CP-SAT model with every cell locked to the final plan (including the pick). Add one rule's `apply()` at a time. If a rule makes the model INFEASIBLE, that rule is violated by the pick (it was satisfied before, because the pre-pick plan was a valid solve).
2. All cells are fixed, so each probe should be cheap. `[unverified]` Measure the cost over the roughly 70 rules; set a budget before enabling.
3. The rule instance must not be shared between solves (repo note 27): use fresh rule instances (`load_for_client` already returns them).
4. Move entries from `not_checked` to `checked` as each rule family is covered, and test each.

---

## 9. Performance budgets `[proposal]`

| Operation | Budget | Measured by |
|---|---|---|
| `/pick` server time, one pick, v1 audit | under 2 s on a typical counter | gate G4 in doc 06 |
| Embedded dish list payload per plan | under 300 KB; rerun time not noticeably longer | gate G5 |
| Search keystroke to results | no network, no rerun | manual QA |

Every number is a starting point for the owner to change after measurement.

---

## 10. Detector-to-test map

| Detector | Test (in doc 06) |
|---|---|
| Pinned guard and extraction | G1, A-05, A-06 |
| Category guard | A-07 |
| Week rule: plan, pick, history, exemptions, cooldown ordering, self-block trap | A-08 to A-14 |
| Cooldown warning | A-15 |
| Client pool warning | A-16 |
| Rice-bread gap | A-17 |
| Pre-filter probe (one rule that removes a row, one that errors) | A-18, A-19 |
| Plate-check regression | A-20 |
| Colour suffix on every base slot | A-21 |
| Coverage lists always present | A-22 |
