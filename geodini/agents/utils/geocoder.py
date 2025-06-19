import json
import os
from pprint import pprint
from typing import Any
import time

from sqlalchemy import create_engine, text
import dotenv

dotenv.load_dotenv()


# PostgreSQL connection settings
def get_postgis_engine():
    """Get PostgreSQL engine for PostGIS geocoding"""
    host = os.getenv("POSTGRES_HOST") or "database"
    database = os.getenv("POSTGRES_DB") or "postgres"
    user = "postgres"
    port = os.getenv("POSTGRES_PORT") or 5432
    password = os.getenv("POSTGRES_PASSWORD")

    return create_engine(f"postgresql://{user}:{password}@{host}:{port}/{database}")


def geocode(query: str, limit: int | None = 20) -> list[dict[str, Any]]:
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
            print(f"Warning: Could not enable pg_trgm extension: {e}")

    connect_time = time.time() - start_time
    print(f"PostgreSQL connection time: {connect_time:.2f} seconds")

    query_start_time = time.time()

    # Build the PostgreSQL query using trigram similarity
    sql_query = build_postgis_query(limit is not None)

    try:
        with engine.begin() as conn:
            if limit is not None:
                result = conn.execute(text(sql_query), {"query": query, "limit": limit})
            else:
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
        print(f"Error executing PostgreSQL query: {e}")
        return []

    query_time = time.time() - query_start_time
    print(f"PostgreSQL query execution time: {query_time:.2f} seconds")

    total_time = time.time() - start_time
    print(f"Total query execution time: {total_time:.2f} seconds")

    return results


def build_postgis_query(has_limit: bool) -> str:
    """Build PostgreSQL query for searching overture unified data using trigram similarity"""

    sql_query = """
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
            ST_AsGeoJSON(geometry) as geometry
        FROM all_geometries
        WHERE 
            source_type = 'division'
            AND geometry IS NOT NULL
            AND (primary_name % :query OR common_en_name % :query)
            AND GREATEST(
                COALESCE(SIMILARITY(primary_name, :query), 0),
                COALESCE(SIMILARITY(common_en_name, :query), 0)
            ) > 0.3
        ORDER BY similarity DESC
    """

    # Add LIMIT clause only if limit is specified
    if has_limit:
        sql_query += " LIMIT :limit"

    return sql_query


if __name__ == "__main__":
    import time

    # Test PostgreSQL geocoding
    print("=== Testing PostgreSQL geocoding ===")
    start_time = time.time()
    postgis_results = geocode("new york", limit=5)
    end_time = time.time()
    print(f"PostgreSQL time taken: {end_time - start_time} seconds")
    print(f"PostgreSQL results: {len(postgis_results)} found")

    if postgis_results:
        print("\nSample PostgreSQL result:")
        pprint(postgis_results[0])
