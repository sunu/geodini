import glob
import json
import logging
import os
import subprocess
import sys

import dotenv
import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import wkb
from sqlalchemy import create_engine, text

dotenv.load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

host = os.getenv("POSTGRES_HOST") or "database"
database = os.getenv("POSTGRES_DB") or "postgres"
user = "postgres"
port = os.getenv("POSTGRES_PORT") or 5432
password = os.getenv("POSTGRES_PASSWORD")

# Add FORCE_RECREATE option
FORCE_RECREATE = os.getenv("FORCE_RECREATE", "false").lower() in ("true", "1", "yes")

engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{database}")

DATA_PATH = os.getenv("DATA_PATH") or "/tmp/data"

# Configuration
BATCH_SIZE = 10000  # Adjust based on your system's memory


class NumpyAwareJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


def test_database_connection():
    """Test database connection and setup"""
    logger.info("Testing database connection...")
    logger.info(f"Connection details: {user}@{host}:{port}/{database}")

    try:
        # Test basic connection
        with engine.begin() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            logger.info(f"Database connection successful: {version}")

            # Test PostGIS extension
            try:
                result = conn.execute(text("SELECT PostGIS_Version();"))
                postgis_version = result.fetchone()[0]
                logger.info(f"PostGIS extension available: {postgis_version}")
            except Exception as e:
                logger.error(f"PostGIS extension not available: {e}")
                logger.info("Attempting to enable PostGIS...")
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
                    conn.execute(
                        text("CREATE EXTENSION IF NOT EXISTS postgis_topology;")
                    )
                    result = conn.execute(text("SELECT PostGIS_Version();"))
                    postgis_version = result.fetchone()[0]
                    logger.info(f"PostGIS extension enabled: {postgis_version}")
                except Exception as create_error:
                    logger.error(f"Failed to enable PostGIS: {create_error}")
                    raise

            # Test write permissions
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS connection_test (id SERIAL PRIMARY KEY);"
                )
            )
            conn.execute(text("DROP TABLE IF EXISTS connection_test;"))
            logger.info("Database write permissions confirmed")

        return True

    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Connection troubleshooting:")
        logger.error(f"  - Check if database is running on {host}:{port}")
        logger.error(f"  - Verify password is set correctly")
        logger.error(
            f"  - For outside Docker, try: POSTGRES_HOST=localhost POSTGRES_PORT=15432"
        )
        logger.error(
            f"  - For inside Docker, try: POSTGRES_HOST=database POSTGRES_PORT=5432"
        )
        return False


def get_common_en_name(names_obj):
    """Safely extract the common English name from a names object."""
    if not isinstance(names_obj, dict):
        return None

    common = names_obj.get("common")

    # Handle list format: [['lang', 'name'], ['lang2', 'name2'], ...] or [('lang', 'name'), ...]
    if isinstance(common, list):
        for item in common:
            # Handle list of lists: [['en', 'name'], ['ko', 'name'], ...]
            if isinstance(item, list) and len(item) >= 2 and item[0] == "en":
                return item[1]
            # Handle list of tuples: [('en', 'name'), ('ko', 'name'), ...]
            elif isinstance(item, tuple) and len(item) >= 2 and item[0] == "en":
                return item[1]

    return None


