#!/bin/bash

# Ensure the /data directory exists
mkdir -p /data &&
echo 'Starting Overture data initialization process...'

# Check if FORCE_RECREATE is set and not empty
if [ -n "$FORCE_RECREATE" ]; then
    echo 'FORCE_RECREATE is set. Re-downloading data and recreating database...'

    # Remove existing parquet files
    echo 'Removing existing Parquet file directories (if any)...'
    rm -rf /data/divisions /data/division_areas

    # Download Overture data
    echo 'Downloading Overture data...'
    mkdir -p /data/divisions /data/division_areas
    aws s3 cp --no-sign-request s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division/ /data/divisions/ --recursive &&
    aws s3 cp --no-sign-request s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division_area/ /data/division_areas/ --recursive &&
    echo 'Overture data download complete.'

    # Remove existing DuckDB database
    echo 'Removing existing DuckDB database (if any)...'
    rm -f /data/overture-unified.duckdb

    # Create DuckDB database
    echo 'Creating DuckDB database...'
    duckdb -c ".read /scripts/create_unified_db.sql" &&
    echo 'DuckDB database creation complete.'
else
    echo 'FORCE_RECREATE is not set. Checking for existing data...'

    # Handle Parquet files
    if [ ! -d "/data/divisions" ] || [ ! -d "/data/division_areas" ] || [ -z "$(ls -A /data/divisions)" ] || [ -z "$(ls -A /data/division_areas)" ]; then
        echo 'One or both Parquet file directories are missing or empty. Downloading Overture data...'
        mkdir -p /data/divisions /data/division_areas
        aws s3 cp --no-sign-request s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division/ /data/divisions/ --recursive &&
        aws s3 cp --no-sign-request s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division_area/ /data/division_areas/ --recursive &&
        echo 'Overture data download complete.'
    else
        echo 'Overture Parquet data already exists. Skipping download.'
    fi

    # Handle DuckDB database
    if [ ! -f /data/overture-unified.duckdb ]; then
        echo 'DuckDB database does not exist. Creating DuckDB database...'
        duckdb -c ".read /scripts/create_unified_db.sql" &&
        echo 'DuckDB database creation complete.'
    else
        echo 'DuckDB database already exists. Skipping creation.'
    fi
fi

echo 'Overture data initialization process finished.'
