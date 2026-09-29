# Version 2.00.01: Faster cold start, clearer layers

**Phase:** 2 Scaling  **Date:** 4 Aug 2026  **Status:** Final

## What changed

The dish-list loading and slot-building code was moved out of the web layer
into a module of its own, together with the caches behind it. 39% of the web
file was not about serving web requests.

The immediate, measurable effect is on the screen that populates the setup
editor. Opening it for the first time took **4,828 milliseconds**; it now takes
**12**.

The move also closed a fault that had been producing confusing test failures.
Four separate caches had to be cleared between runs, and the clearing was
copied by hand into 22 places across 18 files. Missing one left a stale
4,300-row Bangalore dish list answering a question about Chennai, and the
failure surfaced in a different file depending on the order things ran in.
There is now one call that clears all of them.

One deliberate change of shape came with it: the dish-list layer used to look
up a site's city and dish pools in the database itself. That is not its job, so
the caller now passes both in. The dish-list layer no longer touches the
database at all.

A second pass moved the remaining Flask-free work — 19 functions and 604 lines
that touched no web code whatsoever — into an application layer beside it.

## Why it matters

Nothing about a menu changes. What changes is how long a planner waits for the
setup screen, and how confidently the code underneath can be changed: the
dish-list logic can now be exercised on its own, rather than by pretending to
serve a web request first.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.00.01 | 4 Aug | Darshan + Claude Code | Application layer and ontology repository split out of Flask; /editor-metadata cold start 4,828 ms → 12 ms |

**Previous:** [v2.00.00](IkigaiMasala_Final_v2.00.00_2026-08-03.md)  **Next:** [v2.01.00](IkigaiMasala_Final_v2.01.00_2026-08-19.md)
