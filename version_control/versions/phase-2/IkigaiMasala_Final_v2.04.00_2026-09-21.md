# Version 2.04.00: More than one service a day

**Phase:** 2 Scaling  **Date:** 16–21 Sep 2026  **Status:** Final

## In one line

A site can now plan breakfast, lunch, snacks and dinner in one go, with each
service avoiding what the earlier ones already served.

## Why this version was needed

The planner assumed one menu per site per day. A canteen serving both lunch
and dinner had to generate twice and reconcile the two by hand, and the second
menu had no idea what the first one had served — so the same dal could appear
at lunch and again at dinner.

Worse, saving the second menu quietly destroyed the first. Saved menus were
filed by site and date only, so a dinner save overwrote that date's lunch with
no error. The record of what had been served — which is what stops a dish
coming back too soon — was then half missing.

## What's new

### 1. A saved menu now records which service it was

Every stored day carries the service it belongs to, defaulting to lunch. A
dinner save replaces only the dinner rows for those dates. All 61 existing
sites were unaffected: their rows read as lunch, exactly as before. The same
fix was applied to the weekly record, which had the identical fault one table
over.

If a site serves lunch and dinner on Tuesday, both are kept, and the rule that
stops a dish returning too soon can see both.

### 2. Each service avoids what the earlier services served

Services are solved in the order they are eaten: breakfast, lunch, snacks,
dinner. Each one is handed every earlier service's dishes for that week and
told not to use them. Dinner avoids breakfast *and* lunch *and* snacks, not
just the service immediately before it.

A dish is avoided on every day of the week, not only its own day. Otherwise
Monday's lunch dal reappears at Wednesday's dinner within a single generation.
The lists are kept per counter rather than pooled across the site: pooling a
six-counter site's lunch would ban around eighty dishes from every dinner
counter and empty the smaller ones.

Daily staples are deliberately exempt. The everyday curd and the plain chapati
still appear at both services, because that is what a canteen serves.

### 3. Lunch and dinner appear on one screen, one below the other

Dinner is a section beneath lunch, each service with its own table, its own
regenerate button and its own explanation. The two menus are for the same
dates and a kitchen reads them together; putting the second behind a tab means
nobody compares them, which defeats the point of generating it against the
first.

Whether to plan dinner is now a checkbox on the planning screen for that run,
seeded from the site's saved setting. Before this, the only switch was a
database column, and on a database that had not been updated the feature
turned itself off with nothing anywhere saying why.

### 4. How different the two menus are is measured and reported

The client asked for 35–40% of dinner to differ from lunch. Measured on a real
five-day plan, simply excluding lunch's dishes already produces **97%**
different, with no lunch dish reappearing on another day. The screen reports
the achieved share per day and names any day that falls under the floor. It is
reported rather than enforced, because the mechanism already overshoots the
requirement by a factor of two and a half.

### 5. Plate variety rules, built alongside

Four rules were added while the dinner work was underway: a spread of textures
across the plate, no repeating the main ingredient twice on the same plate, a
three-day gap before an ingredient returns to the same slot, and a spread of
protein sources. These stop a plate arriving as paneer gravy beside paneer dry.

## What this means for day-to-day use

A planner ticks "Also plan dinner", generates once, and reads both menus on one
page. Dinner will not repeat lunch, the staples still run at both, and saving
keeps both records.

## Known limits

Replaying a previously saved plan still returns lunch only.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.04.00 | 16–21 Sep | Darshan + Claude Code | **Multi-service planning.** (1) Meal dimension in menu_history; meal-aware /plan, /save, /saved-plan. (2) Dinner planner screen below lunch with its own controls; lunch ≠ dinner rule. (3) Services as a list: breakfast / lunch / snacks / dinner. (4) Plate variety rules built alongside: texture, same-day and 3-day key ingredient, protein |

**Previous:** [v2.03.00](IkigaiMasala_Final_v2.03.00_2026-09-17.md)  **Next:** [v2.05.00](IkigaiMasala_Final_v2.05.00_2026-09-22.md)
