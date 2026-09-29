# Version 2.05.01: Corrected city lists installed

**Phase:** 2 Scaling  **Date:** 23 Sep 2026  **Status:** Final

## What changed

The five city dish lists were replaced with corrected versions supplied by the
client, and the standing chain of correction scripts was re-run over them. The
dish counts moved: Bangalore 5,960 to 5,885, Chennai 669 to 670, NCR 1,487 to
1,417, Hyderabad 6,055 to 5,992, and Pune 512 to 1,315. Pune more than doubled.

Each list also gained seven columns, six of them describing where a dish comes
from. That had an effect nobody asked for in this version but which matters:
the regional day feature shipped in 2.05.00 had been reporting "not available"
because those columns were missing. With them in place it now offers nine
regions in Bangalore and Hyderabad, and two each in Chennai, NCR and Pune.

Two of the thirty-three correction scripts were skipped on purpose. One would
have folded an older snapshot of the dish list back over the client's newer
corrections. The other normalises raw uploads, and these were already
normalised. One script re-filed nine dishes into the right course and then
stopped changing anything, which is what a correction script should do on a
second run.

Separately, 593 lines of menu-building logic were moved out of the web layer
into their own module. Working out which rules a client has, how far back to
look at what they were served, and how many dishes each slot needs are
statements about a menu, not about serving a web request. The web file went
from 2,651 lines to 2,096.

## Why it matters

Every planning decision in the system reads from these five lists. Installing
them is what makes the corrections visible to the planner: a dish that was
mis-filed as a bread stops being offered as one, and a city that was short of
dishes has more to draw on.

The move of the menu logic out of the web layer is invisible on a menu, but it
means that logic can now be tested on its own, without pretending to serve a
web request first.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.05.01 | 23 Sep | Darshan + Claude Code | Installed five corrected city workbooks and re-ran the correction chain; solve-input assembly moved out of api/app.py |

**Previous:** [v2.05.00](IkigaiMasala_Final_v2.05.00_2026-09-22.md)  **Next:** —
