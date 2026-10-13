# 07 · Release and documentation — Pick a dish

Status: **Draft** · written 13 Oct 2026 · **finish after Phase 4 passes**. Every sentence here describes the *intended* behaviour; Phase 5 (doc 05) must check each claim against the code and the tests before this is released.

Contents: A. version document · B. change-control row · C. `CURRENT.md` · D. `docs/repo_map.md` additions · E. `docs/api.md` · F. `docs/architecture.md` · G. planner guide · H. release checklist.

The version number is a **proposal**: major versions need Project Manager approval and bundle three or four related features (`version_control/README.md`). Pick a dish is one feature; the PM may prefer a minor (2.07.04) or to bundle it with other work (decision O6).

---

## A. Version document (draft)

File: `version_control/versions/phase-2/IkigaiMasala_Draft_v2.08.00_<date>.md` (rename to `Final` on release, per the README).

```markdown
# Version 2.08.00: Pick a dish from the city list

**Phase:** 2 Scaling  **Date:** <last day of the span>  **Status:** Draft

## In one line

On the menu table you can now switch from Auto to Pick, click a dish, and
search the whole city list by name to put the exact dish you have already
decided on in that cell. It tells you which rules the dish breaks, but it
will not let a dish appear twice in one week, and it will not touch a pinned
or staple cell.

## What changed

### 1. Auto or Pick

The table header has a new switch. **Auto** is the regenerate you know, and
nothing about it has changed. **Pick** turns each dish into something you can
search: click the dish, type part of a name, and choose from the list.

### 2. Search covers the whole city

The list is every dish of that kind on the city's menu list, not only the
dishes in this client's pool. That means you can choose a dish the client has
not had before. If it is outside their pool, you are told.

### 3. You are told what a dish breaks, and you can still use it

Each result shows whether it fits. A dish can show:

- "Served N days ago" when it is inside the repeat window;
- "Not in this client's pool".

You can still choose it. A dish that breaks a rule is marked on the table and
listed under **Exceptions**, with the rule it breaks and an optional reason
box. **Undo last pick** puts the original dish back.

### 4. The one rule that cannot be overridden

A dish cannot appear twice in one week. A dish already used that week is
shown greyed out with "Already on Tue · one per week" and cannot be chosen.
The system also checks the menus already saved for that week, so the rule
holds even for a day you did not plan today.

### 5. Pinned and staple cells stay as they are

A cell fixed by a client rule, and the daily staples (steamed rice, papad,
pickle, chutney), cannot be changed by Pick **or** by Regenerate. This is now
enforced by the system, not only by the screen.

## What stays the same

- Auto and Regenerate selected work exactly as before.
- Generating a plan, saving, and the rules are unchanged.
- A pick does not re-run the planner; every other dish stays exactly as it was.

## Things to know

- **Exceptions are not saved.** Picks are saved with the menu like any dish,
  but the Exceptions list and your reasons exist only on screen for this
  session.
- **Exceptions are not a full rule check.** The list covers: the repeat
  window, the client's pool, the rice and bread gap, rules that filter dishes
  out, and the plate checks. It does **not** check weekly limits (for example
  "biryani once a week"), how the day's dishes are composed, or the colour
  rules. The screen says this under the list.
- A picked dish is saved with the menu, so it counts toward the repeat window
  for future weeks like any other dish.

## Questions for you

1. Should the week rule count dishes served by the client's other counters,
   and at lunch versus dinner? It does for the repeat window today.
2. Do you want the Exceptions and reasons saved with the menu? That needs a
   change to how menus are stored.
```

---

## B. Change-control row (for the master record, newest first)

Add at the top of the Phase 2 table in `version_control/IkigaiMasala_<Status>_v<version>_<date>.md`, after moving the previous master to `archive/` (README release steps 1–2):

