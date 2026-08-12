-- =============================================================================
-- IKIGAI MASALA — MASTER SETUP + OPTIMIZE (idempotent, safe to re-run)
-- =============================================================================
-- One script that brings ANY database to the final, consolidated schema:
--   * fresh install                          → creates the 4 tables
--   * original DB (normalized config tables) → backfills clients.counters,
--                                               then drops the old tables
--   * earlier counter build (client_counters / counter_mode / counter_count)
--                                            → folds it in, then drops it
--
-- Run it in the Supabase SQL Editor (Dashboard > SQL Editor > New query).
--
-- FINAL SCHEMA (4 tables):
--   clients (name PK, version, counters JSONB, created_at)
--   app_settings (key PK, value JSONB)
--   menu_history / week_signatures (history + cooldown tracking)
--
-- The whole per-client config is ONE document — clients.counters:
--     [{name, categories, slot_counts, theme_map}, …]
--   counters[0] is the primary (what the menu solver plans from); extra
--   entries are additional cuisine stations. Mode is derived (single ⇔ 1
--   counter, multi ⇔ 2+). The old menu_categories / slot_count_overrides /
--   theme_overrides tables (premature normalization — every read/write hit
--   one client as a whole, never cross-client) are folded into this column.
-- =============================================================================

-- 1. Clients — the whole config lives in the counters JSONB column.
--    `city` is an optional client location (Bangalore / Pune / Chennai /
--    Hyderabad / NCR); NULL means unset.
CREATE TABLE IF NOT EXISTS clients (
    name               TEXT PRIMARY KEY,
    version            INT  NOT NULL DEFAULT 1,
    counters           JSONB NOT NULL DEFAULT '[]'::jsonb,
    city               TEXT,
    serve_weekends     BOOLEAN NOT NULL DEFAULT false,
    item_cooldown_days INT,
    source_pools       JSONB,
    working_days       JSONB,
    is_launch_site     BOOLEAN NOT NULL DEFAULT false,
    shared_categories  JSONB,
    created_at         TIMESTAMPTZ DEFAULT now()
);

-- 2. App-level settings (core_min_one_slots, constant_slots, fallback, etc.)
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT  PRIMARY KEY,
    value JSONB NOT NULL
);

-- 3. Menu history — one row per (client, date); the day's whole menu lives in
--    the `menu` JSONB column ({slot: item_base}). Item-level cooldowns explode
--    this in memory. (Was one row per dish — collapsed to one row per day.)
CREATE TABLE IF NOT EXISTS menu_history (
    client_name  TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    service_date DATE NOT NULL,
    menu         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (client_name, service_date)
);

-- 4. Week signatures — one row per saved week plan
CREATE TABLE IF NOT EXISTS week_signatures (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_name     TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    week_start      DATE NOT NULL,
    week_signature  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- MIGRATE existing databases into clients.counters
-- -----------------------------------------------------------------------------
ALTER TABLE clients ADD COLUMN IF NOT EXISTS version            INT   NOT NULL DEFAULT 1;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS counters           JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS city               TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS serve_weekends     BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS item_cooldown_days INT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS source_pools       JSONB;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS working_days       JSONB;
-- Launch sites (F: launch view). NOT NULL DEFAULT false means every client that
-- already exists becomes NON-launch the moment the column is added; only clients
-- configured through the launch view afterwards are flagged true.
ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_launch_site     BOOLEAN NOT NULL DEFAULT false;
-- Cross-counter common categories (editor toggle+multiselect). NULL = none;
-- the planner falls back to the file-based value in client_rules.json (DXC).
ALTER TABLE clients ADD COLUMN IF NOT EXISTS shared_categories  JSONB;

-- Seed working_days for kitchens that do not run a full Mon–Fri week.
UPDATE clients SET working_days = '["wednesday","thursday","friday"]'::jsonb
 WHERE name = 'Quince';
UPDATE clients SET working_days = '["monday","tuesday","thursday"]'::jsonb
 WHERE name = 'Piramel Finance';

-- -----------------------------------------------------------------------------
-- Attach clients to their own item pools.
--
-- `source_pools` lists the ontology `client`-column tokens a client draws on;
-- `common` is always implicit. NULL means "use the whole ontology", and an
-- empty array means "common only" — so a client left at '[]' silently runs on
-- the ~865 common items even when the ontology carries a pool named for it.
--
-- These three were in that state. The uplift in distinct eligible items is
-- large enough to change how varied their menus can be:
--
--   Cloudera   865 -> 1525   (veg_gravy 139->284, dessert 27->81, dal 37->88)
--   Infenion   865 -> 1326   (salad 25->74, starter 43->76, veg_dry 116->193)
--   Icon Blr   865 ->  968   (dessert 27->41, dal 37->48, salad 25->31)
--
-- Only applied where the value is still unset/empty, so a deliberate later
-- choice is never overwritten.
UPDATE clients SET source_pools = '["cloudera"]'::jsonb
 WHERE name = 'Cloudera'
   AND (source_pools IS NULL OR source_pools = '[]'::jsonb);

UPDATE clients SET source_pools = '["icon"]'::jsonb
 WHERE name = 'Icon Blr'
   AND (source_pools IS NULL OR source_pools = '[]'::jsonb);

-- NOTE: the `infineon` pool is also referenced by 'Plan View'. Pools are
-- shareable (a client's universe is common ∪ its tokens), so granting it here
-- takes nothing away from Plan View. Whether Plan View should keep it is a
-- separate question for whoever owns that account — this script does not touch
-- Plan View.
UPDATE clients SET source_pools = '["infineon"]'::jsonb
 WHERE name = 'Infenion'
   AND (source_pools IS NULL OR source_pools = '[]'::jsonb);

-- (a) Fold an older `client_counters` table (multi-cuisine build) into the
--     column: aggregate ALL of a client's rows, ordered by counter_index.
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
        ) sub
        WHERE sub.client_name = c.name
          AND (c.counters = '[]'::jsonb OR c.counters IS NULL);
    END IF;
END $$;

-- (b) Backfill the remaining (single-cuisine) clients from the normalized
--     config tables → a one-element counters list.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'menu_categories')
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'clients'
                     AND column_name = 'menu_category') THEN
        UPDATE clients c
        SET counters = jsonb_build_array(
            jsonb_build_object(
                'name', 'Counter 1',
                'categories', COALESCE(
                    (SELECT to_jsonb(mc.slots) FROM menu_categories mc WHERE mc.name = c.menu_category),
                    '[]'::jsonb),
                'slot_counts', COALESCE(
                    (SELECT jsonb_object_agg(s.slot, s.count)
                     FROM slot_count_overrides s WHERE s.client_name = c.name),
                    '{}'::jsonb),
                'theme_map', COALESCE(
                    (SELECT jsonb_object_agg(t.day, t.theme)
                     FROM theme_overrides t WHERE t.client_name = c.name),
                    '{}'::jsonb)
            )
        )
        WHERE (c.counters = '[]'::jsonb OR c.counters IS NULL)
          AND c.menu_category IS NOT NULL;
    END IF;
