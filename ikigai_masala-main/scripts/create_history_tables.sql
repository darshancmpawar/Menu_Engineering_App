-- =============================================================================
-- Supabase schema for menu history (cooldown & signature tracking)
-- Run this in the Supabase SQL Editor AFTER create_tables.sql.
-- Re-running is idempotent (every CREATE/ALTER guards against duplication).
-- =============================================================================

-- 1. Menu history — one row per (client, date); the day's whole menu lives in
--    the `menu` JSONB column ({slot: item_base}). The PK (client_name,
--    service_date) both enforces one-menu-per-day and serves the cooldown
--    "client + date range" query, so no extra index is needed.
-- (To migrate an OLD item-per-row menu_history, run scripts/setup_all.sql.)
CREATE TABLE IF NOT EXISTS menu_history (
    client_name  TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    service_date DATE NOT NULL,
    menu         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (client_name, service_date)
);

-- 2. Week signatures — one row per saved week plan
CREATE TABLE IF NOT EXISTS week_signatures (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_name     TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    week_start      DATE NOT NULL,
    week_signature  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Fast lookups: signature queries filter by client + date range
CREATE INDEX IF NOT EXISTS idx_week_signatures_client_date
    ON week_signatures(client_name, week_start DESC);

-- Prevent saving the exact same week twice
CREATE UNIQUE INDEX IF NOT EXISTS idx_week_signatures_unique
    ON week_signatures(client_name, week_start, week_signature);

-- =============================================================================
-- Row Level Security
-- =============================================================================
ALTER TABLE menu_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE week_signatures ENABLE ROW LEVEL SECURITY;

-- Idempotent policy creation — re-running this script must not fail.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on menu_history') THEN
        CREATE POLICY "Allow all on menu_history"
            ON menu_history FOR ALL
            TO anon, authenticated
            USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on week_signatures') THEN
        CREATE POLICY "Allow all on week_signatures"
            ON week_signatures FOR ALL
            TO anon, authenticated
            USING (true) WITH CHECK (true);
    END IF;
END
$$;
