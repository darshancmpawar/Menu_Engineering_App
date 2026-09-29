# Version 1.00.02: Dark interface, and tidier internals

**Phase:** 1 Simple tool  **Date:** 3–17 Apr 2026  **Status:** Final

## What changed

The interface was redesigned around a dark theme applied consistently across
the planner, the login screen, the setup editor and the user management screen.
The menu table gained coloured pills for each dish's colour, icons per cuisine
theme, a dash where a cell is empty rather than a blank, and a proper empty
state before anything has been generated.

Two internal clean-ups came with it, neither of which changes a menu.

The part of the solver that assembles and runs the model had grown to handle
five separate concerns in one function — building the context, adding the
built-in colour constraints, applying every rule, building the objective, and
configuring and running the solve. A reader had to hold all five at once. It is
now three named steps in sequence.

The rules package had twenty files, one per rule, with four subject areas
scattered across twelve of them. Reading about how themes work meant opening
four files. Those twelve were consolidated into four modules by subject — theme,
colour, cooldown, non-veg — without renaming a single rule or changing what the
configuration refers to.

## Why it matters

The redesign is what a planner looks at all day. The internal changes are
groundwork: the rule engine grew substantially in the next two versions, and
consolidating first is what kept that manageable.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.00.02 | 3–17 Apr | Darshan + Claude Code | Dark UI redesign; solver pipeline split; rule files consolidated |

**Previous:** [v1.00.01](IkigaiMasala_Final_v1.00.01_2026-04-01.md)  **Next:** [v1.01.00](IkigaiMasala_Final_v1.01.00_2026-05-11.md)