def check_and_download_data():
    """Check if data exists in DATA_PATH, if not download from S3"""
    logger.info(f"Checking for data in: {DATA_PATH}")

    # Define the required directories and their S3 sources
    data_requirements = {
        "divisions": {
            "local_path": os.path.join(DATA_PATH, "divisions"),
            "s3_path": "s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division/",
        },
        "division_areas": {
            "local_path": os.path.join(DATA_PATH, "division_areas"),
            "s3_path": "s3://overturemaps-us-west-2/release/2025-02-19.0/theme=divisions/type=division_area/",
        },
    }

    for data_type, paths in data_requirements.items():
        local_path = paths["local_path"]
        s3_path = paths["s3_path"]

        # Check if directory exists and has parquet files
        needs_download = False

        if not os.path.exists(local_path):
            logger.info(f"Directory {local_path} does not exist")
            needs_download = True
        else:
            # Check if directory has parquet files
            parquet_files = glob.glob(os.path.join(local_path, "*.parquet"))
            if not parquet_files:
                logger.info(
                    f"Directory {local_path} exists but contains no parquet files"
                )
                needs_download = True
            else:
                logger.info(f"Found {len(parquet_files)} parquet files in {local_path}")

        if needs_download:
            logger.info(f"Downloading {data_type} data from S3...")

            # Create directory if it doesn't exist
            os.makedirs(local_path, exist_ok=True)

            # Download from S3 using aws cli
            try:
                cmd = [
                    "aws",
                    "s3",
                    "cp",
                    "--no-sign-request",
                    s3_path,
                    local_path,
                    "--recursive",
                ]

                logger.info(f"Running command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)

                if result.stdout:
                    logger.info(f"Download output: {result.stdout}")

                # Verify download was successful
                parquet_files = glob.glob(os.path.join(local_path, "*.parquet"))
                if parquet_files:
                    logger.info(
                        f"Successfully downloaded {len(parquet_files)} parquet files to {local_path}"
                    )
                else:
                    raise Exception(
                        f"No parquet files found after download to {local_path}"
                    )

            except subprocess.CalledProcessError as e:
                logger.error(f"Error downloading {data_type} data from S3: {e}")
                logger.error(f"Command output: {e.stdout}")
                logger.error(f"Command error: {e.stderr}")
                raise Exception(f"Failed to download {data_type} data from S3")
            except FileNotFoundError:
                logger.error(
                    "AWS CLI not found. Please install AWS CLI to download data from S3."
                )
                logger.error("You can install it with: pip install awscli")
                raise Exception("AWS CLI not available for data download")

    logger.info("Data availability check and download completed successfully")


def check_table_exists_with_data(table_name):
    """Check if a table exists and has data"""
    try:
        with engine.begin() as conn:
            # Check if table exists
            result = conn.execute(
                text(
                    """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = :table_name
                );
                """
                ),
                {"table_name": table_name},
            )
            table_exists = result.fetchone()[0]

            if not table_exists:
                logger.info(f"Table '{table_name}' does not exist")
                return False, 0

            # Check if table has data
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name};"))
            row_count = result.fetchone()[0]

            logger.info(f"Table '{table_name}' exists with {row_count:,} rows")
            return True, row_count

    except Exception as e:
        logger.error(f"Error checking table '{table_name}': {e}")
        return False, 0


