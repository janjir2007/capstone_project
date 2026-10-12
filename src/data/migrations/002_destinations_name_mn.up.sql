-- =====================================================================
-- Migration 002 UP — destinations.name_mn (Task 1.1c, D-040)
--
-- Adds the Mongolian label of each destination. The oil changer's UI is
-- Mongolian; the English `name` stays as the key (the model's route table
-- and the generator use it, so it must not change).
--
-- Values: task 1.1c brief (Ari). Only the 5 road destinations get a label
-- now; 'Ulaanbaatar city (local work)' and 'Other / several / unknown'
-- stay NULL until Ari gives their Mongolian text (the UI shows `name`
-- when name_mn is NULL).
--
-- Not in this migration (they were planned for 1.1c in PROJECT_STATE, but
-- are not in the brief): Ari's round-trip days and mine-site rows.
--
-- Run after 001 (the runner provides the transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction \
--       -v ON_ERROR_STOP=1 -f /sql/migrations/002_destinations_name_mn.up.sql
-- Undo: 002_destinations_name_mn.down.sql
-- =====================================================================

-- NULL allowed (rows without a label yet); blank text is not, and two
-- destinations must not show the same label in the picker.
ALTER TABLE destinations
    ADD COLUMN name_mn TEXT CHECK (btrim(name_mn) <> '');

ALTER TABLE destinations
    ADD CONSTRAINT destinations_name_mn_uq UNIQUE (name_mn);

UPDATE destinations AS d
SET name_mn = v.name_mn
FROM (VALUES
    ('Zamyn-Uud (MN–CN border)',    'Замын-Үүд'),
    ('Erenhot (CN side of border)', 'Эрээн'),
    ('Beijing',                     'Бээжин'),
    ('Altanbulag (MN–RU border)',   'Алтанбулаг'),
    ('Kyakhta (RU side of border)', 'Хиагт')
) AS v (name, name_mn)
WHERE d.name = v.name;

-- Stop (and roll back) if a name above was not found, e.g. renamed in 001.
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM destinations WHERE name_mn IS NOT NULL) <> 5 THEN
        RAISE EXCEPTION 'migration 002: expected 5 destinations with name_mn, found %',
            (SELECT COUNT(*) FROM destinations WHERE name_mn IS NOT NULL);
    END IF;
END
$$;
