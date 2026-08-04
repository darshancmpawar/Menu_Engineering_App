"""The logger name application-layer warnings are emitted under.

Moving code out of `api/app.py` silently changed where its warnings appear to come
from: a constant-pin typo used to be logged by `api.app` and started being logged
by `src.application.constant_items`. Nothing broke functionally, but log records
are observable output — anything filtering or alerting on `api.app` stopped
matching those warnings, and three tests that captured by that name failed while a
fourth started passing vacuously.

So the emitting name is pinned here rather than derived from `__name__`. Operators
keep one name to filter on across refactors, and moving a function between modules
can no longer change what shows up in a log query.

This is a plain string. `src/` still imports nothing from `api/` — the constant
happens to spell an interface name because that is the name already in use in
deployed log filters, and continuity is the whole point. Renaming it is a
breaking change for anyone's alerting, so treat it as one.

Modules whose logs are purely internal (the ontology repository's cache
bookkeeping, say) should keep `logging.getLogger(__name__)`; this is for the
warnings an operator is expected to act on.
"""

from __future__ import annotations

#: Emitting name for operator-facing application warnings. Deliberately stable
#: across module moves — see the module docstring.
APP_LOGGER_NAME = 'api.app'
