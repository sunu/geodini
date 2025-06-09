-- Attach the database
ATTACH 'data/overture-unified.duckdb' AS db;

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
FROM read_parquet('data/divisions.parquet') d
LEFT JOIN read_parquet('data/division_areas.parquet') da ON d.id = da.division_id
WHERE da.geometry IS NOT NULL