```markdown
| **2.08.00** | <dates> | Darshan + Claude Code | **Pick a dish from the city list.** (1) Auto/Pick mode on the menu table; in Pick the cell becomes a name search over the whole city list. (2) New `POST /api/v1/pick`: stamps the chosen dish without a solve, then audits it (cooldown, client pool, rice-bread gap, pre-filter rules, plate checks) and returns the findings as Exceptions, with the checks it did NOT run listed beside them. (3) The one-dish-per-week rule is a hard block, read from the plan, the other picks and saved history. (4) The pinned-cell set (staples, pins, client constants) extracted into one function, and `/regenerate` now refuses pinned cells server-side | <commits> |
```

Feature-to-version map row (README layout §4 of the master record):

```markdown
| Pick a dish (search override) | 2.08.00 | 2.08.00 | api/app.py (`/pick`), src/solver/picker.py, ui/menu_table/ |
```

---

## C. `version_control/CURRENT.md` (only when the version is approved)

```markdown
# Current version

**2.08.00** — <date>

On the menu table you can switch from Auto to Pick and search the city list by
name to put an already-decided dish in a cell. It lists the rules the dish
breaks under Exceptions, blocks a dish that would appear twice in one week, and
leaves pinned and staple cells alone.

- Version document: [IkigaiMasala_Final_v2.08.00_<date>.md](versions/phase-2/IkigaiMasala_Final_v2.08.00_<date>.md)
- Master change control record: [IkigaiMasala_Final_v2.08.00_<date>.md](IkigaiMasala_Final_v2.08.00_<date>.md)

Next major is 2.09.00, next minor is 2.08.01, next phase 3.00.00.
```

---

## D. `docs/repo_map.md` additions (repo root `docs/`)

File rule (its §11): one line per row, optimised for scanning. Match the neighbouring rows' columns.

**§3 API surface** (beside the `/api/v1/regenerate` row):

```markdown
| POST | `/api/v1/pick` | put a chosen dish in a cell WITHOUT a solve: stamps it, audits it, returns `exceptions` plus `checked`/`not_checked`; 400 `week_repeat` (one dish per week, plan + picks + saved history), `pinned_cell`, `not_a_slot_dish`; `@rate_limit("diagnose")`, no `@solver_gate` |
```

Also amend the `/regenerate` row: append "; refuses pinned cells (400 `pinned_cell`)".

**§4 module map** (beside `regenerator.py`):

```markdown
| `picker.py` | `pick_cells`, `week_repeat`, `audit_pick` | stamp a user-chosen dish and audit it; guards: pinned, category (city list), one-dish-per-week |
```

and, for the extracted function, a row noting its location and that `solve()` and `picker.py` both call it.

**§5 UI layer** (menu table row): append "Auto|Pick mode; in Pick the cell is a combobox over the city list; `pick` action returns `{cell, item, nonce}`; Exceptions section".

**§8 tests**: add rows for `tests/api/test_pick.py`, `tests/ui/test_pick_request.py`.

**§9 design note** (use the next free number after the highest existing note; 41 at the time of writing). Draft:

```markdown
N. **A user's pick is stamped and audited, never solved, because a solve cannot hold a dish the pool already rejected.** Regenerate locks every other cell and re-runs CP-SAT with the pick as the one candidate; a dish the pre-filters removed (cooldown, theme, pool) leaves the cell with no variable to choose, so the model is INFEASIBLE, and the existing "pinned dish not eligible" path is worse: it logs at INFO and solves the cell normally, answering 200 with a different dish than the one typed. `/api/v1/pick` therefore changes one cell and audits it. **Three decisions, each against a silent failure.** (a) *The week rule is a block, not a warning*, and it runs before the cooldown audit, because a dish served earlier this week is also inside the 21-day window and would otherwise surface as a mere "served N days ago" warning that can be overridden. (b) *History rows for the plan's own dates are excluded from that check*: a saved plan is overwritten per (client, dates), so counting those rows makes every dish block itself and its siblings. (c) *`checked` and `not_checked` are always returned*: weekly caps, `slot_composition` and colour constraints exist only inside the model, so an Exceptions list that omitted them would read as complete (note 31's lesson in a new place). **The pinned set is one function**, extracted from `MenuSolver.solve` (staples + `forced_items` + client constants), because both `/pick` and `/regenerate` must refuse those cells without a solve, and two definitions drift. The client lock is a convenience; the server checks are the rule. v2 closes the coverage gap with a per-rule feasibility probe over a fully locked plan. `tests/api/test_pick.py`.
```

