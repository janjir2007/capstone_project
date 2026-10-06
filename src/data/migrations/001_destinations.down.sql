-- =====================================================================
-- Migration 001 DOWN — undo 001_destinations.up.sql (Task 1.1b)
--
-- WARNING: deletes every stored destination (the destinations table and
-- the destination_id / destination_raw values on service records).
-- All other service record data stays.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/001_destinations.down.sql
-- =====================================================================

-- Columns first: destination_id references destinations.
-- Dropping a column also drops its index, FK and CHECK.
ALTER TABLE service_records
    DROP COLUMN destination_raw,
    DROP COLUMN destination_id;

DROP TABLE destinations;
