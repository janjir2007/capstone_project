-- =====================================================================
-- Migration 006 DOWN — undo 006_reminder_stages.up.sql (Task 9.5b)
--
-- WARNING: deletes every month-stage "sent" row (they have no prediction, so
-- they cannot satisfy the old NOT NULL columns) and the list of phones that
-- asked to stop. Old prediction rows and service records stay.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/006_reminder_stages.down.sql
-- =====================================================================

DROP TABLE reminder_stops;

DELETE FROM reminders_sent WHERE stage IS NOT NULL;
ALTER TABLE reminders_sent DROP CONSTRAINT reminders_sent_one_per_stage_uq;
ALTER TABLE reminders_sent ADD CONSTRAINT reminders_sent_one_per_service_uq UNIQUE (service_id);
ALTER TABLE reminders_sent
    DROP CONSTRAINT reminders_sent_stage_or_prediction_ck,
    ALTER COLUMN method SET NOT NULL,
    ALTER COLUMN model_version SET NOT NULL,
    ALTER COLUMN predicted_date SET NOT NULL,
    DROP COLUMN stage;
