-- =====================================================================
-- Migration 009 UP — sync_runs.account_code (Task 9.6b-3)
--
-- The acc-txn sync writes ONE sync_runs row per bank account per run, so it can warn when an
-- account returned 0 rows N runs in a row (a wrong account code also returns 200 + an empty
-- list: docs/artlab_api_notes.md §8c). Bill and nightly runs leave account_code NULL.
--
-- Run (the runner provides the transaction):  python -m scripts.migrate
-- Undo: 009_sync_runs_account.down.sql
-- =====================================================================

ALTER TABLE sync_runs
    ADD COLUMN account_code TEXT CHECK (account_code ~ '^[0-9]{1,20}$');

CREATE INDEX sync_runs_account_started_idx ON sync_runs (account_code, started_at DESC)
    WHERE account_code IS NOT NULL;
