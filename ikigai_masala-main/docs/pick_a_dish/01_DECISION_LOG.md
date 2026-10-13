# 01 · Decision log — Pick a dish

Status: **Draft for owner review** · written 13 Oct 2026

Purpose: one place where every decision about this feature is recorded, with who made it, so no one has to reconstruct it from a chat. Claude Code must treat section 1 as fixed and section 2 as "ask, do not guess".

---

## 1. Locked decisions

| ID | Decision | Decided by | Date | Consequence for the build |
|---|---|---|---|---|
| D1 | The regenerate control gets a mode: **Auto** (today's regenerate) or **Pick** (search by name, scoped to the cell's category). In Pick, the cell itself becomes the search input; there is no separate panel | Owner (Darshan) | 13 Oct 2026 | Table-level toggle in the header; click behaviour depends on mode (spec 03 §3) |
| D2 | A picked dish **may override and violate rules**. Violations are shown as warnings in an expandable **Exceptions** section | Owner | 13 Oct 2026 | Pick is not a solve; stamp then audit (spec 04) |
| D3 | **Staple and pinned cells cannot be changed** by search or regenerate | Owner | 13 Oct 2026 | Server guard on `/pick` and on `/regenerate`; both are the same set in the code (a cell the solver did not choose) |
| D4 | Search scope is the **city item list**, not the client's pool | Owner | 13 Oct 2026 | "Not in this client's pool" is a warning, never a filter |
| D5 | **Hard rule: the same dish cannot appear twice in a week.** A pick that would repeat is blocked, not warned. It is the one rule search cannot override | Owner | 13 Oct 2026 | 400 `week_repeat` on the server; locked rows in search; runs before cooldown |
| D6 | **"A week" for D5 is the ISO calendar week (Mon-Sun).** Not a rolling 7 days | Owner (Darshan) | 13 Oct 2026 | The D5 check buckets by `date.isocalendar()[1]`, the same bucketing the cross-week cadence rules use. For a standard Mon-Fri plan the two readings agree; this one does not block a Sunday dish on the next Monday |
| D7 | **Saved history counts for D5: same client, all counters, all services** | Owner (Darshan) | 13 Oct 2026 | The check reads the same history the item cooldown reads (which already spans services and drops the `meal` column, note 39), restricted to the pick's ISO week. Without it a same-week repeat slips in from a previous save with nothing on screen to show it |
| D8 | **Exceptions and reasons are NOT persisted in v1.** Session only | Owner (Darshan) | 13 Oct 2026 | No `menu_history` schema change, so no risk to the readers that explode that row (cooldown, freshness, cadences). The mockup's "saved with the plan" copy becomes **"Picked by you"** |

### Why D3 is a single rule in the code (verified)
The solver stamps `CONST_SLOTS` (`white_rice`, `papad`, `pickle`, `chutney`) and client `forced_items` and client constants, and adds all of them to `pinned_cells` (`src/solver/menu_solver.py`, around lines 1395–1442). The table already refuses to select a pinned cell. "Staple or pinned" is therefore one set, not two.

---

## 2. Open questions (owner must answer; defaults are proposals)

| ID | Question | Why it matters | Proposed default | Blocks |
|---|---|---|---|---|
| O4 | Embed the dish list in the component, or fetch it? | Streamlit resends component arguments on every rerun | Embed and cache; switch to fetch only if the measured gate in spec 06 trips | Phase 4 |
| O5 | Who may override? | The mockup assumes any planner | Any planner; no new permission | none |
| O6 | Version number and approval | Major versions need Project Manager approval; this is one feature | Draft as **2.08.00** (new endpoint, new capability); PM may prefer 2.07.04 | Release |
| O7 | Which slots are exempt from D5? | The solver already exempts `REPEATABLE_SLOTS` (`curd`, `curd_rice`) from unique-items | Exempt `REPEATABLE_SLOTS` and pinned staples; nothing else | Phase 2 |
| O8 | Is "the same item" the exact ontology `item` string, or does it include duplicates folded in v2.02.00 (330 duplicate groups)? | A near-duplicate dish with a different name would pass the check | Exact normalised `item` match, v1 **[unverified: whether variant names remain after the fold]** | Phase 2 |

### How to record an answer
Replace the "Proposed default" cell with the owner's answer, add the name and date, and move the row to section 1 with the next free ID.

---

## 3. Deliberately out of scope for v1

| Item | Reason | Where it would live |
|---|---|---|
| Pick a dish **and** auto-regenerate the rest of the day around it | The pick would have to be injected into the cell's candidate pool, because the pre-filters drop it | v2 work order |
| Persisting exceptions and reasons | O3 | Separate schema order |
| Detecting frequency caps, slot composition and colour constraints in Exceptions | They exist only inside the solver model | v2: per-rule feasibility probe (spec 04 §8) |
| Recording every pick for learning | Not requested | Optional edit-log order |
| Multiple picks in one Apply from the UI | The API accepts a map; the UI sends one | v1.5 |

---

## 4. Change history of this log

| Date | Change | By |
|---|---|---|
| 13 Oct 2026 | Created with D1–D5 and O1–O8 | Claude, from the design conversation |
| 13 Oct 2026 | O1, O2 and O3 answered by the owner and moved to section 1 as D6, D7 and D8 | Claude, from the owner's answers |