def load_division_areas_in_batches():
    """Load division areas in batches to avoid memory issues"""
    # Check if table exists and has data
    table_exists, row_count = check_table_exists_with_data("division_areas")

    if table_exists and row_count > 0 and not FORCE_RECREATE:
        logger.info(
            f"Table 'division_areas' already exists with {row_count:,} rows. Skipping load."
        )
        logger.info("Set FORCE_RECREATE=true to force recreation of the table.")
        return row_count

    if FORCE_RECREATE and table_exists:
        logger.info("FORCE_RECREATE is set. Will recreate division_areas table.")

    logger.info("Starting to load division areas...")

    # Find all parquet files in the directory
    parquet_files = glob.glob(f"{DATA_PATH}/division_areas/*.parquet")
    logger.info(f"Found {len(parquet_files)} parquet files to process")

    total_areas = 0
    for file_path in parquet_files:
        parquet_file = pq.ParquetFile(file_path)
        total_areas += parquet_file.metadata.num_rows

    logger.info(f"Total division areas to process: {total_areas}")

    loaded_count = 0
    valid_count = 0
    batch_num = 0

    # Process each parquet file
    for file_idx, file_path in enumerate(parquet_files):
        logger.info(
            f"Processing file {file_idx + 1}/{len(parquet_files)}: {os.path.basename(file_path)}"
        )

        parquet_file = pq.ParquetFile(file_path)

        # Read in batches directly from parquet
        for batch in parquet_file.iter_batches(batch_size=BATCH_SIZE):
            # Convert to pandas DataFrame first
            batch_df = batch.to_pandas()

            # Decode geometry from WKB binary format
            if "geometry" in batch_df.columns:
                try:
                    # Convert WKB binary to shapely geometries
                    batch_df["geometry"] = batch_df["geometry"].apply(
                        lambda x: wkb.loads(x) if x is not None else None
                    )
                    # Create GeoDataFrame with proper geometry column and CRS
                    batch_df = gpd.GeoDataFrame(
                        batch_df, geometry="geometry", crs="EPSG:4326"
                    )
                except Exception as e:
                    logger.error(f"Error decoding geometry: {e}")
                    continue
            else:
                logger.warning("No geometry column found in batch, skipping...")
                continue

            # Filter out null geometries and select only needed columns
            batch_df = batch_df.loc[
                batch_df.geometry.notnull(), ["division_id", "geometry"]
            ]
            valid_batch_count = len(batch_df)

            if valid_batch_count > 0:  # Only process if there are valid records
                # Use replace for first batch with data, append for subsequent
                if_exists = "replace" if loaded_count == 0 else "append"

                batch_df.to_postgis(
                    "division_areas", engine, if_exists=if_exists, index=False
                )
                loaded_count += valid_batch_count

            valid_count += valid_batch_count
            batch_num += 1

            logger.info(
                f"Processed batch {batch_num}: {valid_batch_count} valid areas, {loaded_count} total loaded"
            )

    logger.info(
        f"Completed loading {loaded_count} division areas (from {total_areas} total)"
    )
    return loaded_count


def load_divisions_in_batches():
    """Load divisions in batches with name processing"""
    # Check if table exists and has data
    table_exists, row_count = check_table_exists_with_data("divisions")

    if table_exists and row_count > 0 and not FORCE_RECREATE:
        logger.info(
            f"Table 'divisions' already exists with {row_count:,} rows. Skipping load."
        )
        logger.info("Set FORCE_RECREATE=true to force recreation of the table.")
        return row_count

    if FORCE_RECREATE and table_exists:
        logger.info("FORCE_RECREATE is set. Will recreate divisions table.")

    logger.info("Starting to load divisions...")

    # Find all parquet files in the directory
    parquet_files = glob.glob(f"{DATA_PATH}/divisions/*.parquet")
    logger.info(f"Found {len(parquet_files)} parquet files to process")

    total_divs = 0
    for file_path in parquet_files:
        parquet_file = pq.ParquetFile(file_path)
        total_divs += parquet_file.metadata.num_rows

    logger.info(f"Total divisions to process: {total_divs}")

    loaded_count = 0
    batch_num = 0

    columns_to_load = ["id", "subtype", "names", "country", "hierarchies"]
    logger.info(f"Only loading specified columns: {columns_to_load}")

    # Drop dependent view before replacing table
    logger.info("Dropping dependent view before table replacement...")
    with engine.begin() as conn:
        conn.execute(text("DROP VIEW IF EXISTS all_geometries;"))

    # Process each parquet file
    for file_idx, file_path in enumerate(parquet_files):
        logger.info(
            f"Processing file {file_idx + 1}/{len(parquet_files)}: {os.path.basename(file_path)}"
        )

        parquet_file = pq.ParquetFile(file_path)

        # Read in batches directly from parquet
        for batch in parquet_file.iter_batches(
            batch_size=BATCH_SIZE, columns=columns_to_load
        ):
            batch_df = pd.DataFrame(batch.to_pandas())

            # Process names
            batch_df["primary_name"] = batch_df.names.apply(
                lambda n: n.get("primary") if n and isinstance(n, dict) else None
            )
            batch_df["common_en_name"] = batch_df.names.apply(get_common_en_name)

            # Columns with complex objects that need to be serialized to JSON
            json_cols = [
                "names",
                "hierarchies",
            ]

            for col in json_cols:
                if col in batch_df.columns:
                    batch_df[col] = batch_df[col].apply(
                        lambda x: (
                            json.dumps(x, cls=NumpyAwareJSONEncoder)
                            if x is not None
                            else None
                        )
                    )

            # Use replace for first batch, append for subsequent
            if_exists = "replace" if loaded_count == 0 else "append"

            batch_df.to_sql("divisions", engine, if_exists=if_exists, index=False)
            batch_count = len(batch_df)
            loaded_count += batch_count
            batch_num += 1

            logger.info(
                f"Loaded batch {batch_num}: {batch_count} divisions, {loaded_count} total loaded"
            )

    logger.info(f"Completed loading {loaded_count} divisions")
    return loaded_count


