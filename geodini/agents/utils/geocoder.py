import json
import logging
import os
import time
from pprint import pprint
from typing import Any

from sqlalchemy import create_engine, text
import dotenv

from geodini.cache import cached


dotenv.load_dotenv()

logger = logging.getLogger(__name__)


# PostgreSQL connection settings
def get_postgis_engine():
    """Get PostgreSQL engine for PostGIS geocoding"""
    host = os.getenv("POSTGRES_HOST") or "database"
    database = os.getenv("POSTGRES_DB") or "postgres"
    user = "postgres"
    port = os.getenv("POSTGRES_PORT") or 5432
    password = os.getenv("POSTGRES_PASSWORD")

    return create_engine(f"postgresql://{user}:{password}@{host}:{port}/{database}")


@cached(
    prefix="postgis_geocode",
    ttl=3600,  # 1 hour
    cache_condition=lambda result: result
    and len(result) > 0,  # Only cache non-empty results
)
def geocode(query: str, simplify_geometry: bool = True) -> list[dict[str, Any]]:
    """
    Geocode using PostgreSQL/PostGIS database with trigram similarity search.
    Follows the same signature and return format as the geocode() function.
    """
    start_time = time.time()
    engine = get_postgis_engine()

    # Ensure pg_trgm extension is available
    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        except Exception as e:
            logger.warning(f"Warning: Could not enable pg_trgm extension: {e}")

    connect_time = time.time() - start_time
    logger.info(f"PostgreSQL connection time: {connect_time:.2f} seconds")

    query_start_time = time.time()

    # Build the PostgreSQL query using trigram similarity
    sql_query = build_postgis_query(simplify_geometry)

    try:
        with engine.begin() as conn:
            result = conn.execute(text(sql_query), {"query": query})

            rows = result.fetchall()

            # Convert to the same format as the original geocode function
            results = []
            for row in rows:
                # Parse geometry JSON if it exists
                geometry = None
                if row.geometry:
                    try:
                        geometry = json.loads(row.geometry)
                    except (json.JSONDecodeError, TypeError):
                        geometry = None

                results.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "name_type": row.name_type,
                        "subtype": row.subtype,
                        "source_type": row.source_type,
                        "hierarchies": (
                            json.loads(row.hierarchies) if row.hierarchies else None
                        ),
                        "country": row.country,
                        "similarity": float(row.similarity),
                        "geometry": geometry,
                    }
                )

    except Exception as e:
        logger.error(f"Error executing PostgreSQL query: {e}")
        return []

    query_time = time.time() - query_start_time
    logger.info(f"PostgreSQL query execution time: {query_time:.2f} seconds")

    total_time = time.time() - start_time
    logger.info(f"Total query execution time: {total_time:.2f} seconds")

    return results


def build_postgis_query(simplify_geometry: bool = True) -> str:
    """Build PostgreSQL query for searching overture unified data using trigram similarity"""

    # Choose geometry function based on whether to simplify
    geometry_func = "ST_AsGeoJSON(ST_Simplify(geometry, 0.001))" if simplify_geometry else "ST_AsGeoJSON(geometry)"

    sql_query = f"""
        SELECT 
            id,
            COALESCE(common_en_name, primary_name) as name,
            CASE
                WHEN COALESCE(SIMILARITY(primary_name, :query), 0) >= 
                     COALESCE(SIMILARITY(common_en_name, :query), 0)
                THEN 'primary'
                ELSE 'common_en'
            END as name_type,
            subtype,
            source_type,
            hierarchies,
            country,
            GREATEST(
                COALESCE(SIMILARITY(primary_name, :query), 0),
                COALESCE(SIMILARITY(common_en_name, :query), 0)
            ) as similarity,
            {geometry_func} as geometry,
            GREATEST(
                COALESCE(SIMILARITY(primary_name, :query), 0),
                COALESCE(SIMILARITY(common_en_name, :query), 0)
            ) * CASE subtype
                WHEN 'country' THEN 2.0
                WHEN 'dependency' THEN 2.0
                WHEN 'macroregion' THEN 2.0
                WHEN 'region' THEN 2.0
                WHEN 'macrocounty' THEN 2.0
                WHEN 'county' THEN 1.0
                WHEN 'localadmin' THEN 1.1
                WHEN 'locality' THEN 0.9
                WHEN 'borough' THEN 0.8
                WHEN 'macrohood' THEN 0.8
                WHEN 'neighborhood' THEN 0.8
                WHEN 'microhood' THEN 0.8
                ELSE 1.0
            END as weighted_similarity
        FROM all_geometries
        WHERE 
            source_type = 'division'
            AND geometry IS NOT NULL
            AND (primary_name % :query OR common_en_name % :query)
            AND GREATEST(
                COALESCE(SIMILARITY(primary_name, :query), 0),
                COALESCE(SIMILARITY(common_en_name, :query), 0)
            ) > 0.33
        ORDER BY weighted_similarity DESC
        LIMIT 50
    """

    return sql_query


if __name__ == "__main__":
    import time

    # Test PostgreSQL geocoding
    print("=== Testing PostgreSQL geocoding ===")
    start_time = time.time()
    postgis_results = geocode("new york")
    end_time = time.time()
    print(f"PostgreSQL time taken: {end_time - start_time} seconds")
    print(f"PostgreSQL results: {len(postgis_results)} found")

    if postgis_results:
        print("\nSample PostgreSQL result:")
        pprint(postgis_results[0])

    # print the name and similarity score of all results
    for result in postgis_results:
        print(
            f"Name: {result['name']}, Similarity: {result['similarity']}, Type: {result['subtype']}, Country: {result['country']}"
        )
    print(len(postgis_results))
