-- =====================================================================
-- Migration 006 UP — month-based reminder stages + "stop" phones (Task 9.5b)
--
-- Reminders are no longer timed by the ML prediction (D-036): the due list
-- shows a truck 30 / 60 / 90 days after its latest service (stages 1m / 2m /
-- 3m), only the highest stage reached, each stage once per service.
--
-- 1. reminders_sent.stage: which month message went out. One row per
--    (service, stage): UNIQUE (service_id, stage) replaces UNIQUE (service_id).
--    A new service = a new service_id, so stages start again automatically.
-- 2. method / model_version / predicted_date become optional: month rows have
--    no prediction. Old rows (stage NULL) keep their values unchanged; every
--    row is either a month row (stage) or an old prediction row (method).
-- 3. reminder_stops: driver phones that asked for no more messages.
--
-- Run (the runner provides the transaction):  python -m scripts.migrate
-- Undo: 006_reminder_stages.down.sql
-- =====================================================================

ALTER TABLE reminders_sent
    ADD COLUMN stage TEXT CHECK (stage IN ('1m', '2m', '3m')),
    ALTER COLUMN method DROP NOT NULL,
    ALTER COLUMN model_version DROP NOT NULL,
    ALTER COLUMN predicted_date DROP NOT NULL,
    ADD CONSTRAINT reminders_sent_stage_or_prediction_ck CHECK (stage IS NOT NULL OR method IS NOT NULL);

ALTER TABLE reminders_sent DROP CONSTRAINT reminders_sent_one_per_service_uq;
-- Marking the same stage twice must not create a second row (POST /reminders/{id}/sent is idempotent).
ALTER TABLE reminders_sent ADD CONSTRAINT reminders_sent_one_per_stage_uq UNIQUE (service_id, stage);

-- A driver said "stop": no reminder goes to this phone any more (whatever truck he drives).
CREATE TABLE reminder_stops (
    phone       TEXT        PRIMARY KEY CHECK (phone ~ '^[0-9]{8}$'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
