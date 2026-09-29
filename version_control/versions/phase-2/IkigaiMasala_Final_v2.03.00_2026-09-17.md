# Version 2.03.00: The Explainer

**Phase:** 2 Scaling  **Date:** 4–17 Sep 2026  **Status:** Final

## In one line

Every generated day now comes with a short written account of why those dishes
go together, and says so plainly when something on the plate is missing.

## Why this version was needed

The planner produced a menu and nothing else. A manager looking at Thursday
could see six dishes but had no way of knowing whether the plate worked, or
why the system had chosen it. If a rule could not be met, the menu came back
looking exactly like one where every rule held — the software wrote a line to
a log file nobody reads and carried on. A menu that quietly gave up on a rule
was indistinguishable from a menu that satisfied it.

## What's new

### 1. Six plate checks, decided offline

Six judgements are made about each day by ordinary program logic, with no
outside service involved: colour variety, texture contrast, richness balance,
the spice arc, whether the plate echoes its own main ingredient, and whether
the pairings hold. They run on the site's own dish data.

This matters for trust. Because every judgement is made offline first, nothing
downstream can invent a figure. If the plate has four colours, "four colours"
is a measured fact before any sentence is written about it.

### 2. Calibrated against 49 real menu days — which found three faulty checks

The six checks were scored against 49 real days from 10 clients across all four
cities before anyone was asked to trust them. That measurement found problems
in three of them.

Two checks could never fail. One passes when a day has two or more spice
levels; across 49 days the lowest seen was two. Another passes when richness
sits in a middle band; every observed day was already inside it. A check that
always prints "ok" teaches the reader to skim the list, which costs the checks
that do carry information.

A third demanded four colours when the planner itself had been asked for fewer,
so it was reporting failures on days that had done exactly what was asked.

### 3. When a rule is relaxed, the explanation says so

Sixteen places in the rule engine deliberately bend rather than fail — a weekly
minimum lowered because the dish list cannot supply it, a themed restriction
skipped because the slot would otherwise be empty, a pairing dropped for want
of a free slot. Each of these is the right behaviour, and each used to announce
itself only to a log.

Every one of those sites now stamps the explanation with the name of the rule
that gave way. If a site asked for kofta once a week and the dishes had all
been served too recently, the explanation says that, instead of showing a menu
that looks fully compliant.

### 4. Written prose, and it is not allowed to flatter

An optional layer turns the evidence into prose. Two guards sit on it. The
first discards any number or dish name that is not in the underlying evidence,
so nothing can be invented. The second was added later and matters more: a
reply that stays silent about a failing check, a missing pairing or a relaxed
rule is rejected. The easiest paragraph to write is the flattering one, and
telling the system not to flatter was not enough on its own — now it is
enforced, and a rejected reply falls back to the plain bulleted version, which
leads with problems.

### 5. An overview of the meal, not a rule report

The panel now opens with a short paragraph about the food:

> Thursday is a north menu of 6 main dishes. Gobi 65 is very hot — boondi raita
> cools it. Paneer butter masala is rich at 4 of 5 — plain chapati at 1 cuts
> through it. Aloo jeera is dry against dal tadka in sauce.

That is built from the pairings, not the checks, because a pairing is already a
statement about two dishes with a reason, while a check scores the plate as a
set and leaves the reader to work out what "four colours across seven dishes"
means for lunch. It is written by ordinary logic, not by a model.

A gap is named last and never dropped to make room for praise — "Missing: gobi
65 is very hot and there is no curd or raita on the plate" — because that is
the one thing on the page a kitchen can fix this morning. The itemised plate,
the per-line pairings and the six verdicts stay below it as the working.

## What this means for day-to-day use

A planner opens "Why this menu" under any day and reads four or five sentences
about the food. If something is missing or a rule had to give way, it is in
that paragraph in the same plain voice. Nothing has to be turned on: the
written summary is the product, and the prose layer is an optional extra on
top.

## Known limits

Checks that are not yet calibrated are carried in the response for whoever is
measuring them, but the prose is not required to mention them — repeating a
verdict that is not yet trusted would work against the honesty the rest of this
is built on.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.03.00 | 4–17 Sep | Darshan + Claude Code | **Explainer.** (1) Deterministic plate checks, calibrated against 49 real menu days. (2) Solver relaxations routed into the explanation; `/explain` endpoint. (3) LLM layer with cache, made to disagree when warranted rather than agree. (4) Reframed as an overview of the meal, not a rule report; stepped explain UI |

**Previous:** [v2.02.00](IkigaiMasala_Final_v2.02.00_2026-09-09.md)  **Next:** [v2.04.00](IkigaiMasala_Final_v2.04.00_2026-09-21.md)
