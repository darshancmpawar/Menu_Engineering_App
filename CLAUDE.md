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
