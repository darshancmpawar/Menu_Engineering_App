# Version 2.01.00: Fleet expansion

**Phase:** 2 Scaling  **Date:** 5–19 Aug 2026  **Status:** Final

## In one line

A fourth city, a separate view for sites still being set up, and counters that
can be made to serve the same dish as each other.

## Why this version was needed

Three cities were live and the fourth, NCR, had a rule file but no dish list
behind it. Every site appeared in one long list whether it was feeding people
or still being configured. And a site with several counters had no way to say
"the bread is the same at all of them" — each counter chose independently, so
one queue got chapati and the next got naan on the same day.

## What's new

### 1. NCR has its own dish list — 1,544 dishes

Built from the client's pre-mapped workbook. Most of the work was correction
rather than import: two fish dishes were filed under chicken, 31 dishes sat in
the wrong course including a kulfi being offered as a gravy, ten rows were
category names rather than dishes, and 35 desserts were retagged by region.

The client also asked for a fuzzy name-merge in the source file to be reversed,
because it had merged dishes that were not the same dish.

### 2. Launch sites are kept apart from live ones

A site can be marked as a launch site. The planner then has two views that
divide the fleet between them: the launch view lists sites being set up, and
the Ops view lists the ones running. Before this, the second view showed
everybody.

When a launch site goes live, a "Move to Ops Client View" button reclassifies
it and it moves across immediately. Every site that already existed was
classified as operational when the flag was added, so nothing moved unasked.

### 3. Counters can share a category

A site can declare that certain categories are common across its counters. The
first counter is planned, and the dish it picked for each shared category is
handed to the others as a fixed choice.

If a site declares bread as common, every counter serves the same bread that
day, while the non-veg counter still picks its own main independently. An
explicit pin on a particular counter wins over the shared dish, and if a shared
dish cannot go in a sibling counter's slot, that slot is planned normally
rather than the whole menu failing.

### 4. Rules that reach across weeks, and menus that stay fresh

Three planning improvements landed together. A new rule type expresses cadences
longer than one plan — "fish no more than once in fifteen days" — by reading
what was actually served rather than only what is in the current week.
Regenerating a day no longer cycles back to a menu it has already shown. And a
freshness score nudges the planner towards dishes that have not been served for
a while, rather than treating every eligible dish as equal.

### 5. Client menus imported into the dish lists

Real client menus were imported, taking Bangalore from 4,988 to 6,183 dishes
and Chennai from 425 to 616. Deeper lists are what let a daily slot run for
several weeks without repeating.

## What this means for day-to-day use

An account manager setting up a new site works in the launch view without it
cluttering the live fleet, then promotes it with one button. A multi-counter
site can guarantee the same bread at every queue. And a planner generating week
three gets a menu that does not repeat week two, because the cadence rules and
the freshness score are reading the saved history.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.01.00 | 5–19 Aug | Darshan + Claude Code | **Fleet expansion.** (1) NCR ontology (1,544 items) and site logic. (2) Launch sites: flag, launch view, Launch→Ops promotion. (3) Shared categories across counters, cross-week cadence rule, regenerate anti-cycling, freshness objective. (4) Client menu importers: Bangalore 4,988 → 6,183 dishes, Chennai 425 → 616 |

**Previous:** [v2.00.01](IkigaiMasala_Final_v2.00.01_2026-08-04.md)  **Next:** [v2.02.00](IkigaiMasala_Final_v2.02.00_2026-09-09.md)
