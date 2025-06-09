INSTALL spatial;
INSTALL httpfs;
LOAD spatial;
LOAD httpfs; 

-- Access the data on AWS
SET s3_region='us-west-2';

SELECT 'Starting Overture data download...' as message;

-- Download divisions
SELECT 'Downloading divisions...' as message;
COPY (
    SELECT *
    FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division/*')
) TO 'data/divisions.parquet';

SELECT 'Divisions download complete.' as message;

-- Download division areas
SELECT 'Downloading division areas...' as message;
COPY (
    SELECT *
    FROM read_parquet('s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division_area/*')
) TO 'data/division_areas.parquet';

SELECT 'Division areas download complete.' as message;

SELECT 'All downloads finished successfully!' as message;
