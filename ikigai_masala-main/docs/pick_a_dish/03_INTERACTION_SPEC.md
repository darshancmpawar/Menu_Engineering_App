# 03 · Interaction spec — Pick a dish

Status: **Draft** · written 13 Oct 2026 · applies to `ui/menu_table/index.html`, `ui/menu_table.py`, `app.py`

Reference: the interactive prototype and the mockup (https://claude.ai/artifact/QmwjUF4X6dotuVLE1KNRGF). Where this spec and the mockup differ, **this spec wins** and the mockup is corrected (§11).

---

## 1. Scope

In scope: the Auto/Pick mode, in-cell search, results, apply, undo, the Exceptions section, locked cells, keyboard and screen-reader behaviour, all strings.
Out of scope: the API (doc 02), rule logic (doc 04), persisting exceptions (decision O3).

Today's table (verified): slot rows by day columns; each dish is a button; clicking selects it; "Regenerate selected" sends the selection to Streamlit; pinned cells carry no `data-cell` so they cannot be selected; markers: pin, warning, "changed" (redo).

---

## 2. Elements

| Element | Where | Notes |
|---|---|---|
| Mode toggle `Auto` / `Pick` | table header, right side | Segmented control, two real buttons with `aria-pressed`. Default **Auto** |
| Selection count and `Regenerate selected` | header, Auto mode only | As today; shown when 1 or more cells are selected |
| `Undo last pick` | header | Shown only when at least one pick can be undone |
| Status line | under the header | One line, `aria-live="polite"`, plain text |
| Cell | table | A button (today's), or a search input while being picked |
| Results panel | in the page flow directly under the **row** of the cell being edited | Not floating; it pushes the rows below it down |
| Exceptions section | under the table | Collapsible; hidden when there are none |

---

## 3. Modes and what a click does

| Mode | Click on a pickable cell | Click on a pinned cell | Notes |
|---|---|---|---|
| **Auto** | Toggle selection (today's behaviour) | Status line: the pinned message (§10). Nothing else happens | Multi-select, then `Regenerate selected` |
| **Pick** | The cell becomes a search input, **empty**, focused. Any previous edit closes | Same pinned message | One cell is edited at a time |

* Switching mode clears the selection and closes any open edit. It never changes the plan.
* Pickable = not pinned and not an off day. This is the same predicate the table already uses; no new definition (decision D3).
* Auto must behave **exactly** as it does today. A regression test covers it (doc 06).

The earlier design selected a cell and then chose Pick. That is **replaced** by a table-level mode, because "Pick works on exactly one selected cell" made the toggle ambiguous when several cells were selected.

---

## 4. Pick state machine

```
        ┌──────────────┐  click pickable cell   ┌──────────────┐
        │  Idle (Pick) │ ─────────────────────▶ │   Editing    │
        └──────────────┘ ◀───────────────────── └──────────────┘
              ▲   ▲        Esc / mode switch /     │      │
              │   │        click another cell      │      │ Enter or click on
              │   │        (re-enters Editing)     │      │ a selectable result
              │   │                                 │      ▼
              │   │                         ┌──────────────┐
              │   └─────────────────────────│  Applying    │  server call
              │      error: stay Editing    └──────────────┘
              │      (message in status)            │ success
              └─────────────────────────────────────┘
                       Idle, cell marked, status line set
```

| State | What the user sees | Leaves when |
|---|---|---|
| Idle | Normal table; Pick active | Click a pickable cell |
| Editing | The cell is an input; the results panel is open under its row | Esc, mode switch, another cell clicked, or Apply |
| Applying | Input disabled, a short "Applying…" in the status line | Server answers |
| Error | Back to Editing with the message in the status line; the plan is unchanged | User edits, picks again, or Esc |

An in-progress Apply cannot be started twice (the Enter key and the click are ignored until the call returns).

---

## 5. Results

### 5.1 Content of the panel

* Heading line: `<Slot> · <Day> <date> · replacing <current dish>` on the left; on the right `Searching the <City> city list · <N> dishes` where N is the **count of that slot's dishes in the city list**.
* Up to **8 selectable results**, then up to **3 locked results** (§5.4).
* Footer hint line (§10).

### 5.2 Matching and order (client-side, no network, no Streamlit rerun)

1. Lower-case the query and the dish name; split the query on whitespace into tokens.
2. A dish matches when **every** token is a substring of the lowercase display name (underscores shown as spaces).
3. Empty query: show suggestions (all dishes of the slot, ordered as below), still capped at 8.
4. Order selectable results by: name starts with the whole query first; then **fewer warnings first** (a "Fits" dish before a dish with warnings); then alphabetical.
5. The dish currently in the cell never appears as a result.

### 5.3 Status chips (advisory)

| Chip | Condition | Style |
|---|---|---|
| Fits | no warning | success |
| Served N days ago | days since last served is below the client's cooldown window | warning |
| Not in this client's pool | dish not in the client's narrowed pool for the base slot | warning |
| `+N` suffix | more than one warning: show the first and `+N` | warning |

Chips use icon plus text, never colour alone. They are computed from data embedded in the component; the server audit on Apply is authoritative and may add or drop warnings.

### 5.4 Locked results (decision D5)

A dish already used elsewhere in the same week is shown **after** the selectable results, with a lock chip: `Already on <Day> · one per week`.

* Disabled: no hover state, ignores click and Enter, skipped by arrow keys, `aria-disabled="true"`.
* Shown rather than hidden, so a planner who types a dish they know is on the plan sees why it is unavailable.
* Not a warning, and never appears in Exceptions.
* Text uses the muted text token, not reduced opacity.
* "Same week" follows the owner's answer to O1/O2; the client-side lock only knows the plan on screen. If saved history would also block the dish, the server returns `week_repeat` with `source: "history"` and the panel shows it in the status line and locks that dish for the rest of the edit.

### 5.5 Empty and error results

| Situation | Text |
|---|---|
| No dish matches | `No <slot> dish matches "<query>" in the city list.` |
| Only locked dishes match | the locked rows plus the heading; no extra text |
| Server rejects the pick | the error's `error` sentence in the status line (doc 02 §2.4) |

---

## 6. Apply, banner, undo

1. Apply triggers on **Enter** (on the highlighted result) or **click** (on a result). Nothing needs a second confirmation: a warning is visible in the chip beforehand, and Undo exists.
2. On success the cell shows the **"chosen by you"** marker (pencil). Amber background when the pick has warnings; neutral when clean.
3. Status line: `<Dish> applied to <Day> <slot>. It breaks N rule(s) and is listed under Exceptions.` or `... It fits every check.`
4. `Undo last pick` restores the dish that was there before the most recent pick, and the marker and Exceptions entry it created. The undo stack is per table, in session only, and cleared when a new plan is generated.
5. Picking again in an already-picked cell keeps the **original auto dish** as "replaced", so Undo on the Exceptions entry restores the original, not the previous pick.
6. A picked cell can be selected in Auto mode and regenerated; that replaces the pick and removes its marker and entry.
7. Regenerating other cells locks a picked cell in place (existing behaviour: it is in `base_plan`).
8. After a pick, the dish is added to the session's `regen_seen` list for that cell so a later Auto does not flip back to it.

---

## 7. Exceptions section

* Hidden when there are no picks with warnings. Otherwise a collapsible block under the table, **expanded** by default after the first exception, collapsed again if the user collapsed it.
* Header: chevron, `Exceptions`, a count badge, right-aligned `Picked by you`.
* One entry per picked cell that has warnings: dish, slot, day, `Replaced <auto dish> (auto)`, one row per warning (rule name in bold, then the detail), an optional **Reason** text input, and `Undo this pick`.
* The Reason text lives in component state for the session. It is **not** saved with the plan (decision O3). Do not label it as saved.
* Under the list, one line states the coverage returned by the server: `Checked: <checked list>. Not checked: <not_checked list>.` (doc 04 §6). This line is required; it stops the list reading as complete.
* The header, count and entries update without a Streamlit rerun (local state).

---

## 8. Locked (pinned and staple) cells

* One marker (the pin icon) for both. No separate lock icon (the code has one set).
* Not selectable in Auto, not editable in Pick. No `data-cell`.
* Click shows the pinned message in the status line. Hover title: the same message.
* The server also rejects it (doc 02), so a stale tab cannot bypass this.

---

## 9. Keyboard and accessibility

### 9.1 Keyboard map (Editing state)

| Key | Action |
|---|---|
| Type | Filter results; the highlighted index resets to the first selectable result |
| Down / Up | Move the highlight through **selectable** results, wrapping; locked results are skipped |
| Enter | Apply the highlighted result; if none is selectable, do nothing |
| Esc | Cancel editing; keep the plan; focus returns to the cell button |
| Tab | Leaves the input; the results panel stays open until Esc, mode switch or another cell is clicked |
| Home / End | Move the caret in the input (not the list) |

Auto mode keeps its current keyboard behaviour.

### 9.2 Combobox pattern

* The input has `role="combobox"`, `aria-expanded="true"` while the panel is open, `aria-controls` pointing at the results list, `aria-autocomplete="list"`, and `aria-activedescendant` set to the highlighted option.
* The list has `role="listbox"`; each result `role="option"` with a stable `id`; the highlighted one `aria-selected="true"`; locked ones `aria-disabled="true"`.
* The input has a real label (visually hidden): `Search <slot> dishes`.
* The status line is a polite live region and announces: applied, undone, pinned, rejected.
* Result chips carry text, so a screen reader reads `Paneer lababdar, served 6 days ago`.
* Target size 44 px for results and buttons.
* Contrast: chip and marker text meets 4.5:1; the amber state is never the only signal (the pencil icon and the Exceptions entry carry it).
* **Not tested [unverified]:** screen reader behaviour inside the Streamlit iframe, and virtual keyboard behaviour on mobile (the input must not be covered by the keyboard when results are below it).

---

## 10. UI strings

Sentence case; no terminal punctuation on labels; helper text ends with a period; no "please", no "successfully", no exclamation marks.

| Key | Text |
|---|---|
| Mode: Auto | `Auto` |
| Mode: Pick | `Pick` |
| Mode hint (status, on switch to Pick) | `Pick mode: click a dish to search the city list.` |
| Mode hint (status, on switch to Auto) | `Auto mode: click dishes to select, then regenerate.` |
| Input label | `Search <slot> dishes` |
| Scope line | `Searching the <City> city list · <N> dishes` |
| Replacing line | `<Slot> · <Day> <date> · replacing <dish>` |
| Fits chip | `Fits` |
| Cooldown chip | `Served <N> days ago` |
| Pool chip | `Not in this client's pool` |
| Locked chip | `Already on <Day> · one per week` |
| Footer hint | `Up and down to move · Enter to apply · Esc to cancel · Warnings can be applied; a dish already used this week cannot` |
| No match | `No <slot> dish matches "<query>" in the city list.` |
| Pinned message | `Pinned by a client rule. Search and Regenerate can't change it.` |
| Applied, clean | `<Dish> applied to <Day> <slot>. It fits every check.` |
| Applied, warnings | `<Dish> applied to <Day> <slot>. It breaks <N> rule(s) and is listed under Exceptions.` |
| Week blocked | `<Dish> is already on <Day>. A dish can't repeat in a week.` |
| Undone | `Pick undone. <Dish> is back.` |
| Applying | `Applying…` |
| Server error | the response's `error` sentence |
| Undo button | `Undo last pick` |
| Exceptions header | `Exceptions` |
| Exceptions sub-label | `Picked by you` |
| Replaced line | `Replaced <dish> (auto)` |
| Reason placeholder | `Reason (optional), for example client request` |
| Entry undo | `Undo this pick` |
| Coverage line | `Checked: <list>. Not checked: <list>.` |
| Marker label | `Chosen by you` / `Chosen by you, breaks a rule` |
| Pinned marker label | `Pinned` |

Dish and slot names come from the data (`format_item_for_ui`, `display_label_for_slot_id`); they are not authored strings.

---

## 11. Corrections the mockup needs

| Mockup shows | Change to |
|---|---|
| Separate side search panel under the toolbar and a "Pick works on one dish at a time" tooltip | In-cell search with the results panel under the row; mode is table-level (§3) |
| "Already on Thu" as a warning chip that can be applied | A locked result (§5.4) |
| Separate lock icon for "Fixed" staples and a pin for client pins | One pin marker for both (§8) |
| "Picked by you · saved with the plan" | `Picked by you` (decision O3) |
| Exceptions list that reads as complete | Add the coverage line (§7) |
| "Apply with exception" confirmation footer | Removed; apply on Enter or click (§6) |
| Static "Searching … 1,050 veg gravies" | The count is live per slot (§5.1) |

---

## 12. Technical constraints of the component (verified unless marked)

* One plain HTML file talking to Streamlit over the postMessage protocol; no npm, no bundler.
* Selection and local state live in the component; **only an action sends a value back**, so Streamlit reruns once per Apply, not per keystroke.
* The component rebuilds its DOM with `innerHTML` on a state change and re-attaches handlers. A rebuild while typing would drop the input's focus on every keystroke. **Rule:** while Editing, typing updates only the results container (and calls the height reporter); the table is rebuilt only on Apply, Cancel, mode switch or cell click.
* The component reports its own height to Streamlit; every change to the results panel must re-measure.
* A return value is replayed on every rerun; the `pick` action needs the same nonce guard `regen_request` uses.
* The dish list reaches the component as an argument (default) and is cached per client, city and plan dates (doc 06 gate G5 measures the cost).
* The results panel is in-flow, not floating, because the iframe sizes to its content.

---

## 13. Open items

* Should an Esc keypress while the results panel is open also clear the status line? (Proposed: yes.)
* Exceptions persistence (O3) and its effect on the copy.
* Whether the Reason field should be required for some warning types. (Proposed: never required.)