END $$;

-- (c) Drop the redundant tables + columns from any earlier build.
DROP TABLE IF EXISTS client_counters       CASCADE;
DROP TABLE IF EXISTS slot_count_overrides   CASCADE;
DROP TABLE IF EXISTS theme_overrides        CASCADE;
DROP TABLE IF EXISTS menu_categories        CASCADE;  -- CASCADE drops clients.menu_category FK
DROP TABLE IF EXISTS users                  CASCADE;  -- dead: auth feature was removed
ALTER TABLE clients DROP COLUMN IF EXISTS menu_category;
ALTER TABLE clients DROP COLUMN IF EXISTS counter_mode;
ALTER TABLE clients DROP COLUMN IF EXISTS counter_count;

-- (d) Reshape an OLD item-per-row menu_history into one JSONB row per day.
--     Aggregates each day's slots into a {slot: item_base} object, taking the
--     newest row per (client, date, slot). No-op on the new/fresh shape.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'menu_history'
                 AND column_name = 'item_base') THEN
        -- Clean any half-built table left by an earlier failed run so this
        -- block is safe to re-run.
        DROP TABLE IF EXISTS menu_history_new CASCADE;
        CREATE TABLE menu_history_new (
            client_name  TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
            service_date DATE NOT NULL,
            menu         JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (client_name, service_date)
        );
        -- Skip orphaned history (rows whose client_name is no longer in
        -- `clients` — e.g. a deleted client, or a name that never matched).
        -- They can't satisfy the FK and are dead data anyway.
        INSERT INTO menu_history_new (client_name, service_date, menu)
        SELECT client_name, service_date, jsonb_object_agg(slot, item_base)
        FROM (
            SELECT DISTINCT ON (client_name, service_date, slot)
                   client_name, service_date, slot, item_base
            FROM menu_history
            WHERE client_name IN (SELECT name FROM clients)
            ORDER BY client_name, service_date, slot, id DESC
        ) t
        GROUP BY client_name, service_date;
        DROP TABLE menu_history CASCADE;
        ALTER TABLE menu_history_new RENAME TO menu_history;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------
-- menu_history is keyed by its PK (client_name, service_date), which already
-- serves the "client + date range" cooldown query — no extra index needed.
CREATE INDEX IF NOT EXISTS idx_week_signatures_client_date
    ON week_signatures(client_name, week_start DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_week_signatures_unique
    ON week_signatures(client_name, week_start, week_signature);
-- (No index on clients.counters — it is never filtered on, so skipping it
--  saves storage and keeps writes cheap. Clients are looked up by PK.)

-- -----------------------------------------------------------------------------
-- Row Level Security + open policies (single-tenant app, anon key)
-- -----------------------------------------------------------------------------
ALTER TABLE clients          ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings     ENABLE ROW LEVEL SECURITY;
ALTER TABLE menu_history     ENABLE ROW LEVEL SECURITY;
ALTER TABLE week_signatures  ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on clients') THEN
        CREATE POLICY "Allow all on clients"        ON clients        FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on app_settings') THEN
        CREATE POLICY "Allow all on app_settings"   ON app_settings   FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on menu_history') THEN
        CREATE POLICY "Allow all on menu_history"   ON menu_history   FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on week_signatures') THEN
        CREATE POLICY "Allow all on week_signatures" ON week_signatures FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
    END IF;
END
$$;

-- -----------------------------------------------------------------------------
-- Optional sanity check (run separately):
--   SELECT name, counters FROM clients ORDER BY name;      -- 1+ counters each
--   SELECT to_regclass('public.menu_categories');          -- → NULL (gone)
--   SELECT to_regclass('public.slot_count_overrides');     -- → NULL (gone)
--   SELECT to_regclass('public.theme_overrides');          -- → NULL (gone)
-- -----------------------------------------------------------------------------
