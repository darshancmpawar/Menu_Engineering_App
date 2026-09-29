# Version 1.00.00: Core planner

**Phase:** 1 Simple tool  **Date:** 30 Mar – 16 Apr 2026  **Status:** Final

## In one line

The first working menu planner: give it a site and a week, and it produces a
menu that obeys the site's rules.

## Why this version was needed

Menus were planned by hand. Somebody had to hold a site's requirements in their
head — which categories it serves, how many dishes in each, which days carry
which theme, what was served recently — and produce a week that satisfied all of
them without repeating itself. It took hours per site per week, and the result
depended on who did it.

## What's new

### 1. A menu engine that plans a whole week at once

The planner builds the week as a single problem and solves it, rather than
filling one day at a time. That is what lets it satisfy rules that span days —
no dish twice in the same week, a dish family no more than twice — instead of
picking a good Monday and then discovering Friday has nothing left.

It is reached through a planning screen where somebody chooses a site, a start
date and a length, and a backing service that does the work.

### 2. Site configuration held in a database

Which categories a site serves, how many dishes in each, and which days carry
which theme are stored centrally rather than in a file. An edit in the setup
screen takes effect on the next generation, with no deployment.

### 3. Several people can generate at the same time

Generating a menu is heavy work, and the first version handled requests one at a
time, so a second person waited for the first.

Menus are now built concurrently, with a limit on how many run at once and a
queue behind it. The work is shared adaptively: one menu being built gets the
full machine, two get half each. When the queue is full the answer is an
immediate, clear "server busy" rather than an indefinite wait.

### 4. Rules that apply to one site only

Three kinds of site-specific rule arrived, configured rather than programmed:

- **Ban an ingredient.** Tekion serves no mushroom. The match is exact, so
  banning "corn" does not also remove baby corn.
- **Cap how often a dish family appears.** One liquid rice a week.
- **Stand a category down on some days.** Tekion serves its non-veg counter on
  Monday, Wednesday and Friday only; on the other days that slot is not planned
  at all.

## What this means for day-to-day use

A planner picks a site and a week and gets a menu that already respects the
site's categories, its themed days, its banned ingredients and its no-repeat
rules — in seconds rather than hours, and the same way regardless of who
pressed the button.

## Known limits

At this stage all sites drew on one shared dish list, and rules were written in
a configuration file by whoever maintained the deployment.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.00.00 | 30 Mar–16 Apr | Darshan + Claude Code | **Core planner.** (1) CP-SAT menu solver, Streamlit UI, Flask API. (2) Client config in Supabase. (3) Concurrent generation for 5+ users. (4) Per-client custom rules |

**Previous:** —  **Next:** [v1.00.01](IkigaiMasala_Final_v1.00.01_2026-04-01.md)
