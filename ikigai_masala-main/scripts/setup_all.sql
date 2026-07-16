-- =============================================================================
-- IKIGAI MASALA — MASTER SETUP + OPTIMIZE (idempotent, safe to re-run)
-- =============================================================================
-- One script that brings ANY database to the final optimized schema:
--   * fresh install                         → creates every table
--   * original DB (pre cuisine-counters)    → adds clients.counters
--   * earlier build with client_counters    → backfills, then drops it
--
-- Run it in the Supabase SQL Editor (Dashboard > SQL Editor > New query).
-- It supersedes running create_tables.sql + create_history_tables.sql
-- separately, and folds in the cuisine-counter migration.
--
-- Cuisine counters are stored in ONE column, clients.counters (JSONB):
--   * single-cuisine client (every client today): counters = '[]'; the config
--     is read from the legacy menu_category / slot_count_overrides /
--     theme_overrides tables — no duplicated data.
--   * multi-cuisine client (future): counters holds the ordered list
--     [{name, categories, slot_counts, theme_map}, …]; the primary counter
--     (index 0) is also mirrored into the legacy tables so the solver keeps
--     working unchanged. single vs multi is derived (multi <=> counters <> '[]').
-- =============================================================================

-- 1. Menu categories — slot presets (menu_cat_1 … menu_cat_N)
CREATE TABLE IF NOT EXISTS menu_categories (
    name  TEXT PRIMARY KEY,
    slots TEXT[] NOT NULL
);

-- 2. Clients — references a menu category; `version` is the optimistic-
--    concurrency counter; `counters` (JSONB) holds the multi-cuisine config.
CREATE TABLE IF NOT EXISTS clients (
    name           TEXT PRIMARY KEY,
    menu_category  TEXT NOT NULL REFERENCES menu_categories(name),
    version        INT  NOT NULL DEFAULT 1,
    counters       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- 3. Slot count overrides — per-client, per-slot frequency (e.g. veg_dry x2)
CREATE TABLE IF NOT EXISTS slot_count_overrides (
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    slot        TEXT NOT NULL,
    count       INT  NOT NULL DEFAULT 1 CHECK (count >= 0),
    PRIMARY KEY (client_name, slot)
);

-- 4. Theme overrides — per-client day-to-theme mapping
CREATE TABLE IF NOT EXISTS theme_overrides (
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    day         TEXT NOT NULL CHECK (day IN ('monday','tuesday','wednesday','thursday','friday')),
    theme       TEXT NOT NULL CHECK (theme IN ('mix','chinese','biryani','south','north')),
    PRIMARY KEY (client_name, day)
);

-- 5. App-level settings (core_min_one_slots, constant_slots, fallback, etc.)
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT  PRIMARY KEY,
    value JSONB NOT NULL
);

-- 6. Menu history — one row per (client, date, slot, item) served
CREATE TABLE IF NOT EXISTS menu_history (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_name  TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    service_date DATE NOT NULL,
    slot         TEXT NOT NULL,
    item_base    TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- 7. Week signatures — one row per saved week plan
CREATE TABLE IF NOT EXISTS week_signatures (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_name     TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    week_start      DATE NOT NULL,
    week_signature  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- MIGRATE existing databases to the optimized shape
-- -----------------------------------------------------------------------------
-- Ensure the columns exist on a pre-existing `clients` table.
ALTER TABLE clients ADD COLUMN IF NOT EXISTS version  INT   NOT NULL DEFAULT 1;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS counters JSONB NOT NULL DEFAULT '[]'::jsonb;

-- If an older `client_counters` table exists, fold any genuinely-multi client
-- (2+ rows) into clients.counters, ordered by counter_index; single clients
-- stay '[]'. No-op when the table was never created / is empty.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'client_counters') THEN
        UPDATE clients c
        SET counters = sub.arr
        FROM (
            SELECT client_name,
                   jsonb_agg(
                       jsonb_build_object(
                           'name',        counter_name,
                           'categories',  categories,
                           'slot_counts', slot_counts,
                           'theme_map',   theme_map
                       ) ORDER BY counter_index
                   ) AS arr
            FROM client_counters
            GROUP BY client_name
            HAVING count(*) >= 2
        ) sub
        WHERE sub.client_name = c.name;
    END IF;
END $$;

-- Drop the redundant table + columns from any earlier build.
DROP TABLE IF EXISTS client_counters CASCADE;
ALTER TABLE clients DROP COLUMN IF EXISTS counter_mode;
ALTER TABLE clients DROP COLUMN IF EXISTS counter_count;

-- Drop the dead `users` table left over from the removed authentication
-- feature (no application code references it).
DROP TABLE IF EXISTS users CASCADE;

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_slot_overrides_client   ON slot_count_overrides(client_name);
CREATE INDEX IF NOT EXISTS idx_theme_overrides_client  ON theme_overrides(client_name);
CREATE INDEX IF NOT EXISTS idx_menu_history_client_date
    ON menu_history(client_name, service_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_menu_history_unique
    ON menu_history(client_name, service_date, slot, item_base);
CREATE INDEX IF NOT EXISTS idx_week_signatures_client_date
    ON week_signatures(client_name, week_start DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_week_signatures_unique
    ON week_signatures(client_name, week_start, week_signature);
-- (No index on clients.counters — it is never filtered on, so skipping it
--  saves storage and keeps writes cheap.)

-- -----------------------------------------------------------------------------
-- Row Level Security + open policies (single-tenant app, anon key)
-- -----------------------------------------------------------------------------
ALTER TABLE menu_categories      ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients              ENABLE ROW LEVEL SECURITY;
ALTER TABLE slot_count_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_overrides      ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE menu_history         ENABLE ROW LEVEL SECURITY;
ALTER TABLE week_signatures      ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on menu_categories') THEN
        CREATE POLICY "Allow all on menu_categories"      ON menu_categories      FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on clients') THEN
        CREATE POLICY "Allow all on clients"              ON clients              FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on slot_count_overrides') THEN
        CREATE POLICY "Allow all on slot_count_overrides" ON slot_count_overrides FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on theme_overrides') THEN
        CREATE POLICY "Allow all on theme_overrides"      ON theme_overrides      FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on app_settings') THEN
        CREATE POLICY "Allow all on app_settings"         ON app_settings         FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on menu_history') THEN
        CREATE POLICY "Allow all on menu_history"         ON menu_history         FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on week_signatures') THEN
        CREATE POLICY "Allow all on week_signatures"      ON week_signatures      FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
    END IF;
END
$$;

-- -----------------------------------------------------------------------------
-- Optional sanity check (safe to run separately):
--   SELECT name, counters FROM clients ORDER BY name;   -- existing clients → []
--   SELECT to_regclass('public.client_counters');       -- → NULL (table gone)
-- -----------------------------------------------------------------------------
