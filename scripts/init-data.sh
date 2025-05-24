#!/bin/bash

mkdir -p /data &&
echo 'Starting Overture data initialization...' &&
# check if the parquet files exist
if [ ! -f /data/divisions.parquet ] || [ ! -f /data/division_areas.parquet ]; then
    duckdb -c '.read /scripts/download_overture_data.sql' &&
    echo 'Overture data download complete.'
else
    echo 'Overture data already exists.'
fi
echo 'Creating DuckDB database...' &&
# check if the file exists
if [ ! -f /data/overture-unified.duckdb ]; then
    duckdb /data/overture-unified.duckdb -c '.read /scripts/create_unified_db.sql' &&
    echo 'DuckDB database creation complete.'
else
    echo 'DuckDB database already exists.'
fi