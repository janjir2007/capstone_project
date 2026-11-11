-- =====================================================================
-- Migration 013 UP — manual payment status per service (Task 9.16b-2, plan docs/plans/9.16b_plan.md)
--
-- Artlab has no sales endpoint (D-139), so payment is marked by hand in our app (D-140).
-- Payment is always in full (PM 11-09): one service = at most one payment, so no payments table,
-- only columns on service_records:
--
-- price_mnt         whole tugrik, >= 0, NULL = no price entered («Нийт үнэ (₮)», optional).
--                   0 = nothing owed -> the service counts as «Төлсөн» (PM Q3).
-- paid_at           when «Төлсөн» was pressed; NULL = not paid. «Буцаах» clears it.
-- marked_unpaid_at  when «Авлага» was pressed (before the 24 h passed, or to correct a «Төлсөн»).
-- payment_tracked   false = the service was saved BEFORE this migration: it has no payment status at
--                   all (PM Q1), so old services do not all turn «Авлага» the day after deploy.
--                   Every service saved from now on gets true (column default).
--
-- The status itself is NOT stored: the API computes it when it reads a service
-- (src/api/payments.py manual_status; PAYMENT_DUE_HOURS, default 24). No timer.
-- The Artlab tables (008/009) are not touched.
--
-- Run (the runner provides the transaction):  python -m scripts.migrate
-- Undo: 013_service_payment.down.sql (loses every price and every click; take a backup first)
-- =====================================================================

ALTER TABLE service_records
    ADD COLUMN price_mnt        INTEGER     CHECK (price_mnt >= 0),
    ADD COLUMN paid_at          TIMESTAMPTZ,
    ADD COLUMN marked_unpaid_at TIMESTAMPTZ,
    -- Existing rows get false (added with this default) ...
    ADD COLUMN payment_tracked  BOOLEAN     NOT NULL DEFAULT false;

-- ... and every row inserted from now on gets true.
ALTER TABLE service_records ALTER COLUMN payment_tracked SET DEFAULT true;

-- GET /payments/receivables and the plate-screen check read only the not-paid tracked services.
CREATE INDEX service_records_not_paid_idx ON service_records (vehicle_id, created_at)
    WHERE payment_tracked AND paid_at IS NULL;
