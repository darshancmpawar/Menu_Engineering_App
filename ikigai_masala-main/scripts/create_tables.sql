-- =============================================================================
-- Supabase schema for Ikigai Masala client configuration
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New query)
--
-- NOTE: scripts/setup_all.sql is the master script — it creates every table
-- (this file + create_history_tables.sql) AND migrates older databases into
-- the consolidated shape in one run. Prefer it for anything but a brand-new
-- project. This file only covers the client-config tables.
-- =============================================================================

-- 1. Clients — the whole per-client config is one JSON document.
-- ``version`` is an optimistic-concurrency counter: GET /client-config returns
-- the current value; PUT must send it back and fails with 409 if another writer
-- bumped it in the meantime.
-- ``counters`` is the single source of truth for the cuisine setup — an
-- ordered, non-empty list ``[{name, categories, slot_counts, theme_map}, …]``.
-- counters[0] is the primary counter the solver plans from; extra entries are
-- additional stations. single ⇔ 1 counter, multi ⇔ 2+ (derived, no mode column).
CREATE TABLE IF NOT EXISTS clients (
    name        TEXT PRIMARY KEY,
    version     INT  NOT NULL DEFAULT 1,
    counters    JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT now()
);
-- Migrations for tables created before these columns existed. No-ops on fresh
-- installs. (To migrate an OLD normalized schema, run scripts/setup_all.sql.)
ALTER TABLE clients ADD COLUMN IF NOT EXISTS version  INT   NOT NULL DEFAULT 1;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS counters JSONB NOT NULL DEFAULT '[]'::jsonb;

-- 2. App-level settings (core_min_one_slots, constant_slots, fallback, etc.)
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT  PRIMARY KEY,
    value JSONB NOT NULL
);

-- Note: menu_history and week_signatures are defined in
-- create_history_tables.sql.

-- =============================================================================
-- Row Level Security (keep tables accessible via service/anon key)
-- =============================================================================
ALTER TABLE clients      ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;

-- Allow full access via the anon key (single-tenant app)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on clients') THEN
    CREATE POLICY "Allow all on clients"      ON clients      FOR ALL USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on app_settings') THEN
    CREATE POLICY "Allow all on app_settings" ON app_settings FOR ALL USING (true) WITH CHECK (true);
  END IF;
END
$$;
