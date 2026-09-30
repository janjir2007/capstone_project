-- =====================================================================
-- Example queries (Task 1.1). Expected results on sample_data.sql are
-- listed in docs/data_dictionary.md §5 and checked by tests/test_schema.py.
--
-- Each query starts with a "-- name:" line; the test splits the file on it.
-- Literal values stand in for API parameters. In the API they become bound
-- parameters, and the plate is normalized by src/common/plates.py FIRST.
--
-- Run:  docker compose exec -T db psql -U oil -d oil_change -f /sql/example_queries.sql
-- =====================================================================

-- name: lookup_by_plate
-- Vehicle card header for one (already normalized) plate.
SELECT v.id AS vehicle_id,
       v.identifier,
       v.identifier_type,
       v.vehicle_model,
       c.name AS company_name,
       s.service_count,
       s.last_service_date,
       s.last_oil_grade,
       s.last_liters,
       s.last_route,
       s.last_driver_name,
       s.last_driver_phone
FROM vehicles v
JOIN companies c ON c.id = v.company_id
JOIN v_vehicle_service_summary s ON s.vehicle_id = v.id
WHERE v.plate_normalized = '1234УБА';

-- name: lookup_by_phone
-- Every vehicle this phone number has EVER appeared on (drivers change
-- trucks, D-004), newest service first.
SELECT v.id AS vehicle_id,
       v.identifier,
       c.name AS company_name,
       s.service_count,
       s.last_service_date,
       s.last_driver_phone
FROM vehicles v
JOIN companies c ON c.id = v.company_id
JOIN v_vehicle_service_summary s ON s.vehicle_id = v.id
WHERE v.id IN (SELECT sr.vehicle_id FROM service_records sr WHERE sr.driver_phone = '99110002')
ORDER BY s.last_service_date DESC, v.id;

-- name: service_count_per_vehicle
SELECT v.id AS vehicle_id,
       v.identifier,
       s.service_count,
       s.first_service_date,
       s.last_service_date
FROM vehicles v
JOIN v_vehicle_service_summary s ON s.vehicle_id = v.id
ORDER BY v.id;

-- name: segment_per_vehicle
-- Fixed date so the result is reproducible. The app uses v_vehicle_segment (today).
SELECT vehicle_id, service_count, last_service_date, latest_predicted_date, segment
FROM vehicle_segments(DATE '2026-09-30')
ORDER BY vehicle_id;

-- name: segment_counts
-- Shape of GET /stats/segments.
SELECT segment, COUNT(*) AS vehicles
FROM vehicle_segments(DATE '2026-09-30')
GROUP BY segment
ORDER BY segment;
