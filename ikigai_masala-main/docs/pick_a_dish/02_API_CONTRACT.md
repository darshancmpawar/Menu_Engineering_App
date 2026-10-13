# 02 · API contract — Pick a dish

Status: **Draft** · written 13 Oct 2026 · target: `docs/api.md`, section for `/api/v1/pick`

Existing conventions (verified from `api/app.py`): every endpoint is under `/api/v1`, open (no auth header), JSON in and out, errors shaped `{"success": false, "error": "<message>"}`. This contract keeps that shape and **adds** a stable `code` (and optional `details`) so a client can branch without reading prose.

---

## 1. Endpoints in this feature

| Method | Path | New or changed | Purpose | Gate / limit |
|---|---|---|---|---|
| POST | `/api/v1/pick` | **New** | Put chosen dishes into cells, audit them, return the updated plan | `@rate_limit("diagnose")` class (cheap). **No** `@solver_gate`: it does not solve |
| POST | `/api/v1/regenerate` | **Changed** | Reject any cell that is pinned | Existing gate and limit |
| GET | `/api/v1/pick-candidates` | **New, conditional** | Per-slot city dish list, only if the embed gate in doc 06 trips | `@rate_limit("diagnose")` |

---

## 2. `POST /api/v1/pick`

### 2.1 Request

