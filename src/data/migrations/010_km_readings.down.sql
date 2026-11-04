-- =====================================================================
-- Migration 010 DOWN — undo 010_km_readings.up.sql (Task 9.14a)
--
-- Drops km_checks and odometer_readings (driver readings and the km-check log are lost) and the
-- stored interval / target km of every service (the API before 9.14a computes the target when
-- shown). No other row is changed.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/010_km_readings.down.sql
-- =====================================================================

DROP TABLE km_checks;
DROP TABLE odometer_readings;

ALTER TABLE service_records
    DROP CONSTRAINT service_records_target_km_check,
    DROP COLUMN target_km,
    DROP COLUMN interval_km;
