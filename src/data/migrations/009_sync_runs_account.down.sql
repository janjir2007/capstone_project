-- =====================================================================
-- Migration 009 DOWN — undo 009_sync_runs_account.up.sql (Task 9.6b-3)
--
-- Drops the column (and its index with it). Only per-account run counts are lost.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/009_sync_runs_account.down.sql
-- =====================================================================

ALTER TABLE sync_runs DROP COLUMN account_code;
