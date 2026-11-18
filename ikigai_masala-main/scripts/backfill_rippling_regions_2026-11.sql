-- Rippling's regional days for 2-13 Nov 2026, from "weekly menu - 2nd to 13th nov.xlsx"
-- (owner, 18 Nov), so the reopened weeks show them in the day header. Lunch and
-- dinner rows of each date. Names are the planner's own regions (the sheet's
-- "Italian" day is Continental, the region the planner offers). Safe to run twice.
BEGIN;
ALTER TABLE menu_history ADD COLUMN IF NOT EXISTS region TEXT;
UPDATE menu_history SET region = 'Karnataka'    WHERE client_name = 'Rippling' AND service_date = '2026-11-02';
UPDATE menu_history SET region = 'Continental'  WHERE client_name = 'Rippling' AND service_date = '2026-11-05';  -- sheet: Italian
UPDATE menu_history SET region = 'Tamil Nadu'   WHERE client_name = 'Rippling' AND service_date = '2026-11-09';
UPDATE menu_history SET region = 'Indo-Chinese' WHERE client_name = 'Rippling' AND service_date = '2026-11-12';
COMMIT;
