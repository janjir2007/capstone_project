-- =====================================================================
-- Migration 007 DOWN — undo 007_single_reminder.up.sql (Task 9.5c)
--
-- No row is deleted: every 'single' row becomes '3m' (the 9.5b stage closest
-- to it, so the 9.5b code also sees that service as reminded). The channel
-- column is dropped (until 9.5c every reminder was 'manual' anyway).
--
-- A service never has both a 'single' and an old stage row (the API refuses
-- to add 'single' then), so the UPDATE cannot break UNIQUE (service_id,
-- stage). If someone made one by hand, the UPDATE fails and nothing changes.
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/007_single_reminder.down.sql
-- =====================================================================

ALTER TABLE reminders_sent DROP COLUMN channel;

ALTER TABLE reminders_sent DROP CONSTRAINT reminders_sent_stage_check;
UPDATE reminders_sent SET stage = '3m' WHERE stage = 'single';
ALTER TABLE reminders_sent ADD CONSTRAINT reminders_sent_stage_check CHECK (stage IN ('1m', '2m', '3m'));
