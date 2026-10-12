-- =====================================================================
-- Migration 002 DOWN — undo 002_destinations_name_mn.up.sql (Task 1.1c)
--
-- Removes the Mongolian labels. Destinations and service records stay.
-- The API from contract v0.6 on reads name_mn: run this only together with
-- going back to an older API version.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/002_destinations_name_mn.down.sql
-- =====================================================================

-- Dropping the column also drops its CHECK and UNIQUE constraint.
ALTER TABLE destinations
    DROP COLUMN name_mn;