def create_combined_view():
    """Create a view that combines divisions with their geometries"""
    logger.info("Creating combined view...")

    with engine.begin() as conn:
        # Drop existing view if it exists
        conn.execute(text("DROP VIEW IF EXISTS all_geometries;"))

        # Create view that joins divisions with their areas
        create_view_sql = """
        CREATE VIEW all_geometries AS
        SELECT 
            d.id,
            d.subtype,
            d.names,
            d.country,
            d.hierarchies,
            d.primary_name,
            d.common_en_name,
            da.geometry,
            'division' as source_type
        FROM divisions d
        INNER JOIN division_areas da ON d.id = da.division_id
        WHERE da.geometry IS NOT NULL;
        """

        conn.execute(text(create_view_sql))

        # Get count of combined records
        result = conn.execute(text("SELECT COUNT(*) FROM all_geometries;"))
        combined_count = result.fetchone()[0]

    logger.info(f"Created combined view with {combined_count} records")
    return combined_count


def check_common_name_data():
    """Check if common_en_name column has any data"""
    logger.info("Checking common_en_name data availability...")

    try:
        with engine.begin() as conn:
            # Check total count
            result = conn.execute(text("SELECT COUNT(*) FROM divisions;"))
            total_count = result.fetchone()[0]

            # Check how many have non-null common_en_name
            result = conn.execute(
                text("SELECT COUNT(*) FROM divisions WHERE common_en_name IS NOT NULL;")
            )
            common_name_count = result.fetchone()[0]

            # Check how many have non-empty common_en_name
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM divisions WHERE common_en_name IS NOT NULL AND common_en_name != '';"
                )
            )
            non_empty_common_name_count = result.fetchone()[0]

            # Get some samples of common names
            result = conn.execute(
                text(
                    "SELECT primary_name, common_en_name FROM divisions WHERE common_en_name IS NOT NULL AND common_en_name != '' LIMIT 10;"
                )
            )
            samples = result.fetchall()

            logger.info(f"Total divisions: {total_count}")
            logger.info(f"Divisions with non-null common_en_name: {common_name_count}")
            logger.info(
                f"Divisions with non-empty common_en_name: {non_empty_common_name_count}"
            )
            logger.info(
                f"Percentage with common names: {(non_empty_common_name_count / total_count) * 100:.2f}%"
            )

            if samples:
                logger.info("Sample common names:")
                for i, sample in enumerate(samples, 1):
                    logger.info(
                        f"  {i}. Primary: '{sample.primary_name}' -> Common: '{sample.common_en_name}'"
                    )
            else:
                logger.info("No samples found - common_en_name appears to be empty!")

            # Let's also check the raw names structure
            result = conn.execute(
                text("SELECT names FROM divisions WHERE names IS NOT NULL LIMIT 5;")
            )
            name_samples = result.fetchall()

            logger.info("Sample raw names structures:")
            for i, sample in enumerate(name_samples, 1):
                try:
                    names_obj = json.loads(sample.names) if sample.names else {}
                    logger.info(f"  {i}. Names structure: {names_obj}")
                    # Test our extraction function
                    common_name = get_common_en_name(names_obj)
                    logger.info(f"      Extracted common name: {common_name}")
                except Exception as e:
                    logger.error(f"      Error parsing names: {e}")

    except Exception as e:
        logger.error(f"Error checking common name data: {str(e)}")


