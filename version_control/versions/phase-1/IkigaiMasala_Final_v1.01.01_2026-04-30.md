# Version 1.01.01: Docker, and a clearer regenerate panel

**Phase:** 1 Simple tool  **Date:** 27–30 Apr 2026  **Status:** Final

## What changed

The application was packaged to run in a container, with a Dockerfile, a
compose file and the setup and operations notes to go with it.

Two things the planner screen did on every click were made to stop doing it.
The connection to the backend was being rebuilt from scratch every time anyone
touched a control, so each click paid for a fresh network handshake; it is now
kept and reused. The list of sites was being re-fetched just as often, and is
now held briefly. Logging out clears both, so a new sign-in cannot reuse the
previous one's connection.

The regenerate panel was reworked after use showed up three irritations. The
changes log now records each replaced dish as a before-and-after line — the old
dish struck through, an arrow, the new dish in bold — instead of a single line
saying how many cells changed. Where the solver chose the same dish again,
those are collapsed into one row rather than listed as changes.

The dish picker now shows the current dish beside each slot ("Veg Dry — Aloo
Gobi"), so it is clear what is being replaced, and the picker is capped at three
columns because the labels were being truncated to fragments like "lavor …".

Saving switched to a small notification instead of reloading the whole page,
and the menu table now fades in rather than flashing on each repaint.

## Why it matters

None of the menu logic changed. What changed is that the planner stopped
feeling slow on every click, and that a planner regenerating a few dishes can
see exactly what was swapped for what — which is what they are asked to sign
off.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.01.01 | 27–30 Apr | Darshan + Claude Code | Docker; from→to changes log; smoother regenerate panel |

**Previous:** [v1.01.00](IkigaiMasala_Final_v1.01.00_2026-05-11.md)  **Next:** [v1.02.00](IkigaiMasala_Final_v1.02.00_2026-07-21.md)
