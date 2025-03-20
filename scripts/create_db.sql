-- Attach the database
ATTACH 'data/overture.duckdb' AS db;

-- Install and Load the FTS extension
INSTALL fts;
LOAD fts;

-- Create and populate the 'divisions' table
CREATE OR REPLACE TABLE db.divisions AS 
SELECT 
    id, 
    subtype, 
    names, 
    country, 
    hierarchies, 
    population,
    names->>'primary' AS primary_name,
    names->'common'->>'en' AS common_en_name
FROM read_parquet('data/divisions.parquet') 
ORDER BY names->>'primary';

-- Create and populate the 'division_areas' table
CREATE OR REPLACE TABLE db.division_areas AS 
SELECT id, division_id, geometry FROM read_parquet('data/division_areas.parquet');

-- Create FTS index on 'divisions' table for fast name search
PRAGMA create_fts_index('db.divisions', 'id', 'primary_name', 'common_en_name');


-- -- Create and populate the 'land' table
-- CREATE OR REPLACE TABLE db.land AS
-- SELECT 
--     id,
--     subtype,
--     names,
--     class,
--     geometry,
--     names->>'primary' AS primary_name,
--     names->'common'->>'en' AS common_en_name
-- FROM read_parquet('data/land.parquet');

-- -- Create an FTS table for 'land' names
-- CREATE VIRTUAL TABLE db.land_fts USING fts5(primary_name, common_en_name);

-- -- Populate the FTS table with land names
-- INSERT INTO db.land_fts (primary_name, common_en_name)
-- SELECT primary_name, common_en_name FROM db.land;

-- -- Create a view for land names using FTS
-- CREATE OR REPLACE VIEW db.all_land_names AS
-- SELECT l.id, l.primary_name, l.common_en_name, l.subtype, l.class, l.geometry
-- FROM db.land l
-- JOIN db.land_fts fts ON l.primary_name = fts.primary_name OR l.common_en_name = fts.common_en_name;

