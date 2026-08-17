-- Backfill `clients.city` for rows that predate the per-city ontology.
--
-- Five live clients (Moengage, Odessia, Rippling, Stripe, Stryker) carry
-- `city = NULL` because they were created before the column existed. A null
-- city is NOT harmless:
--
--   * `city_excel_path(None)` falls back to bangalore.xlsx and
--     `MenuRuleLoader.load_for_city(None)` falls back to DEFAULT_CITY, so the
--     menus look right — which is exactly why this went unnoticed.
--   * but `FULL_POOL_CITIES` is matched on the NORMALISED city string, and
--     `normalize_city(None)` returns None. So a null-city client is excluded
--     from the Bangalore full-pool switch and still plans from `common` only
--     (893 of 4,349 rows) while every other Bangalore client draws on all of
--     them.
--   * the planner's City filter and the editor's city picker both list cities
--     found on client rows, so a null-city client is unreachable through them.
--
-- Run in the Supabase SQL editor. Idempotent: re-running matches no rows.

-- 1. Look before you write — confirm these are the rows you expect.
SELECT name, city, source_pools, is_launch_site
FROM   public.clients
WHERE  city IS NULL OR btrim(city) = '';

-- 2. Backfill. Every existing null-city client is a Bangalore site; adjust the
--    WHERE clause if that stops being true.
UPDATE public.clients
SET    city = 'Bangalore'
WHERE  city IS NULL OR btrim(city) = '';

-- 3. Verify: this must come back empty, and the Bangalore count must have gone
--    up by exactly the number of rows step 1 listed.
SELECT name FROM public.clients WHERE city IS NULL OR btrim(city) = '';
SELECT city, count(*) FROM public.clients GROUP BY city ORDER BY city;

-- Note on `version`: this deliberately does NOT bump it. `version` guards the
-- app's own optimistic-concurrency writes (`update_client_atomic`); bumping it
-- out of band would make an editor session that read the row mid-migration fail
-- its next save with a stale-version error for no reason. `city` is not part of
-- any in-flight edit here.