def test_query(place_name):
    """
    Search for places using trigram similarity on common_en_name and primary_name.
    Returns top 10 matches with similarity scores.
    """
    logger.info(f"Searching for places similar to: '{place_name}'")

    # First ensure pg_trgm extension is available
    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        except Exception as e:
            logger.error(f"Could not enable pg_trgm extension: {e}")
            logger.error("pg_trgm extension is required for similarity search")
            return []

    # Query with trigram similarity search on both name fields
    search_sql = """
    SELECT 
        id,
        subtype,
        country,
        primary_name,
        common_en_name,
        -- Calculate similarity scores for both fields
        GREATEST(
            COALESCE(SIMILARITY(primary_name, :place_name), 0),
            COALESCE(SIMILARITY(common_en_name, :place_name), 0)
        ) as similarity_score,
        -- Show which field matched better
        CASE 
            WHEN COALESCE(SIMILARITY(primary_name, :place_name), 0) >= 
                 COALESCE(SIMILARITY(common_en_name, :place_name), 0)
            THEN 'primary_name'
            ELSE 'common_en_name'
        END as best_match_field,
        -- Simplified geometry as GeoJSON (only for top result)
        ST_AsGeoJSON(ST_Simplify(geometry, 0.05)) as simplified_geometry
    FROM all_geometries
    WHERE 
        -- Use trigram similarity operator (% means similar to)
        (primary_name % :place_name OR common_en_name % :place_name)
    ORDER BY similarity_score DESC, subtype
    LIMIT 10;
    """

    try:
        with engine.begin() as conn:
            result = conn.execute(text(search_sql), {"place_name": place_name})

            matches = result.fetchall()

            if matches:
                logger.info(f"Found {len(matches)} matches:")
                for i, match in enumerate(matches, 1):
                    # Prioritize common name if available, otherwise use primary name
                    display_name = match.common_en_name or match.primary_name or "N/A"
                    alt_name = ""

                    # Show alternative name in parentheses if different from display name
                    if (
                        match.common_en_name
                        and match.primary_name
                        and match.common_en_name != match.primary_name
                    ):
                        alt_name = f" (also: {match.primary_name})"
                    elif not match.common_en_name and match.primary_name:
                        alt_name = " (primary name only)"

                    logger.info(
                        f"{i:2d}. {display_name}{alt_name} "
                        f"[{match.subtype}] [{match.country or 'N/A'}] "
                        f"- Score: {match.similarity_score:.3f} "
                        f"(via {match.best_match_field})"
                    )

                    # Show simplified geometry only for the top match
                    if i == 1 and match.simplified_geometry:
                        # Truncate very long geometries for readability
                        geom_text = match.simplified_geometry
                        logger.info(f"      Geometry: {geom_text}")

                return matches
            else:
                logger.info("No matches found")
                return []

    except Exception as e:
        logger.error(f"Error during trigram similarity search: {str(e)}")
        return []


