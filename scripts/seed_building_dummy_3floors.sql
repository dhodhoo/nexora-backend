-- Building-first dummy seed.
-- Purpose: seed one building with one building manager, 3 floors, 9 units, and recent kWh data
-- without requiring rows in communities/units/devices tables.
--
-- Notes:
-- - energy_readings.community_id is still mandatory in the current schema, so this seed uses
--   a technical placeholder value: C-DUMMY-BLD-001
-- - the building analytics path reads primarily from energy_readings.building_id
--
-- Login after seed:
--   email    : manager.demo.building@nexora.local
--   password : manager12345

BEGIN;

-- 1) Building + manager
INSERT INTO buildings (building_id, name)
VALUES ('bld-demo-3f-001', 'Gedung Demo 3 Lantai')
ON CONFLICT (building_id) DO UPDATE
SET name = EXCLUDED.name;

INSERT INTO building_configs (building_id, peak_threshold_kwh, created_at, updated_at)
VALUES ('bld-demo-3f-001', 4.5, NOW(), NOW())
ON CONFLICT (building_id) DO UPDATE
SET peak_threshold_kwh = EXCLUDED.peak_threshold_kwh,
    updated_at = NOW();

-- bcrypt hash for password: manager12345
INSERT INTO users (
  user_id,
  full_name,
  email,
  password_hash,
  role,
  status,
  community_id,
  building_id,
  unit_id,
  is_deleted,
  created_at,
  updated_at
)
VALUES (
  'usr-demo-bld-mgr-001',
  'Demo Building Manager',
  'manager.demo.building@nexora.local',
  '$2b$12$0iD20Kx4TjBemCGmF.04tevso5RozB5QrP1q8emj9iuOt0MndFhgW',
  'ROLE_BUILDING_MANAGER',
  'ACTIVE',
  NULL,
  'bld-demo-3f-001',
  NULL,
  FALSE,
  NOW(),
  NOW()
)
ON CONFLICT (user_id) DO UPDATE
SET full_name = EXCLUDED.full_name,
    email = EXCLUDED.email,
    password_hash = EXCLUDED.password_hash,
    role = EXCLUDED.role,
    status = EXCLUDED.status,
    building_id = EXCLUDED.building_id,
    updated_at = NOW();

-- 2) Building units only
WITH unit_seed (floor_no, unit_no, unit_id, zone) AS (
  VALUES
    (1, 1, 'F01-01', 'north'),
    (1, 2, 'F01-02', 'center'),
    (1, 3, 'F01-03', 'south'),
    (2, 1, 'F02-01', 'north'),
    (2, 2, 'F02-02', 'center'),
    (2, 3, 'F02-03', 'south'),
    (3, 1, 'F03-01', 'north'),
    (3, 2, 'F03-02', 'center'),
    (3, 3, 'F03-03', 'south')
)
INSERT INTO building_units (
  building_id,
  unit_id,
  is_active,
  metadata_json,
  created_at,
  updated_at
)
SELECT
  'bld-demo-3f-001',
  unit_id,
  TRUE,
  json_build_object(
    'floor', floor_no,
    'zone', zone,
    'label', 'Lantai ' || floor_no || ' Unit ' || unit_no
  ),
  NOW(),
  NOW()
FROM unit_seed
ON CONFLICT (building_id, unit_id) DO UPDATE
SET is_active = EXCLUDED.is_active,
    metadata_json = EXCLUDED.metadata_json,
    updated_at = NOW();

-- 3) Recent building consumption data for the last 4 hourly buckets.
-- community_id here is only a technical placeholder for the current schema.
WITH unit_seed (floor_no, unit_no, unit_id) AS (
  VALUES
    (1, 1, 'F01-01'),
    (1, 2, 'F01-02'),
    (1, 3, 'F01-03'),
    (2, 1, 'F02-01'),
    (2, 2, 'F02-02'),
    (2, 3, 'F02-03'),
    (3, 1, 'F03-01'),
    (3, 2, 'F03-02'),
    (3, 3, 'F03-03')
),
device_seed (device_id, power_watt, weight) AS (
  VALUES
    ('ac', 900::float, 1.00::numeric),
    ('lamp', 120::float, 0.28::numeric),
    ('fridge', 180::float, 0.34::numeric)
),
bucket_seed (bucket_idx, ts) AS (
  SELECT gs, date_trunc('hour', NOW()) - ((3 - gs) || ' hour')::interval
  FROM generate_series(0, 3) AS gs
)
INSERT INTO energy_readings (
  building_id,
  community_id,
  unit_id,
  device_id,
  timestamp,
  kwh,
  power_watt,
  tariff_per_kwh,
  estimated_cost,
  is_simulation,
  raw_payload
)
SELECT
  'bld-demo-3f-001',
  'C-DUMMY-BLD-001',
  u.unit_id,
  d.device_id,
  b.ts,
  ROUND(((0.22 * u.floor_no) + (0.08 * u.unit_no) + (0.05 * b.bucket_idx) + d.weight)::numeric, 2)::float,
  d.power_watt,
  1444.7,
  ROUND((((0.22 * u.floor_no) + (0.08 * u.unit_no) + (0.05 * b.bucket_idx) + d.weight) * 1444.7)::numeric, 2)::float,
  FALSE,
  json_build_object(
    'source', 'sql_seed',
    'building_id', 'bld-demo-3f-001',
    'floor', u.floor_no,
    'unit_no', u.unit_no,
    'community_id_placeholder', 'C-DUMMY-BLD-001'
  )
FROM unit_seed u
CROSS JOIN device_seed d
CROSS JOIN bucket_seed b
ON CONFLICT (community_id, unit_id, device_id, timestamp) DO NOTHING;

COMMIT;
