# Setup

Everything you need to get from a fresh clone to a running planner. The
[README quick start](../README.md#quick-start) is the 30-second version;
this file has the full story.

---

## 1. Prerequisites

- Python 3.10+
- A Supabase project (URL + service-role key)
- The schema applied once (see [Supabase schema](#3-supabase-schema))
- Secrets: `SUPABASE_URL`, `SUPABASE_KEY`

---

## 2. Install

```bash
cd ikigai_masala-main
pip install -r requirements-dev.txt   # runtime + pytest + ruff + bandit
# or `-r requirements.txt` for runtime only (prod containers)
```

---

## 3. Supabase schema

The whole schema is **four tables**: `clients`, `app_settings`, `menu_history`,
`week_signatures`. A client's entire cuisine config is one JSON document in
`clients.counters` (plus a `city` column); menu history is one JSON row per
`(client, service_date)`.

In the Supabase SQL editor, run the master script once. It's idempotent
(`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`) and also migrates an
older normalized database (folds the legacy `menu_categories` /
`slot_count_overrides` / `theme_overrides` tables into `clients.counters` and
reshapes the old per-dish `menu_history`):

```
scripts/setup_all.sql   master schema + migrations (supersedes the two files below)
```

For a brand-new database you can instead run the two component files
(same result, no migration steps):

```
scripts/create_tables.sql          clients, app_settings
scripts/create_history_tables.sql  menu_history, week_signatures
```

---

## 4. Secrets

The app reads secrets from `.streamlit/secrets.toml` locally (or the Secrets
panel on Streamlit Cloud). Both values are required; the API fails at
startup if either is missing.

```toml
SUPABASE_URL = "https://<your-project-ref>.supabase.co"
SUPABASE_KEY = "<service_role / sb_secret_... key — NOT publishable>"
```

### Key-class notes

- **`SUPABASE_KEY` must be the service-role key** (`sb_secret_...` or the
  legacy JWT `eyJ...`). The publishable / anon key obeys RLS and will block
  the backend from writing history.
- Never commit the secret. Rotate immediately if it leaks.

### Optional env vars

```toml
APP_TIMEZONE             = "Asia/Kolkata"   # default; any IANA name
LOG_FORMAT               = "json"           # structured logs for prod
LOG_LEVEL                = "INFO"
APP_VERSION              = "$(git rev-parse --short HEAD)"   # surfaced in /health + /
SUPABASE_TIMEOUT_SECONDS = "5"              # bound on every Supabase read/write; default 5s
CORS_ALLOWED_ORIGINS     = "https://prod.example.com"   # comma-separated; defaults to loopback only
API_HOST                 = "127.0.0.1"      # loopback. Containers / prod may want 0.0.0.0
API_PORT                 = "5000"
```

`APP_TIMEZONE` decides what "today" means when the client doesn't pass an
explicit `start_date`. Change it if the kitchens you're planning for operate
in another zone — otherwise a container running in UTC will drift cooldown
windows and weekday themes by up to a day.

---

## 5. Seed data

```bash
export SUPABASE_URL=...
export SUPABASE_KEY=...

python scripts/seed_supabase.py   # migrate data/configs/clients.json into Supabase
```

---

## 6. Run

```bash
streamlit run app.py
```

The Streamlit process auto-spawns the Flask API in a daemon thread on
`http://localhost:5000`. Both talk to the same Supabase project.

To run the API standalone (e.g. under gunicorn):

```bash
flask --app api.app run              # or python -m api.app
```

---

## 7. Docker

A single-process container (Streamlit on `:8501`, auto-spawned Flask on
loopback `:5000`) lives at the repo root.

```bash
cp .env.example .env       # fill in real SUPABASE_URL / SUPABASE_KEY
docker compose up --build  # → http://localhost:8501
```

The container:

- Runs as non-root (`uid 10001`) — defence-in-depth.
- Uses `tini` as PID 1 so `docker stop` / Ctrl-C are clean.
- Exposes only `8501`. Flask is *not* published — the Streamlit
  frontend talks to it over loopback inside the container.
- Has a `HEALTHCHECK` against `/api/v1/health` so `docker compose ps`
  shows `healthy`/`unhealthy` correctly. Set `APP_VERSION` in `.env` to
  the build SHA so `/health` and `/` surface what's running.

The schema migrations and the client seed still need a one-time run
against Supabase from your laptop (sections 3 + 5 above) — they're
deliberately out of the container so a forgotten `docker run` can't
mutate the database.
