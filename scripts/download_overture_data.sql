LOAD spatial; -- noqa
LOAD httpfs;  -- noqa

-- Access the data on AWS
SET s3_region='us-west-2';

SELECT 'Starting Overture data download...' as message;

-- -- Download divisions
-- SELECT 'Downloading divisions...' as message;
-- COPY (
--     SELECT *
--     FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division/*')
-- ) TO 'data/divisions.parquet';

-- SELECT 'Divisions download complete.' as message;

-- -- Download division areas
-- SELECT 'Downloading division areas...' as message;
-- COPY (
--     SELECT *
--     FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division_area/*')
-- ) TO 'data/division_areas.parquet';

-- SELECT 'Division areas download complete.' as message;

-- Download land data
SELECT 'Downloading land data...' as message;
COPY (
    SELECT *
    FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=base/type=land/*')
) TO 'data/land.parquet';

SELECT 'Land data download complete.' as message;

-- Download water data 
SELECT 'Downloading water data...' as message;
COPY (
    SELECT *
    FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=base/type=water/*')
) TO 'data/water.parquet';

SELECT 'Water data download complete.' as message;

-- Download infrastructure data
SELECT 'Downloading infrastructure data...' as message;
COPY (
    SELECT *
    FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=base/type=infrastructure/*')
) TO 'data/infrastructure.parquet';

SELECT 'Infrastructure data download complete.' as message;

SELECT 'All downloads finished successfully!' as message;