```json
{
  "client_name": "Zscaler",
  "counter_index": 0,
  "meal": "lunch",
  "start_date": "2026-11-02",
  "num_days": 5,
  "base_plan": {
    "2026-11-03": { "veg_gravy": "kadai_paneer(R)", "rice": "veg_biryani(Y)" }
  },
  "picks": {
    "2026-11-03": { "veg_gravy": "paneer_lababdar" }
  }
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `client_name` | string | yes | Must be a known client (same check as `/regenerate`: `_require_known_client`) |
| `counter_index` | int | no, default 0 | Resolved with `_resolve_counter` |
| `meal` | string | no | Which service's counters `counter_index` indexes, as in `/regenerate` |
| `start_date` | ISO date | yes | First planned day |
| `num_days` | int | no, default 5 | Horizon, as in `/plan` |
| `base_plan` | `{iso: {slot_id: item}}` | yes | The plan on screen. Items may carry the colour suffix. Same shape `/regenerate` takes |
| `picks` | `{iso: {slot_id: item_base}}` | yes, non-empty | `item_base` is the **ontology** `item` spelling (lower-case, underscores), never a display name. A colour suffix is ignored if sent |

The UI sends one pick per call in v1. The server accepts several and applies them **atomically**: either every pick is valid or none is applied.

### 2.2 Validation order (first failure wins; later steps never run)

| # | Check | Failure code | HTTP |
|---|---|---|---|
| 1 | Body is JSON and has `base_plan` and non-empty `picks` | `bad_request` | 400 |
| 2 | Client and counter resolve | `unknown_client` / `bad_counter` | 400 |
| 3 | Every date parses and lies in the planned horizon | `bad_date` | 400 |
| 4 | Every `slot_id` exists in `base_plan` for that date | `unknown_cell` | 400 |
| 5 | The cell is **not pinned** (staple, `forced_items` pin, client constant) and not an off day | `pinned_cell` | 400 |
| 6 | `item_base` is a dish of that cell's base slot in the **city list** (D4) | `not_a_slot_dish` | 400 |
| 7 | **D5**: the dish is not used elsewhere in the same week, in the plan, in other picks of this request, or in saved history (doc 04 §3) | `week_repeat` | 400 |
| 8 | Stamp and audit (doc 04 §4–§6) | none: always 200 with warnings | 200 |

Picking the dish that is already in the cell is not an error: the response has `"changed": false`, an unchanged plan and no exception.

### 2.3 Success response (200)

```json
{
  "success": true,
  "changed": true,
  "solution": {
    "2026-11-03": {
      "theme": "Biryani", "day_type": "biryani",
      "items": {
        "veg_gravy": {
          "display_name": "Veg Gravy", "item": "paneer_lababdar(R)",
          "item_base": "paneer_lababdar", "is_nonveg": false,
          "is_pinned": false, "is_manual": true
        }
      }
    }
  },
  "manual_cells": { "2026-11-03": ["veg_gravy"] },
  "exceptions": [
    {
      "date": "2026-11-03",
      "slot_id": "veg_gravy",
      "item": "paneer_lababdar",
      "replaced": "kadai_paneer",
      "violations": [
        {
          "code": "cooldown",
          "rule": "item_cooldown",
          "severity": "warning",
          "message": "Served 6 days ago (Wed 28 Oct). This client's window is 21 days.",
          "details": { "last_served": "2026-10-28", "days_ago": 6, "window_days": 21 }
        }
      ]
    }
  ],
  "checked": ["cooldown", "client_pool", "ricebread_gap", "pre_filter_rules", "plate_checks"],
  "not_checked": ["selector_frequency caps", "slot_composition", "colour constraints"]
}
```

Rules for the body:

* `solution` has the **same shape** `/regenerate` returns (`SolutionFormatter.to_dict()`), with one new per-item flag, `is_manual`. `is_pinned` is recomputed (doc 04 §2.3).
* `manual_cells` is every cell **picked in this request**. The client unions it into its own session set; the server is stateless.
* `exceptions` contains only picks that have at least one violation. A clean pick has no entry.
* `checked` and `not_checked` are **always present**, even when empty, so a client can never mistake an incomplete audit for a complete one (doc 04 §6).
* `severity` is `"warning"` for every violation in v1 (D2). The field exists so a later version can add a level without a contract change.
* `violations[].code` is from the closed set in §5.

### 2.4 Error response

```json
{
  "success": false,
  "code": "week_repeat",
  "error": "Palak paneer is already on Thu 5 Nov. A dish can't repeat in a week.",
  "details": { "item": "palak_paneer", "on": "2026-11-05", "week": "2026-W45", "source": "plan" }
}
```

* `error` is a sentence a planner could read (the repo's content rules: what happened, then what to do; no raw exception text).
* `details` varies by code (§5).
* `source` in `week_repeat` is `"plan"`, `"history"` or `"pick"`.
* On any 400 **nothing is applied**. The plan the client holds is unchanged.
* Unexpected failures return 500 through the existing `_internal_error_response(500)`; a data-loading failure keeps its current 500 mapping.

---

## 3. `POST /api/v1/regenerate` (guard only)

The body and success response are unchanged. New behaviour:

* If any cell in `replace_slots` is pinned, respond 400 `pinned_cell` with `details: {"cells": [{"date": "...", "slot_id": "..."}]}` and **solve nothing**.
* Today only the table component prevents selecting a pinned cell; the server accepts any cell. This closes that gap for stale tabs and other clients.
* A request with no pinned cell behaves exactly as before. A test proves `/plan` and `/regenerate` output is unchanged (doc 06, gate G1).

---

## 4. `GET /api/v1/pick-candidates` (only if doc 06 gate G5 trips)

Query: `client_name`, `city`, `counter_index`, `meal`, `slots` (comma-separated base slots).

```json
{
  "success": true,
  "city": "Bangalore",
  "slots": {
    "veg_gravy": [
      { "n": "paneer_lababdar", "d": "Paneer Lababdar", "p": 1, "a": 6, "t": ["north", "veg"] }
    ]
  }
}
```

| Key | Meaning |
|---|---|
| `n` | ontology `item` (what `picks` sends back) |
| `d` | display name (`format_item_for_ui`) |
| `p` | 1 if the dish is in the client's narrowed pool for that base slot, else 0 |
| `a` | days since last served from `recency_by_item`, or `null` if not in the window |
| `t` | tags: cuisine or region, veg or non-veg, where known |

The list comes from the **full city dataframe** mapped to base slots (D4), never from the client-narrowed pools. In the default design the same structure is passed to the component as an argument instead of fetched.

---

## 5. Closed code sets

### 5.1 Error codes

| Code | HTTP | `details` |
|---|---|---|
| `bad_request` | 400 | `{ "field": "picks" }` |
| `unknown_client` | 400 | `{}` |
| `bad_counter` | 400 | `{ "counter_index": 3 }` |
| `bad_date` | 400 | `{ "date": "2026-11-31" }` |
| `unknown_cell` | 400 | `{ "date": "...", "slot_id": "..." }` |
| `pinned_cell` | 400 | `{ "date": "...", "slot_id": "..." }` or a `cells` list (regenerate) |
| `not_a_slot_dish` | 400 | `{ "item": "...", "slot_id": "...", "city": "Bangalore" }` |
| `week_repeat` | 400 | `{ "item", "on", "week", "source" }` |
| `internal_error` | 500 | none |

### 5.2 Violation codes (always severity `warning`)

| Code | Rule label | Meaning |
|---|---|---|
| `cooldown` | `item_cooldown` | Served inside the client's cooldown window (21 days by default) |
| `client_pool` | `client_pool` | On the city list but not in this client's pool |
| `ricebread_gap` | `ricebread_gap` | Bread on a day the rice-bread gap rule bans it |
| `rule:<name>` | the rule's `name` | A `pre_filter_pool` rule would have removed this dish |
| `plate:<check>` | the check's name | A plate check that passed before the pick now fails |

`week_repeat` is **not** a violation code. It is an error (§5.1).

---

## 6. Behaviour guarantees

1. **No solve.** A pick never runs CP-SAT and never takes a solver slot.
2. **Everything else is byte-identical.** Cells not named in `picks` are returned exactly as received.
3. **Atomic.** All picks apply or none does.
4. **Stateless.** The server remembers nothing between calls; the client holds the plan, the manual set, the exceptions and the undo stack.
5. **Never a silent substitution.** The server never returns a dish other than the one requested. (The existing "pinned dish not eligible, solve the cell normally" path is not reused.)
6. **Honest audit.** `not_checked` is always returned; no field implies the audit is complete.
7. **Spelling.** The stamped item uses the ontology spelling and the same colour suffix the solver would write (`_fmt_item_with_color(row, cfg.color_col)`), so a later `/save` stores what cooldown readers expect (repo note 28).

---

## 7. Examples

### 7.1 Clean pick

Request `picks: {"2026-11-03": {"veg_gravy": "paneer_do_pyaza"}}` →

```json
{ "success": true, "changed": true, "solution": { "...": "..." },
  "manual_cells": { "2026-11-03": ["veg_gravy"] },
  "exceptions": [],
  "checked": ["cooldown", "client_pool", "ricebread_gap", "pre_filter_rules", "plate_checks"],
  "not_checked": ["selector_frequency caps", "slot_composition", "colour constraints"] }
