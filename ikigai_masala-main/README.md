# Ikigai Masala

Constraint-based weekly menu planner for corporate meal providers. Generates
Indian menus that respect cuisine themes, item cooldowns, color variety,
per-client customizations, and history.

- **Frontend:** Streamlit
- **Backend:** Flask API (auto-started by Streamlit on port 5000)
- **Solver:** Google OR-Tools CP-SAT
- **Database:** Supabase (PostgreSQL) — clients, history, config

---

## Quick start

> First-time setup: run `scripts/setup_all.sql` once in the Supabase SQL
> editor (the master idempotent schema) — see [docs/setup.md](docs/setup.md).

```bash
cd ikigai_masala-main
pip install -r requirements-dev.txt

# one-time in the Supabase SQL editor:
#   scripts/setup_all.sql   (master schema + migrations, idempotent)

cat > .streamlit/secrets.toml <<EOF
SUPABASE_URL = "https://<your-project>.supabase.co"
SUPABASE_KEY = "<service_role key>"
EOF

streamlit run app.py
```

---

## Documentation

- [docs/setup.md](docs/setup.md) — prerequisites, install, secrets, seed,
  every env var the app reads.
- [docs/architecture.md](docs/architecture.md) — system diagram, layer
  overview, design choices, plan / save / regenerate sequence diagrams.
- [docs/api.md](docs/api.md) — endpoint table, response shapes (plan,
  health, metrics), concurrency semantics, rules reference, data model,
  output formats.
- [docs/operations.md](docs/operations.md) — testing, CI, structured
  logs + metrics, troubleshooting table, project layout.

For a file-level symbol map optimised for Claude Code sessions, see
[`../CLAUDE.md`](../CLAUDE.md).

---

## Tests

```bash
pytest                # default (skips @slow)
pytest -m slow        # real-Excel full-pipeline tests
```

CI runs pytest + `ruff check --select=F,E9` + `bandit -ll` on every PR;
the slow suite runs on push-to-main and manual dispatch. See
[docs/operations.md](docs/operations.md#ci).
