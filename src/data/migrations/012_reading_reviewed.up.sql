-- =====================================================================
-- Migration 012 UP — «Шалгах» list: a flagged reading can be marked checked (Task 9.15a-3)
--
-- odometer_readings.reviewed_at: when the oil changer tapped «Шалгасан» on a flagged Messenger
-- reading in «Сануулга» → «Шалгах». NULL = not checked yet (the list shows it). Only hides the row
-- from that list: the reading stays flagged and is still never used for the pace.
--
-- Note (plan 9.15a §0): task 9.2 (photos) also planned a "012"; whichever is built second renumbers.
--
-- Run (the runner provides the transaction):  python -m scripts.migrate
-- Undo: 012_reading_reviewed.down.sql
-- =====================================================================

ALTER TABLE odometer_readings ADD COLUMN reviewed_at TIMESTAMPTZ;
