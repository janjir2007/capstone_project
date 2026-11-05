-- =====================================================================
-- Migration 012 DOWN — undo 012_reading_reviewed.up.sql (Task 9.15a-3)
--
-- Drops odometer_readings.reviewed_at: every flagged Messenger reading shows in «Шалгах» again.
-- No reading is deleted.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/012_reading_reviewed.down.sql
-- =====================================================================

ALTER TABLE odometer_readings DROP COLUMN reviewed_at;