```

### 7.2 Blocked: same week

```json
{ "success": false, "code": "week_repeat",
  "error": "Paneer butter masala is already on Mon 2 Nov. A dish can't repeat in a week.",
  "details": { "item": "paneer_butter_masala", "on": "2026-11-02", "week": "2026-W45", "source": "plan" } }
```

### 7.3 Blocked: pinned cell

```json
{ "success": false, "code": "pinned_cell",
  "error": "That cell is pinned by a client rule. Search and Regenerate can't change it.",
  "details": { "date": "2026-11-04", "slot_id": "dessert" } }
```

### 7.4 Overridden with two warnings

```json
{ "success": true, "changed": true, "exceptions": [{
    "date": "2026-11-05", "slot_id": "veg_dry", "item": "methi_aloo", "replaced": "beans_poriyal",
    "violations": [
      { "code": "client_pool", "rule": "client_pool", "severity": "warning",
        "message": "On the Bangalore city list, but not in Zscaler's dish pool." },
      { "code": "rule:theme_cuisine_filter", "rule": "theme_cuisine_filter", "severity": "warning",
        "message": "Thursday is a South day; this is a North dish." } ] }] }
```

---

## 8. Compatibility and Pulse

* No existing field changes meaning. `/regenerate` only gains a rejection for a cell it should never have accepted.
* The contract is stateless and UI-free so the Pulse migration can reuse it unchanged. Hand this document, plus doc 03's string table, to whoever builds the Pulse screen.
* Add the three rows from §1 to the endpoint table at the top of `docs/api.md` and the sections of §2–§5 below it. Add a row for `/api/v1/pick` to §3 of `docs/repo_map.md` (one line, per that file's editing rules).

## 9. Open items for this contract

* The exact shape of saved history for the week check (O2) and whether a pick may name a dish served earlier **today** by another counter. Resolve in Phase 2.
* Whether `bad_counter` needs its own code or reuses `bad_request`. Keep separate only if the UI needs to tell them apart.
