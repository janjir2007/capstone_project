-- =====================================================================
-- Migration 011 DOWN — undo 011_messenger.up.sql (Task 9.15a-2)
--
-- LOSES DATA on purpose, so the old CHECKs can come back:
--   - readings flagged 'plate_mismatch' (Messenger readings whose plate did not match the link)
--   - reminders sent with channel 'messenger' (One-Time Notification)
-- Other Messenger readings (source 'messenger', allowed since 010) are KEPT.
-- Then the 5 messenger tables are dropped (PSID links, refs, pending questions, seen ids, OTN tokens).
--
-- Run (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/011_messenger.down.sql
-- =====================================================================

DELETE FROM odometer_readings WHERE flag_reason = 'plate_mismatch';
DELETE FROM reminders_sent WHERE channel = 'messenger';

ALTER TABLE odometer_readings DROP CONSTRAINT odometer_readings_flag_reason_check;
ALTER TABLE odometer_readings ADD CONSTRAINT odometer_readings_flag_reason_check
    CHECK (flag_reason IN ('not_higher', 'too_slow', 'too_fast'));

ALTER TABLE reminders_sent DROP CONSTRAINT reminders_sent_channel_check;
ALTER TABLE reminders_sent ADD CONSTRAINT reminders_sent_channel_check
    CHECK (channel IN ('manual', 'sms'));

DROP TABLE messenger_otn;
DROP TABLE messenger_seen;
DROP TABLE messenger_pending;
DROP TABLE messenger_links;
DROP TABLE messenger_refs;
