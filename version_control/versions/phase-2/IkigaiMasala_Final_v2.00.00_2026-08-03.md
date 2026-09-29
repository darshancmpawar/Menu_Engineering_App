# Version 2.00.00: Multi-city foundation

**Phase:** 2 Scaling  **Date:** 27 Jul – 3 Aug 2026  **Status:** Final

## In one line

Each city gets its own rules and its own dish list, and each client — and each
counter within a client — can vary them.

## Why this version was needed

Everything ran off one rulebook and one dish list. That was right while the tool
served Bangalore, but it could not describe a second city: a Pune site would
have been planned against Bangalore's rules and offered Bangalore's dishes.

Client-specific behaviour had the same shape. Rules could be varied for a
client, but not for one counter within that client. A site with a dedicated
non-veg counter that genuinely serves biryani every day had to switch the
weekly biryani cap off for the whole site — including the vegetarian counters,
silently, the moment either of them gained a non-veg slot.

## What's new

### 1. One rule file per city, with inheritance

Rules now live in a file per city. A city's file can inherit another city's
rules and override them by name, or switch individual inherited rules off. Pune,
Chennai, Hyderabad and NCR each start by inheriting Bangalore's reference
rulebook and diverge from there.

A city nobody has written a file for still plans, by falling back to the
reference rulebook, so adding a city to the list can never break planning.

### 2. Rules can be scoped to a single counter

A client block can now carry per-counter overrides, applied on top of the
client-level ones. The case that prompted it: L&T's "Non Veg Lunch" counter is
deliberately biryani five days a week, so the weekly biryani cap comes off
*there* while staying on for South Lunch and North Lunch.

Client-specific rules went from covering 1 site to 24 in the days after this
landed.

### 3. Pinned dishes, working days, and weekday-specific requirements

Three client-level capabilities arrived together.

A client can pin a slot to a fixed dish, either every day or by weekday — this
is how a daily curd or a Monday-Wednesday-Friday chapati is written.

A client can declare which days of the week it serves, and the plan covers only
those days.

And a requirement can be keyed to a named weekday rather than to a theme. Six
clients needed this, and the sample menus showed why: "biryani day" meant the
vegetarian biryani in the rice slot for some sites and the non-veg biryani for
others, and several served both on different days. AstraZeneca has veg biryani
on Monday and Wednesday and no non-veg biryani at all; Plan View's non-veg
biryani is Tuesday and its vegetarian one Friday. A rule naming a biryani has to
say which one it means.

### 4. Pune and Chennai get their own dish lists

The dish list was a single file for the whole system; it is now one file per
city, chosen from the site's city. Pune's list arrived with 274 dishes, all
vegetarian.

Sites in cities with no list of their own still fall back to Bangalore's, so
nothing stops working while a city's list is being built.

## What this means for day-to-day use

An account manager can set up a Pune site and have it planned against Pune's
rules and Pune's dishes. A site with several counters can have a rule apply to
one of them without touching the others. And a requirement that names a day of
the week — "chapati on Monday, Wednesday and Friday" — can now be written down
rather than fixed by hand after each generation.

## Known limits

At this point Chennai, Hyderabad and NCR still shared Bangalore's dish list;
their own lists followed in later versions.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.00.00 | 27 Jul–3 Aug | Darshan + Claude Code | **Multi-city foundation (start of scaling).** (1) Per-city rule files with inheritance. (2) Client-level configuration: client-specific rules go from 1 client to 24; counter-scoped overrides, constant items, working days, weekday composition. (3) Pune and Chennai ontologies and rulesets, pools scoped to city |

**Previous:** [v1.03.00](../phase-1/IkigaiMasala_Final_v1.03.00_2026-07-25.md)  **Next:** [v2.00.01](IkigaiMasala_Final_v2.00.01_2026-08-04.md)
