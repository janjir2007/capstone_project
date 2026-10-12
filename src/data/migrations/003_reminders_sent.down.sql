-- =====================================================================
-- Migration 003 DOWN — undo 003_reminders_sent.up.sql (Task 4.4)
--
-- WARNING: deletes the record of which reminders were sent. The due list
-- will show those vehicles again. Service records stay.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/003_reminders_sent.down.sql
-- =====================================================================

DROP TABLE reminders_sent;
