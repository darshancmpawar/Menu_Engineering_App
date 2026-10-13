# Pick a dish (search override) — Documentation pack

Repo `Menu_Engineering_App` (Ikigai Masala, v2.07.03) · pack written 13 Oct 2026 · status **Draft for owner review**

This pack is everything Claude Code needs to build the feature, and everything the team needs to review, test, release and explain it.
The feature in one sentence: **on the menu table, a planner switches from Auto to Pick, clicks a dish, and searches the city item list by name to put a specific, already-decided dish in that cell; the pick may break rules (shown as Exceptions) except the one-dish-per-week rule, and pinned or staple cells can never be changed.**

---

## 1. The documents

| # | File | For whom | One-line purpose | Status |
|---|---|---|---|---|
| 00 | `00_README_INDEX.md` | everyone | This index | Draft |
| — | `PICK_A_DISH_WORKORDER.md` (separate file, already delivered) | Claude Code | The master build order: spec, architecture, phases, gates | Needs the §11 owner answers folded in |
| 01 | `01_DECISION_LOG.md` | owner, PM, lead dev | Locked decisions D1–D5 and the open questions with proposed defaults | **Owner must answer O1–O3 before Phase 1** |
| 02 | `02_API_CONTRACT.md` | Claude Code, Pulse team | Exact request, response and error shapes for `/api/v1/pick` and the `/regenerate` guard | Draft |
| 03 | `03_INTERACTION_SPEC.md` | UI builder, QA | States, keyboard map, accessibility, every UI string | Draft |
| 04 | `04_RULES_AND_AUDIT_SPEC.md` | Claude Code, ops | What blocks, what warns, what is not checked, in what order | Draft |
| 05 | `05_CLAUDE_CODE_PROMPT_PACK.md` | the person driving Claude Code | Paste-ready prompts, one per phase | Draft |
| 06 | `06_TEST_AND_ACCEPTANCE_CHECKLIST.md` | QA, owner | Pass/fail test matrix, measured gates, manual QA script, sign-off | Draft |
| 07 | `07_RELEASE_AND_DOCS.md` | tech writer, PM | Version document, change-control row, `repo_map` note, `api.md` text, planner guide | Draft; finish after the build |

Related deliverables already made: the interactive prototype (shown in chat) and the 4-artboard mockup at https://claude.ai/artifact/QmwjUF4X6dotuVLE1KNRGF. The mockup needs the fixes listed in `03_INTERACTION_SPEC.md` §11.

---

## 2. Who owns which fact (one source of truth)

When two documents disagree, the owner of that fact wins.

| Fact | Owning document |
|---|---|
| What was decided, and by whom | 01 |
| Request/response/error shapes | 02 |
| What the screen does and says | 03 |
| Which rule blocks, warns or is unchecked | 04 |
| How to instruct Claude Code | 05 |
| What "done" means | 06 |
| What is told to planners and recorded in version control | 07 |
| Build phases, data flow, file-level changes | the master work order |

---

## 3. Recommended order

1. Owner answers the open questions in **01** (O1 week definition, O2 history scope, O3 persistence).
2. Review **02** and **04** together (they share the week rule and the error codes).
3. Review **03** with the prototype open.
4. Hand **05** to Claude Code, with the work order and docs 02–04 copied into the repo (suggested path: `ikigai_masala-main/docs/pick_a_dish/`).
5. Run the gates in **06** after each phase.
6. After Phase 4 passes, finish **07** and release.

---

## 4. Conventions used in every document

* **Verified** = read from the repo or measured. **[unverified]** = a claim to confirm in the first phase that touches it. **[proposal]** = a number or choice the owner may change.
* UI copy is sentence case, no terminal punctuation on labels, no emoji, contractions allowed (the repo's content rules).
* Dish names in examples are illustrative sample data. Real counts (for example Bangalore `veg_gravy` = 1,050 rows) are from the workbooks.
* Nothing in this pack has been implemented or run.
