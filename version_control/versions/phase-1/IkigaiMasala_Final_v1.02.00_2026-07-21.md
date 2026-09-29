# Version 1.02.00: Counters and richer data

**Phase:** 1 Simple tool  **Date:** 15–21 Jul 2026  **Status:** Final

## In one line

A site can run several serving counters, each with its own categories and
themes, and the dish list grew from about 530 dishes to 4,656.

## Why this version was needed

The planner assumed one menu per site. Real sites run several counters — a
north Indian station, a south Indian one, a non-veg one — each with its own
categories and its own themed days. There was no way to describe that, so a
multi-counter site was configured as though it were one.

The dish list was also thin: about 530 dishes for the whole system. A daily
slot drawing from that runs out of variety quickly.

## What's new

### 1. Multiple counters per site

Setting up a site is now a stepped flow: choose or create the site, choose
single or multi-counter, then configure each counter's categories, how many
dishes each category serves, and which days carry which theme.

A multi-counter site produces one menu per counter, each planned from its own
categories and themes, shown as one table per counter with its own regenerate
and clear buttons, and a shared save. If one counter cannot be planned, its
error appears in that counter's tab and the others still generate.

The setup screens also got their own light theme, distinct from the planner's
dark one.

### 2. Site configuration simplified from seven tables to four

The configuration had been spread across several linked database tables, which
cost a join and several round-trips every time a site was read, and left orphan
rows behind that nothing cleaned up. The whole configuration for a site is now
one record. Reading a site's setup went from about five queries with joins to a
single row read.

### 3. The dish list grew to 4,656 dishes

The enriched list replaced the old one. Non-veg detection scaled with it — 360
non-veg dishes including 73 egg dishes — and every course value still maps to a
known slot.

### 4. City, weekend service, and a Continental theme

A site now records its city, which is the groundwork the whole of Phase 2 is
built on.

A site can be marked as serving weekends, so a six-day plan starting Monday
runs to Saturday instead of skipping to the following week.

A Continental theme joined Chinese, along with a combined option that
alternates between the two by calendar week — so a site can have a
Chinese/Continental Tuesday that changes fortnightly without anyone editing it.

### 5. Excel export, and non-veg dishes in red

The menu downloads as a formatted Excel file — one sheet per counter, bordered
and filled headers, and non-veg dishes printed in red. The planner screen marks
them in red too, which matters in a kitchen where the vegetarian and non-veg
counters are run by different people.

## What this means for day-to-day use

A site with three counters is set up once and generates three menus in one
action, each obeying its own categories and themes. The kitchen gets an Excel
sheet per counter with the meat dishes visibly marked.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.02.00 | 15–21 Jul | Darshan + Claude Code | **Counters and richer data.** (1) Multi-cuisine counters with per-counter generation; schema 7 → 4 tables; Pulse theme. (2) Client city field and city filter. (3) Formatted Excel export and non-veg highlighting. (4) Enriched ontology (~530 → 4,656 items) with Continental theme, weekend service, combination categories, per-client cooldown |

**Previous:** [v1.01.01](IkigaiMasala_Final_v1.01.01_2026-04-30.md)  **Next:** [v1.03.00](IkigaiMasala_Final_v1.03.00_2026-07-25.md)
