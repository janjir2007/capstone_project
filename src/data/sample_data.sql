-- =====================================================================
-- Hand-written SAMPLE rows — 100% SYNTHETIC (RISK-06).
-- Names, phones, plates and companies are invented. Phones use the
-- made-up block 99110001–99110009 (plus 99000000 as the Geo-Expert
-- contact placeholder) — do not call them.
--
-- Designed so every segment appears when as_of = 2026-09-30:
--   vehicle 1  loyal      (3 services)
--   vehicle 2  returning  (2 services)
--   vehicle 3  new        (1 service, prediction in the future)
--   vehicle 4  at_risk    (predicted 2026-07-15, +7 days passed, never returned)
--   vehicle 5  returning  (mine truck, fleet number, engine hours only)
--   vehicle 6  returning  (prediction passed but the truck DID come back)
-- Driver phone 99110002 appears on vehicles 1 AND 6 (driver changed trucks, D-004).
--
-- Load (all-or-nothing, thanks to --single-transaction):
--   docker compose exec -T db psql -U oil -d oil_change --single-transaction -v ON_ERROR_STOP=1 -f /sql/sample_data.sql
-- =====================================================================

INSERT INTO companies (id, name) VALUES
    (1, 'Говь Тээвэр ХХК'),
    (2, 'Хан Уул Карго ХХК'),
    (3, 'Бат-Оргил (хувь хүн)'),
    (4, 'Өмнөд Уурхай ХХК');

INSERT INTO vehicles (id, company_id, identifier_type, identifier, plate_normalized, vehicle_model) VALUES
    (1, 1, 'plate',    '1234 УБА', '1234УБА', 'Howo A7'),
    (2, 1, 'plate',    '5678 УНА', '5678УНА', 'Shacman X3000'),
    (3, 2, 'plate',    '9012 ДАА', '9012ДАА', 'Foton Auman'),
    (4, 3, 'plate',    '3456 ӨМА', '3456ӨМА', 'Howo A7'),
    (5, 4, 'fleet_no', 'HT-12',    NULL,      'BelAZ 75131'),
    (6, 2, 'plate',    '7788 ХАА', '7788ХАА', 'Shacman X3000');

INSERT INTO service_records
    (id, vehicle_id, service_date, odometer_km, engine_hours, oil_grade, liters, route, driver_name, driver_phone, oil_changer, photo_ref)
VALUES
    (1,  1, '2026-03-05', 210000, NULL,    '15W-40', 32.0, 'mn_china',  'Дорж Б.',     '99110001', 'Oil changer A', NULL),
    (2,  1, '2026-05-20', 232000, NULL,    '15W-40', 32.0, 'mn_china',  'Дорж Б.',     '99110001', 'Oil changer A', NULL),
    (3,  1, '2026-08-10', 255500, NULL,    '15W-40', 32.0, 'mn_china',  'Ганбат Т.',   '99110002', 'Oil changer A', 'photos/sample/0003.jpg'),
    (4,  2, '2026-06-15', 98000,  NULL,    '10W-40', 28.0, 'ub_city',   'Сараа Д.',    '99110003', 'Oil changer A', NULL),
    (5,  2, '2026-09-10', 104500, NULL,    '10W-40', 28.0, 'ub_city',   'Сараа Д.',    '99110003', 'Oil changer B', NULL),
    (6,  3, '2026-09-20', 150200, NULL,    '15W-40', 30.0, 'mn_russia', 'Болд Ц.',     '99110004', 'Oil changer B', NULL),
    (7,  4, '2026-05-10', 301000, NULL,    '15W-40', 32.0, 'mixed',     'Бат-Оргил Н.', '99110005', 'Oil changer A', NULL),
    (8,  5, '2026-07-01', NULL,   12500.0, '15W-40', 90.0, 'mine_site', 'Энхээ Г.',    '99110006', 'Oil changer B', NULL),
    (9,  5, '2026-08-25', NULL,   12980.5, '15W-40', 90.0, 'mine_site', 'Мөнх Л.',     '99110007', 'Oil changer B', NULL),
    (10, 6, '2026-06-01', 180000, NULL,    '15W-40', 30.0, 'mn_china',  'Ганбат Т.',   '99110002', 'Oil changer A', NULL),
    (11, 6, '2026-09-01', 205000, NULL,    '15W-40', 30.0, 'mn_china',  'Түмэн О.',    '99110008', 'Oil changer A', NULL);

INSERT INTO predictions (id, vehicle_id, based_on_service_id, predicted_days, predicted_date, model_version, created_at) VALUES
    (1, 1, 3,  76.0, '2026-10-25', 'sample-v0', '2026-08-10 12:00+08'),
    (2, 4, 7,  66.0, '2026-07-15', 'sample-v0', '2026-05-10 12:00+08'),
    (3, 6, 10, 80.0, '2026-08-20', 'sample-v0', '2026-06-01 12:00+08'),
    (4, 3, 6,  71.0, '2026-11-30', 'sample-v0', '2026-09-20 12:00+08');

INSERT INTO reminders (id, vehicle_id, prediction_id, phone, message_text, status, created_at, sent_at) VALUES
    (1, 4, 2, '99110005',
     'Сайн байна уу! 3456ӨМА машины тос солих хугацаа 2026-07-15. Сүүлд 2026-05-10-нд 15W-40 тос солисон. Холбогдох: Geo-Expert 99000000',
     'sent', '2026-07-12 09:00+08', '2026-07-12 09:05+08'),
    (2, 1, 1, '99110002',
     'Сайн байна уу! 1234УБА машины тос солих хугацаа 2026-10-25. Сүүлд 2026-08-10-нд 15W-40 тос солисон. Холбогдох: Geo-Expert 99000000',
     'pending', '2026-09-30 09:00+08', NULL);

-- Explicit ids were used above, so move each id counter past the max id;
-- otherwise the next normal INSERT would try id = 1 and fail.
SELECT setval(pg_get_serial_sequence('companies', 'id'),       (SELECT MAX(id) FROM companies));
SELECT setval(pg_get_serial_sequence('vehicles', 'id'),        (SELECT MAX(id) FROM vehicles));
SELECT setval(pg_get_serial_sequence('service_records', 'id'), (SELECT MAX(id) FROM service_records));
SELECT setval(pg_get_serial_sequence('predictions', 'id'),     (SELECT MAX(id) FROM predictions));
SELECT setval(pg_get_serial_sequence('reminders', 'id'),       (SELECT MAX(id) FROM reminders));
