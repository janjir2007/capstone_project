-- =====================================================================
-- Migration 004 DOWN — undo 004_destinations_name_mn_rest.up.sql (Task 6.1)
--
-- The two labels go back to NULL (the UI then shows the English name).
-- Remove the version row afterwards so scripts/migrate.py applies 004 again:
--   DELETE FROM schema_migrations WHERE version = '004';
-- =====================================================================

UPDATE destinations
SET name_mn = NULL
WHERE name IN ('Ulaanbaatar city (local work)', 'Other / several / unknown');
