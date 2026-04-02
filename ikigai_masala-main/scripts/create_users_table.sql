-- =============================================================================
-- Users table for Ikigai Masala authentication
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New query)
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    email          TEXT PRIMARY KEY,
    profile_name   TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('super_admin', 'admin', 'user')),
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Enable RLS with permissive policy (single-tenant app)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on users') THEN
    CREATE POLICY "Allow all on users" ON users FOR ALL USING (true) WITH CHECK (true);
  END IF;
END
$$;

-- =============================================================================
-- Seed default super_admin user
-- Login: Darshan.Pawar@thesmartq.com / Menu@123
-- =============================================================================
INSERT INTO users (email, profile_name, password_hash, role)
VALUES (
    'darshan.pawar@thesmartq.com',
    'Darshan',
    'ae0be011e63f13c5d5702a3a8b397379:e4568f3d5c655723b3b67b305933882b19975694b4502a05719860ef2e4af961',
    'super_admin'
)
ON CONFLICT (email) DO NOTHING;