(Check every sentence of this note against the code in Phase 5 before committing it.)

---

## E. `docs/api.md`

Add the three endpoint rows to the table at the top and paste the sections of doc 02 §2–§5 under a heading `## Pick a dish`. Keep the repo's tone: one table row per endpoint, examples as fenced JSON.

---

## F. `docs/architecture.md` paragraph

Add under the regenerate flow paragraph:

```markdown
Streamlit → `POST /api/v1/pick` → `picker.py` validates the cell (not pinned, a dish of that slot in the city list, not already used this week in the plan, the request or saved history), stamps the dish with the solver's colour suffix, and audits it against the cooldown, the client's pool, the rice-bread gap, every rule's `pre_filter_pool` and the plate checks, returning findings as `exceptions`. It never builds a CP-SAT model, so it takes no solver slot. Findings are warnings; the only blocks are the pinned set, the category, and the week rule.
```

---

## G. Planner guide (for the people who use the table)

```markdown
# Picking a dish yourself

Use this when you already know the dish you want in a cell.

## Do it
1. Switch the header from **Auto** to **Pick**.
2. Click the dish you want to replace. It turns into a search box.
3. Type part of the name. The list shows dishes from the whole city list.
4. Choose one with the arrow keys and Enter, or click it.
5. The cell shows a pencil: you chose this dish.

To go back, press **Undo last pick**.

## What the labels mean
- **Fits** — it breaks no rule we check.
- **Served N days ago** — it is inside the repeat window. You can still use it.
- **Not in this client's pool** — it is on the city list but this client's menu list does not include it. You can still use it.
- **Already on Tue · one per week** — it is greyed out. A dish cannot appear twice in one week, so you cannot pick it.

## Exceptions
If your dish breaks a rule, the cell turns amber and the **Exceptions** section lists the rule. You can add a reason. Exceptions are **not saved** with the menu; if you want to remember why, write the reason somewhere else.

Under the list you will see what was checked and what was not. We do not check weekly limits, how the day's dishes are composed, or colour rules. Look at those yourself.

## What you cannot change
Cells with a pin, and the daily staples (steamed rice, papad, pickle, chutney). Neither Pick nor Regenerate can change them. They are set by the client's rules.

## Good to know
- Picking a dish does not re-plan the week. Every other dish stays as it is.
- To replace a pick, click it again and search, or select it in Auto and regenerate.
- A dish you pick counts toward the repeat window for future weeks, like any other dish.
```

---

## H. Release checklist (per `version_control/README.md`)

| # | Step | Done |
|---|---|---|
| 1 | Gates G0–G7 recorded in doc 06; open questions answered in doc 01 | ☐ |
| 2 | Project Manager approves the version number (O6) | ☐ |
| 3 | `git mv` the current master record into `version_control/archive/` | ☐ |
| 4 | Copy it to the new version and date; add the §B row at the top of the change-control table and the feature-map row | ☐ |
| 5 | Write the version document in `versions/phase-2/` from §A; research the key commits with `git show` and describe what the code does | ☐ |
| 6 | Update `CURRENT.md` (§C) and the Previous/Next links either side of the new document | ☐ |
| 7 | Apply §D–§F to `docs/repo_map.md`, `docs/api.md`, `docs/architecture.md` | ☐ |
| 8 | Publish the planner guide (§G) where planners read their instructions | ☐ |
| 9 | Commit `docs(version): v2.08.00`; tag that commit | ☐ |
| 10 | Rename the version document from `Draft` to `Final` | ☐ |

Do not release until every sentence in §A has been checked against the code. Anything unverified is either removed or listed under "Things to know".
