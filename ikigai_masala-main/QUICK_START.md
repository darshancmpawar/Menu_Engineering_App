# Ikigai Masala - Quick Start Guide

## Prerequisites

- Python 3.10+
- Supabase project with tables created (see `scripts/create_tables.sql`)
- Streamlit secrets configured with `SUPABASE_URL` and `SUPABASE_KEY`

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
cd ikigai_masala-main
streamlit run app.py
```

This starts both the Streamlit frontend and an embedded Flask API backend on port 5000.

## First-Time Setup

1. **Create Supabase tables** -- Run `scripts/create_tables.sql` in the Supabase SQL Editor
2. **Seed client data** -- Run `scripts/seed_supabase.py` to migrate `clients.json` into Supabase
3. **Create history tables** -- Run `scripts/create_history_tables.sql` for menu history tracking
4. **Configure secrets** -- Add `SUPABASE_URL` and `SUPABASE_KEY` to Streamlit secrets

## Using the App

### Generate a Menu

1. Select a **Client** from the sidebar dropdown
2. Set the **Start date** and **Weekdays** count
3. Click **Generate Menu Plan**
4. View the generated menu with theme badges per day
5. **Download CSV** or **Save to History** for cooldown tracking

### Regenerate Cells

1. Expand the **Regenerate cells** section below the menu table
2. Select specific slots on specific days to replace
3. Click **Regenerate Selected**

### Customise Client Config

1. Click **Edit Logic** (top right) to open the Customisation Editor
2. Select or create a client
3. Configure: active slots, slot counts (e.g. veg_dry x2), day themes
4. Click **Save**

## Default Theme Schedule

| Day | Theme |
|-----|-------|
| Monday | Mix (South + North) |
| Tuesday | Chinese |
| Wednesday | Biryani |
| Thursday | South Indian |
| Friday | North Indian |

Themes are per-client overridable via the Theme Editor.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Cannot reach API" | Check that port 5000 is free; restart the app |
| Solver infeasibility | Check pool warnings; add more items to the Ontology for constrained slots |
| "No clients found" | Run `scripts/seed_supabase.py` to populate Supabase |
| Missing dependencies | `pip install -r requirements.txt` |

## Project Structure

```
ikigai_masala-main/
  app.py                  # Streamlit frontend entry point
  api/app.py              # Flask API backend
  api/config.py           # Path and limit constants
  src/solver/             # CP-SAT menu solver
  src/menu_rules/         # 19 constraint rules
  src/preprocessor/       # Excel reader, pool builder
  src/client/             # Supabase-backed client config
  src/history/            # CSV-based history manager
  customisation/          # Streamlit editor UI modules
  ui/                     # API client + formatters
  data/raw/               # menu_items.xlsx (530+ items)
  data/configs/           # indian_menu_rules.json, clients.json
  scripts/                # SQL schemas + Supabase seeding
  tests/                  # Pytest test suite
```
