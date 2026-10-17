-- =====================================================================
-- Migration 005 UP — 4 new cross-border destinations (Task 1.6, D-081)
--
-- Route lines from Ari (1.6 brief). One-way road km from OSRM through the
-- border crossing as a waypoint (src/data/external_api.py,
-- configs/routes_1_6.yaml); `source` is the exact OSRM request.
--
--   name_mn   | start          | crossing                  | one-way km
--   Ганцмод   | Таван толгой   | Гашуунсухайт – Ganqimaodu |  247
--   Сэхээ     | Ulaanbaatar    | Шивээхүрэн – Ceke         |  928
--   Улаан-Үд  | Ulaanbaatar    | Алтанбулаг – Kyakhta      |  578
--   Кош-Агач  | Ulaanbaatar    | Цагааннуур – Tashanta     | 1786
--
-- Ганцмод starts at Tavan Tolgoi, not UB: its km is the Tavan Tolgoi ->
-- Ganqimaodu leg (the coal shuttle), the table has no "start" column.
-- No route was skipped (none was already a destination) and OSRM found a
-- road for all 4. Round-trip days stay NULL (not known, like 001).
--
-- Run after 004 (scripts/migrate.py applies it and records it in
-- schema_migrations; no BEGIN/COMMIT inside, the runner provides the transaction).
-- Undo: 005_destinations_cross_border.down.sql
-- =====================================================================

INSERT INTO destinations (name, name_mn, route_category, one_way_km, source) VALUES
    ('Ganqimaodu (CN side of Gashuunsukhait border)', 'Ганцмод',  'mn_china',  247,
        'https://router.project-osrm.org/route/v1/driving/105.5713167,43.7136004;107.5688958,42.4153691;107.5733786,42.4003511?overview=false'),
    ('Ceke (CN side of Shiveekhuren border)',         'Сэхээ',    'mn_china',  928,
        'https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;101.2818646,42.5884756;101.2735126,42.5588510?overview=false'),
    ('Ulan-Ude (via Altanbulag–Kyakhta)',             'Улаан-Үд', 'mn_russia', 578,
        'https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;106.4886870,50.3218610;107.5839105,51.8357841?overview=false'),
    ('Kosh-Agach (via Tsagaannuur–Tashanta)',         'Кош-Агач', 'mn_russia', 1786,
        'https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;89.4675213,49.6079465;88.6628218,49.9947055?overview=false');
