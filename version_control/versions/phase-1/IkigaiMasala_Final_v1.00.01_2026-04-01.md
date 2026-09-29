# Version 1.00.01: Pool checks before solving, and a simpler editor

**Phase:** 1 Simple tool  **Date:** 31 Mar – 1 Apr 2026  **Status:** Final

## What changed

The planner now checks, before it starts building a menu, whether each slot has
enough dishes to fill the days being asked of it. If a category is short, the
warning names the day and the slot, and appears above the menu table rather than
arriving as a failure minutes later.

Theme badges on the generated table were showing a fixed weekday pattern rather
than the site's own theme settings, so a site with a Chinese Tuesday was
labelled as though it had the default themes. The badges now come from the
site's configuration, and the day's theme is carried through the response so
the screen can show it.

The setup editor was reorganised into one flow for creating a site: name, then
categories, then how often each is served, then the day themes, ending in
Create or Reset. It shows whether a chosen category matched an existing one or
is new. The Delete button was removed from the existing-site view, leaving Save
and Reset.

The solver's time limit was fixed at 180 seconds and the slider that exposed it
was removed — it was a setting no planner could usefully choose.

## Why it matters

A planner who asks for a week that cannot be filled finds out immediately,
with the specific day and category named, instead of waiting for a failure. And
a site with custom themes sees its own themes on screen rather than somebody
else's defaults.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.00.01 | 31 Mar–1 Apr | Darshan + Claude Code | Pre-solve pool validation; editor Create New flow; save fixes |

**Previous:** [v1.00.00](IkigaiMasala_Final_v1.00.00_2026-04-16.md)  **Next:** [v1.00.02](IkigaiMasala_Final_v1.00.02_2026-04-17.md)
