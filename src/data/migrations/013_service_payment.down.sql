-- =====================================================================
-- Migration 013 DOWN — undo 013_service_payment.up.sql (Task 9.16b-2)
--
-- Drops the payment columns of service_records. Every price and every «Төлсөн» / «Авлага» click is
-- LOST (take a backup first: systemctl start ocp-backup.service). No service row is deleted.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/013_service_payment.down.sql
-- =====================================================================

DROP INDEX service_records_not_paid_idx;

ALTER TABLE service_records
    DROP COLUMN payment_tracked,
    DROP COLUMN marked_unpaid_at,
    DROP COLUMN paid_at,
    DROP COLUMN price_mnt;
