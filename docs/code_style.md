> **Moved here, not deleted.** This arrived as a replacement for the
> repo-root `CLAUDE.md`, which holds this repository's 550-line navigation
> map. Overwriting that map looked unintended, so both are kept: the map is
> back at `CLAUDE.md` and this is here. Two things to note before adopting it
> — its placeholder block is still unfilled, and its "Project-specific"
> section describes a personal-health / cycle-tracking app rather than this
> menu planner. Delete this file, or move it back over `CLAUDE.md`, whichever
> you meant.

# Code style

<!--
REPLACE THIS COMMENT BLOCK with the full "Ponytail, lazy senior dev mode"
text — everything from "You are a lazy senior developer" through
"Trivial one-liners need no test."

Source: https://github.com/DietrichGebert/ponytail
Delete these lines once pasted.
-->

## Project-specific

This app stores personal health data. The rungs above do not apply to the
cycle-data schema, its storage layer, or any code that reads or writes it.
Use the explicit, well-tested, boring approach there even when a shorter
one exists.

Applies to:

- Database schema and migrations for cycle, symptom, and user data
- Any read or write path touching that data
- Authentication and session handling
- Local storage, sync, and backup logic

Everywhere else — UI, layout, charts, formatting, utilities, build config —
the rungs above apply normally.
