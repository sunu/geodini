-- Attach the database
ATTACH 'data/overture-unified.duckdb' AS db;

-- Install and Load the FTS extension
INSTALL fts;
LOAD fts;

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

UNION ALL

-- Land data
SELECT 
    id,
    subtype,
    names,
    NULL as country,
    NULL as hierarchies,
    names->>'primary' AS primary_name,
    names->'common'->>'en' AS common_en_name,
    geometry,
    'land' AS source_type
FROM read_parquet('data/land.parquet')
WHERE geometry IS NOT NULL
AND names IS NOT NULL;

-- Create FTS index on 'all_geometries' table for fast name search
-- PRAGMA create_fts_index('db.all_geometries', 'id', 'primary_name', 'common_en_name');
