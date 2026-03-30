-- =============================================================================
-- Supabase schema for Ikigai Masala client configuration
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New query)
-- =============================================================================

-- 1. Menu categories — the slot presets (menu_cat_1 … menu_cat_N)
CREATE TABLE menu_categories (
    name  TEXT PRIMARY KEY,
    slots TEXT[] NOT NULL
);

-- 2. Clients — each client references a menu category
CREATE TABLE clients (
    name           TEXT PRIMARY KEY,
    menu_category  TEXT NOT NULL REFERENCES menu_categories(name),
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- 3. Slot count overrides — e.g. Rippling gets veg_dry x2
CREATE TABLE slot_count_overrides (
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    slot        TEXT NOT NULL,
    count       INT  NOT NULL DEFAULT 1 CHECK (count >= 0),
    PRIMARY KEY (client_name, slot)
);

-- 4. Theme overrides — per-client day-to-theme mapping
CREATE TABLE theme_overrides (
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    day         TEXT NOT NULL CHECK (day IN ('monday','tuesday','wednesday','thursday','friday')),
    theme       TEXT NOT NULL CHECK (theme IN ('mix','chinese','biryani','south','north')),
    PRIMARY KEY (client_name, day)
);

-- 5. App-level settings (core_min_one_slots, constant_slots, fallback, etc.)
CREATE TABLE app_settings (
    key   TEXT  PRIMARY KEY,
    value JSONB NOT NULL
);

-- Indexes for fast lookups
CREATE INDEX idx_slot_overrides_client ON slot_count_overrides(client_name);
CREATE INDEX idx_theme_overrides_client ON theme_overrides(client_name);

-- =============================================================================
-- Enable Row Level Security (keep tables accessible via service/anon key)
-- =============================================================================
ALTER TABLE menu_categories     ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients             ENABLE ROW LEVEL SECURITY;
ALTER TABLE slot_count_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_overrides     ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings        ENABLE ROW LEVEL SECURITY;

-- Allow full access via the anon key (single-tenant app)
CREATE POLICY "Allow all on menu_categories"     ON menu_categories     FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on clients"             ON clients             FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on slot_count_overrides" ON slot_count_overrides FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on theme_overrides"     ON theme_overrides     FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on app_settings"        ON app_settings        FOR ALL USING (true) WITH CHECK (true);