def create_trigram_indexes():
    """Create trigram indexes for faster similarity searches on name columns"""
    logger.info("Creating trigram indexes for faster similarity searches...")

    try:
        with engine.begin() as conn:
            # Ensure pg_trgm extension is available
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
            logger.info("pg_trgm extension is available")

            # Create GIN indexes for trigram similarity on name columns
            # Check if indexes already exist to avoid errors
            index_queries = [
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_divisions_primary_name_trgm ON divisions USING gin (primary_name gin_trgm_ops);",
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_divisions_common_en_name_trgm ON divisions USING gin (common_en_name gin_trgm_ops);",
                # Also create standard indexes for other common query patterns
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_divisions_subtype ON divisions (subtype);",
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_divisions_country ON divisions (country);",
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_division_areas_division_id ON division_areas (division_id);",
            ]

            for idx, query in enumerate(index_queries, 1):
                try:
                    logger.info(
                        f"Creating index {idx}/{len(index_queries)}: {query.split()[5] if len(query.split()) > 5 else 'unknown'}"
                    )
                    # Note: CONCURRENTLY cannot be used inside a transaction, so we need separate connections
                    conn.execute(
                        text(query.replace("CONCURRENTLY ", ""))
                    )  # Remove CONCURRENTLY for transaction compatibility
                except Exception as e:
                    logger.warning(f"Index creation warning (may already exist): {e}")

            # Check what indexes were created
            result = conn.execute(
                text(
                    """
                SELECT indexname, tablename 
                FROM pg_indexes 
                WHERE tablename IN ('divisions', 'division_areas') 
                AND indexname LIKE '%trgm%'
                ORDER BY tablename, indexname;
            """
                )
            )
            trigram_indexes = result.fetchall()

            if trigram_indexes:
                logger.info("Trigram indexes found:")
                for idx in trigram_indexes:
                    logger.info(f"  {idx.tablename}.{idx.indexname}")
            else:
                logger.warning("No trigram indexes found after creation")

            # Show all indexes on these tables
            result = conn.execute(
                text(
                    """
                SELECT indexname, tablename, indexdef 
                FROM pg_indexes 
                WHERE tablename IN ('divisions', 'division_areas') 
                ORDER BY tablename, indexname;
            """
                )
            )
            all_indexes = result.fetchall()

            logger.info(
                f"All indexes on divisions and division_areas tables ({len(all_indexes)} total):"
            )
            for idx in all_indexes:
                logger.info(f"  {idx.tablename}.{idx.indexname}")

    except Exception as e:
        logger.error(f"Error creating trigram indexes: {str(e)}")
        raise


def main():
    """Main execution function"""
    logger.info("Starting geodini data ingestion...")

    if FORCE_RECREATE:
        logger.info("FORCE_RECREATE is enabled - will recreate all tables")
    else:
        logger.info(
            "FORCE_RECREATE is disabled - will skip tables that already have data"
        )

    # Test database connection first
    if not test_database_connection():
        logger.error("Database connection test failed. Exiting.")
        sys.exit(1)

    logger.info("Database connection test passed. Proceeding with ingestion...")

    try:
        # Check and download data if needed
        check_and_download_data()

        # Load division areas in batches
        areas_count = load_division_areas_in_batches()

        # Load divisions in batches
        divs_count = load_divisions_in_batches()

        # Create combined view
        combined_count = create_combined_view()

        logger.info("=== INGESTION SUMMARY ===")
        logger.info(f"Division areas available: {areas_count:,}")
        logger.info(f"Divisions available: {divs_count:,}")
        logger.info(f"Combined records available: {combined_count:,}")
        logger.info("Ingestion completed successfully!")

        # Check common name data availability
        logger.info("\n=== CHECKING COMMON NAME DATA ===")
        check_common_name_data()

        # Test the search functionality
        logger.info("\n=== TESTING SEARCH FUNCTIONALITY ===")
        test_places = ["London", "Paris", "New York", "Tokyo"]
        for place in test_places:
            logger.info(f"\n--- Testing search for '{place}' ---")
            results = test_query(place)
            if not results:
                logger.info("No results found")
            logger.info("---")

        # Create trigram indexes
        create_trigram_indexes()

    except Exception as e:
        logger.error(f"Error during ingestion: {str(e)}")
        raise


if __name__ == "__main__":
    main()
