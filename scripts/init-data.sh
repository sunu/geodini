#!/bin/bash

# Ensure the /data directory exists
mkdir -p /data &&
echo 'Starting Overture data initialization process...'

# Check if FORCE_RECREATE is set and not empty
if [ -n "$FORCE_RECREATE" ]; then
    echo 'FORCE_RECREATE is set. Re-downloading data and recreating database...'

    # Remove existing parquet files
    echo 'Removing existing Parquet files (if any)...'
    rm -f /data/divisions.parquet /data/division_areas.parquet

    # Download Overture data
    echo 'Downloading Overture data...'
    duckdb -c ".read /scripts/download_overture_data.sql" &&
    echo 'Overture data download complete.'

    # Remove existing DuckDB database
    echo 'Removing existing DuckDB database (if any)...'
    rm -f /data/overture-unified.duckdb

    # Create DuckDB database
    echo 'Creating DuckDB database...'
    duckdb /data/overture-unified.duckdb -c ".read /scripts/create_unified_db.sql" &&
    echo 'DuckDB database creation complete.'
else
    echo 'FORCE_RECREATE is not set. Checking for existing data...'

    # Handle Parquet files
    if [ ! -f /data/divisions.parquet ] || [ ! -f /data/division_areas.parquet ]; then
        echo 'One or both Parquet files are missing. Downloading Overture data...'
        duckdb -c ".read /scripts/download_overture_data.sql" &&
        echo 'Overture data download complete.'
    else
        echo 'Overture Parquet data already exists. Skipping download.'
    fi

    # Handle DuckDB database
    if [ ! -f /data/overture-unified.duckdb ]; then
        echo 'DuckDB database does not exist. Creating DuckDB database...'
        duckdb /data/overture-unified.duckdb -c ".read /scripts/create_unified_db.sql" &&
        echo 'DuckDB database creation complete.'
    else
        echo 'DuckDB database already exists. Skipping creation.'
    fi
fi

echo 'Overture data initialization process finished.'
