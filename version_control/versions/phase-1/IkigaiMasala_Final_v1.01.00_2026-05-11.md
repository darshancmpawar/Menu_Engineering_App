# Version 1.01.00: Production readiness

**Phase:** 1 Simple tool  **Date:** 22 Apr – 11 May 2026  **Status:** Final

## In one line

The tool became something that could be run in production: watched, protected
from clashing edits, able to replay a saved week, and able to say why a menu
could not be generated.

## Why this version was needed

The planner worked, but nothing around it did. There was no automatic check on
changes before they shipped. When something failed there was no way to connect
a user's report to a line in a log. Two people editing the same site's setup
silently overwrote each other. And when a menu could not be generated, the
screen said only that no plan was found, after a three-minute wait.

## What's new

### 1. Every change is checked before it ships

Each proposed change now runs the test suite, a narrow correctness check and a
security scan, in parallel. The correctness check was deliberately kept narrow
— real faults like unused imports and undefined names — rather than styling,
which would have buried the signal. The first clean pass removed 29 dead
imports across 13 files.

### 2. Logs that can be followed across a request

Every request is given a short identifier that is stamped on every log line it
produces and returned in the response. When somebody reports that a generation
failed at 11:40, that request can be found and followed across the planner, the
solver and the history layer.

The health check went from reporting "alive" to reporting the version running,
how long it has been up, whether the database is reachable and what the solve
queue is doing. An uptime probe can now tell the difference between a process
that is running and one that can actually serve.

### 3. Two people can no longer overwrite each other

Site setups carry a version number that a writer must send back when saving. If
somebody else has saved in the meantime, the write is refused and the screen is
told the current version instead of quietly discarding the other person's work.

### 4. One user cannot starve the others

The solver already limited how many menus it would build at once. Nothing
stopped a single user from occupying all of that capacity by generating
repeatedly. Requests are now limited per user — ten generations a minute,
twenty regenerations — and a request that is turned away says when to try
again, which the screen handles by retrying quietly.

### 5. Saving overwrites, and Generate replays what was saved

Saving a week again used to leave both versions in the record, so the rules that
read history saw two different answers for the same day. Saving now replaces the
previous version of those dates.

Generate now checks for a saved plan first. If those dates have already been
saved, it shows the saved menu with a "Loaded from history" badge rather than
producing a different one. Pressing Generate for a week that is already agreed
no longer risks changing it.

### 6. When a menu cannot be built, the screen says why

Instead of a generic failure after a long wait, each rule can now examine the
dish lists and the history and report what is wrong before the solver runs. The
clearest example: a case where the Chinese starters had all been served too
recently used to wait three minutes and then fail without explanation. It is now
reported in under a second, naming the slot that has nothing left to offer.

## What this means for day-to-day use

A planner who cannot generate a menu is told which category ran out, and can
fix it. A planner who regenerates a week that was already agreed gets the agreed
menu back. And two account managers can work on different sites, or the same
one, without losing each other's changes.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 1.01.00 | 22 Apr–11 May | Darshan + Claude Code | **Production readiness.** (1) CI with coverage gate. (2) Observability: structured logging, /health, /metrics, rate limits, optimistic concurrency on config writes. (3) Saved plans: overwrite-on-save, replay saved plan. (4) Pre-flight diagnostics explaining failed plans |

**Previous:** [v1.00.02](IkigaiMasala_Final_v1.00.02_2026-04-17.md)  **Next:** [v1.01.01](IkigaiMasala_Final_v1.01.01_2026-04-30.md)
