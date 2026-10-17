-- =====================================================================
-- Migration 005 DOWN — undo 005_destinations_cross_border.up.sql (Task 1.6)
--
-- Removes the 4 destinations. Service records that point to one of them
-- keep the record but lose the link (destination_id -> NULL, the place name
-- is kept in destination_raw) so the FK does not block the DELETE.
-- Remove the version row afterwards so scripts/migrate.py applies 005 again:
--   DELETE FROM schema_migrations WHERE version = '005';
-- =====================================================================

UPDATE service_records AS s
SET destination_raw = COALESCE(s.destination_raw, d.name_mn, d.name),
    destination_id  = NULL
FROM destinations AS d
WHERE s.destination_id = d.id
  AND d.name IN ('Ganqimaodu (CN side of Gashuunsukhait border)', 'Ceke (CN side of Shiveekhuren border)',
                 'Ulan-Ude (via Altanbulag–Kyakhta)', 'Kosh-Agach (via Tsagaannuur–Tashanta)');

DELETE FROM destinations
WHERE name IN ('Ganqimaodu (CN side of Gashuunsukhait border)', 'Ceke (CN side of Shiveekhuren border)',
               'Ulan-Ude (via Altanbulag–Kyakhta)', 'Kosh-Agach (via Tsagaannuur–Tashanta)');
