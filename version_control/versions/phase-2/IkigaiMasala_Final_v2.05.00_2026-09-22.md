# Version 2.05.00: Regional theme days

**Phase:** 2 Scaling  **Date:** 21–22 Sep 2026  **Status:** Final

## In one line

A planner can give one day of the week a regional focus — a Tamil Nadu
Thursday — without rebuilding the rest of the week.

## Why this version was needed

Days could already carry a cuisine theme: Chinese Tuesday, biryani Wednesday.
What they could not carry was a region. A site that wanted a Maharashtrian
Friday or a Punjabi Monday had no way to say so, and the only workaround was
to pick the dishes by hand after the menu was generated.

There was also a trap waiting. The obvious way to build this is to narrow the
day's dish list to that region, the same way a Chinese day narrows to Chinese
dishes. Measurement showed that would break: Bangalore's list holds 47 Punjabi
veg gravies and **zero** Punjabi rice and **zero** Punjabi bread. Kerala has
four rices. Telangana has two veg dries. Narrowing those slots would empty
them, and the system had already had exactly that failure once before with
south Indian breads in NCR.

## What's new

### 1. A region is a floor, never a filter

Asking for a Punjabi Monday now means "serve at least this many Punjabi dishes
on Monday", not "serve only Punjabi dishes on Monday". The list of slots the
floor applies to is worked out from what that region actually has. Punjab's
floor covers the gravy, the veg dry, the dal, the non-veg and the dessert;
rice and bread are simply left out of it, because the city list has none.

The practical effect: a kitchen asking for a Punjabi Monday gets Punjabi
gravies and dals alongside an ordinary rice, instead of an error or an empty
rice counter.

### 2. The control sits on the planner, not in the setup screen

Choosing a region is a weekly editorial decision — "let's do a Tamil Thursday
this week" — not a permanent fact about the site. So the pickers are a row
above the menu table on the planning screen, hidden behind a toggle that is off
by default, and they work **after** a menu already exists. Writing the choice
into the site's permanent weekday settings is a separate, optional step from
the same screen.

### 3. Applying a region re-solves one day against the rest of the week

Nothing new was added to the menu engine for this. Applying a region reuses the
existing regenerate path, which locks every dish the planner is not replacing.
The week's no-repeat rule, the cooldown that stops a dish returning too soon,
the freshness scoring and the cross-counter matching all still hold. The chosen
day is rebuilt in the context of the week around it, not in isolation.

### 4. Only regions the city can actually serve are offered

Measured at the point where the no-repeat window bites, most cities can support
only one to three regions at all; Chennai supports exactly one. The picker
lists what the city can genuinely do, so a planner finds out before generating
rather than after.

## What this means for day-to-day use

A planner who wants a regional day turns on the toggle, picks the region for
that day, and regenerates. The rest of the week stays as it was. If the
region's dishes have been used too recently, the day comes back with fewer of
them and the explanation says the pool ran out that week — which is a different
message from "this city has no Punjabi rice", and that one is visible in the
picker before anyone presses a button.

## Known limits

The columns describing where each dish comes from were not yet in the installed
dish lists when this shipped, so the feature reported itself unavailable until
version 2.05.01 installed them.

One fault was found and fixed during the work: the first request for a city's
region list would hang forever rather than fail. Two pieces of code were both
waiting for the same lock, and nothing raised an error — the page simply never
answered. Cold start is now 4.5 seconds, and 1 millisecond once measured.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.05.00 | 21–22 Sep | Darshan + Claude Code | **Regional theme days.** Design measured against five new client workbooks; regional days placed on the planner (not the config editor) behind a toggle; region-cache deadlock fixed |

**Previous:** [v2.04.00](IkigaiMasala_Final_v2.04.00_2026-09-21.md)  **Next:** [v2.05.01](IkigaiMasala_Final_v2.05.01_2026-09-23.md)
