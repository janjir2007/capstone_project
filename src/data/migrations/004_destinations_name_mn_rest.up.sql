-- =====================================================================
-- Migration 004 UP — Mongolian labels for the last two destinations (Task 6.1)
--
-- Migration 002 labelled the 5 road destinations; 'Ulaanbaatar city (local
-- work)' and 'Other / several / unknown' stayed NULL until Ari gave their
-- text (PROJECT_STATE open question 5). Values from the 6.1 brief:
--   Ulaanbaatar city (local work) -> Улаанбаатар хот
--   Other / several / unknown     -> Бусад
-- After this every destination has a name_mn (the column stays nullable,
-- so new rows without a label are still allowed, contract v0.6).
--
-- Run after 002 (scripts/migrate.py applies it and records it in
-- schema_migrations; no BEGIN/COMMIT inside, the runner provides the transaction).
-- Undo: 004_destinations_name_mn_rest.down.sql
-- =====================================================================

UPDATE destinations AS d
SET name_mn = v.name_mn
FROM (VALUES
    ('Ulaanbaatar city (local work)', 'Улаанбаатар хот'),
    ('Other / several / unknown',     'Бусад')
) AS v (name, name_mn)
WHERE d.name = v.name;

-- Stop (and roll back) if a row above was not found, e.g. renamed by hand.
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM destinations
        WHERE name_mn IN ('Улаанбаатар хот', 'Бусад')) <> 2 THEN
        RAISE EXCEPTION 'migration 004: expected 2 destinations labelled, found %',
            (SELECT COUNT(*) FROM destinations WHERE name_mn IN ('Улаанбаатар хот', 'Бусад'));
    END IF;
END
$$;
