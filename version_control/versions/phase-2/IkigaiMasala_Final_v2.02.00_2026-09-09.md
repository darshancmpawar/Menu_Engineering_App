# Version 2.02.00: Data quality

**Phase:** 2 Scaling  **Date:** 31 Aug – 9 Sep 2026  **Status:** Final

## In one line

The dish lists behind every menu were corrected, deduplicated and completed,
including 28 dishes that were on the wrong side of the vegetarian line.

## Why this version was needed

The planner is only as good as the dish list it draws from, and by late August
that list had three problems that all failed quietly.

Hyderabad was offered as a city but had no dish list of its own, so every
Hyderabad site was planning from Bangalore's. NCR had 1,000 dishes with no
cuisine recorded, and a blank cuisine is not neutral — it acts as a ban, so 613
of those dishes were invisible on any themed day while still appearing in every
diagnostic as available. And the same dish existed under several names across
the lists, so a rule looking for one spelling never saw the other.

## What's new

### 1. Hyderabad has its own dish list

Built from the client's 41-day Quest grid, seeded from Bangalore's list so the
slots are deep enough to plan. Reading the grid needed care: its two layouts
sit at different row offsets, and read on the wrong one a Wednesday veg gravy
files itself as a dal.

Using only the 191 dishes from the grid would have given about seventeen per
slot and a bread list of one, which runs dry in the second week under the
20-day no-repeat window.

### 2. NCR's missing cuisines filled

767 of the 1,000 blanks were filled from evidence. The dishes a north-themed
NCR day can actually offer grew accordingly:

```
slot           before   after   (of total)
veg_gravy         106     462     489
nonveg_main        38     135     150
veg_dry            49     104     145
rice               39      81     108
```

A site with a north Tuesday was choosing its gravy from 106 dishes; it now
chooses from 462.

### 3. The client's enriched lists merged in

The client returned enriched files for Bangalore, Chennai, NCR and Pune, adding
complete colours (Bangalore was 15.7% blank, NCR 35.7%), a real protein
vocabulary and a 1–5 richness score where the previous column was 98% zeros.

This was merged rather than swapped in. The uploads branched from an older
snapshot, so replacing wholesale would have undone twenty-one course fixes and
brought back rows that had already been removed. Only values crossed over. One
guard was added: a meat protein is accepted only on a dish whose course is a
non-veg slot, because the enriched pass reads protein from the dish *name* and
a name can lie — a vegetarian biryani had been given "mutton" that way.

### 4. One dish, one row — 330 duplicate groups folded

The duplicate audit had always stopped at a report, because merging decides
which name gets printed on a menu. With the client's approval all 330 were
applied and 386 rows removed.

Three kinds of group needed three different treatments. A plain duplicate keeps
the best-described row and fills its blanks from the rows folded into it. A
mis-filed pair needed a verdict naming the surviving *row*, because the better
name sometimes sits on the wrong record — picking alphabetically would have
deleted the correct row and left a bottle-gourd dish in the dal list. And six
groups turned out to be two genuinely different dishes: Aloo Beans is made both
as a dry stir-fry and as an onion-tomato curry, so both rows stay.

### 5. 28 dishes corrected on the vegetarian line

This is the one error in the system whose consequence lands on a plate. The
pool builder reads the protein and egg columns to decide two different things,
so a mistake goes two ways: a vegetarian dish marked non-veg disappears from
the list it belongs to and is offered as the day's meat dish, while a meat dish
marked vegetarian is served to someone who asked not to be served meat. Neither
raises an error. Neither writes a log line.

Every verdict came from looking the dish up rather than from matching its name,
because name rules get these wrong in both directions.

### 6. "Once a week" now means once a week

A second frequency rule type summed its weekly limits over the whole plan
despite their names. Two sites asking for "one liquid rice a week" were getting
one in five weeks on a 25-day plan, while another rule forced one every
Thursday. The duplicate rule type was removed and its capability folded into the
main one, counted by calendar week.

## What this means for day-to-day use

Menus draw on fuller, cleaner lists. A Hyderabad site plans from Hyderabad
dishes. A themed NCR day has four times the gravies to choose from. A rule that
names a dish now finds it whichever spelling was used.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.02.00 | 31 Aug–9 Sep | Darshan + Claude Code | **Data quality.** (1) Hyderabad ontology; NCR cuisine fill; client's enriched ontology merged. (2) Dish fold: 330 duplicate groups. (3) Veg/non-veg line corrections, made to survive re-import. Also: min_per_week replaces item_frequency, honest timeout messages |

**Previous:** [v2.01.00](IkigaiMasala_Final_v2.01.00_2026-08-19.md)  **Next:** [v2.03.00](IkigaiMasala_Final_v2.03.00_2026-09-17.md)
