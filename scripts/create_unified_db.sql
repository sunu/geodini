-- Attach the database
ATTACH '/data/overture-unified.duckdb' AS db;

SET preserve_insertion_order=false;
PRAGMA memory_limit='2GB';
PRAGMA temp_directory='/tmp/duckdb_temp';

-- Step 1: Create an intermediate table for division areas with geometry.
-- This reads the area data, filters it, and stores it in the database file.
-- This helps reduce memory pressure during the main join operation.
CREATE OR REPLACE TABLE db.temp_division_areas AS
SELECT
    division_id,
    geometry
FROM read_parquet('/data/division_areas/*.parquet')
WHERE geometry IS NOT NULL;

-- Create and populate the 'all_geometries' table
CREATE OR REPLACE TABLE db.all_geometries AS
-- Division data
SELECT
    d.id,
    d.subtype,
    d.names,
    d.country,
    d.hierarchies,
    d.names->>'primary' AS primary_name,
    d.names->'common'->>'en' AS common_en_name,
    da.geometry,
    'division' AS source_type
FROM read_parquet('/data/divisions/*.parquet') d
-- Use an INNER JOIN because we only want divisions with geometries.
-- This is more explicit than a LEFT JOIN with a WHERE clause on the right table.
JOIN db.temp_division_areas da ON d.id = da.division_id;

-- Clean up the intermediate table
DROP TABLE db.temp_division_areas;
