-- =====================================================================
-- Migration 008 DOWN — undo 008_artlab.up.sql (Task 9.6b-2)
--
-- Drops the three Artlab tables. Nothing else points to them, and they hold only a copy of
-- Artlab data: the next sync after UP again fills them from Artlab.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/008_artlab.down.sql
-- =====================================================================

DROP TABLE artlab_bills;      -- first: it references artlab_transfers
DROP TABLE artlab_transfers;
DROP TABLE sync_runs;
