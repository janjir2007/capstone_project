-- =====================================================================
-- Migration 007 UP — one reminder per service + sent channel (Task 9.5c, D-119)
--
-- The 1m / 2m / 3m month stages (migration 006, D-113) are replaced by ONE
-- reminder, REMINDER_DAYS (default 75) after the truck's latest service.
--
-- 1. stage may now be 'single' (the 9.5c reminder). UNIQUE (service_id,
--    stage) from 006 stays, so there is at most one 'single' row per service.
--    Existing rows are NOT changed: old 1m / 2m / 3m rows and the prediction
--    rows (stage NULL) stay as history. The API counts any 1m / 2m / 3m row
--    of a service as "sent" for that service.
-- 2. channel: how the reminder went out. Every row so far was sent by hand
--    (Viber / copy-paste), so the default 'manual' is true for old rows too.
--    'sms' prepares an SMS sender later; nothing writes it yet.
--
-- The CHECK on stage was created inside ADD COLUMN in 006 without a name;
-- Postgres named it reminders_sent_stage_check (tests/test_reminders.py checks).
--
-- Run (the runner provides the transaction):  python -m scripts.migrate
-- Undo: 007_single_reminder.down.sql
-- =====================================================================

ALTER TABLE reminders_sent DROP CONSTRAINT reminders_sent_stage_check;
ALTER TABLE reminders_sent ADD CONSTRAINT reminders_sent_stage_check
    CHECK (stage IN ('1m', '2m', '3m', 'single'));

ALTER TABLE reminders_sent
    ADD COLUMN channel TEXT NOT NULL DEFAULT 'manual' CHECK (channel IN ('manual', 'sms'));
