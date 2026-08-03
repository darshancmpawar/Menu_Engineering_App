"""Settings the data + domain layers need, with no dependency on an interface.

`api/config.py` looks like web configuration but is really *application*
configuration: ontology paths, city resolution, solver limits, the Supabase
timeout. Because it lives under `api/`, everything that needed one of those
values had to import from the web package — including `src/db.py`, which did it
with a lazy in-function import and a comment admitting the import cycle it was
dodging.

This module is where the settings that belong *below* the interfaces live. The
rule is one-way: `api/` and the Streamlit app may import from here, and this
module imports nothing from either. Values still come from the environment, so
behaviour is unchanged — what changes is that `src/` no longer reaches upward.

Credentials are read from the environment ONLY. `src/db.py` used to try
`streamlit.secrets` first and fall back to `os.environ`, which made the database
singleton depend on a UI framework. The Streamlit entrypoint now copies
`st.secrets` into the environment before anything touches the database, so a
`.streamlit/secrets.toml` deployment keeps working and the dependency points the
right way. See `app.py::_bridge_streamlit_secrets`.
"""

from __future__ import annotations

import os
from typing import Tuple

#: Bound the time we wait on a Supabase response. Without this the httpx client
#: used by supabase-py defaults to no timeout in some versions, which means a
#: slow / unhealthy Supabase pins a Flask thread indefinitely and eventually the
#: threadpool starves. 5 seconds covers normal operation (the slowest reads we
#: make are ~200ms) while still failing fast when something is genuinely wrong.
SUPABASE_TIMEOUT_SECONDS = float(os.getenv('SUPABASE_TIMEOUT_SECONDS', '5'))

#: Environment variables that must be set for any Supabase access.
SUPABASE_URL_ENV = 'SUPABASE_URL'
SUPABASE_KEY_ENV = 'SUPABASE_KEY'


def resolve_supabase_credentials() -> Tuple[str, str]:
    """Return ``(url, key)`` from the environment.

    Raises ``KeyError`` when unset, which is deliberate: a missing credential
    should fail loudly at first use rather than produce a client that 401s on
    every call.
    """
    return os.environ[SUPABASE_URL_ENV], os.environ[SUPABASE_KEY_ENV]
