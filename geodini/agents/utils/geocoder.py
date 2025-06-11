import json
import os
from pprint import pprint
from typing import Any

import duckdb

# get data path from current file
DATA_PATH = os.environ.get(
    "DATA_PATH",
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "overture-unified.duckdb"
    ),
)


def geocode(query: str, limit: int | None = 20) -> list[dict[str, Any]]:
    conn = duckdb.connect(DATA_PATH, read_only=True)
    conn.execute("INSTALL spatial;")
    conn.execute("LOAD spatial;")
    # Reduce memory usage
    conn.execute("SET preserve_insertion_order = false")
    conn.execute("PRAGMA memory_limit='3GB'")
    conn.execute("PRAGMA temp_directory='/tmp/duckdb_temp'")
    sql_query = build_query(False, (limit is not None))
    params = [query] * 2
    if limit is not None:
        params.append(limit)
    result = conn.execute(sql_query, params).fetch_df()
    conn.close()
    # convert geometry to geojson
    result["geometry"] = result["geometry"].apply(
        lambda x: json.loads(x) if x is not None else None
    )
    return result.to_dict(orient="records")


def build_query(has_country_filter: bool, has_limit: bool) -> str:
    """Build SQL query for searching overture unified data"""

    where_clauses = [
        "source_type = 'division'",
        "geometry IS NOT NULL",
        "(primary_similarity > 0.8 OR common_similarity > 0.8)",
    ]

    # Add country code filter if provided
    if has_country_filter:
        where_clauses.append("LOWER(country) = LOWER(?)")

    where_clause_str = " AND ".join(where_clauses)

    sql_query = f"""
        WITH with_similarity AS (
            SELECT 
                *,
                jaro_winkler_similarity(LOWER(primary_name), LOWER(?)) as primary_similarity,
                jaro_winkler_similarity(LOWER(common_en_name), LOWER(?)) as common_similarity
            FROM all_geometries
        )
        SELECT
            id,
            COALESCE(common_en_name, primary_name) as name,
            CASE
                WHEN primary_similarity >= common_similarity THEN 'primary'
                ELSE 'common_en'
            END as name_type,
            subtype,
            source_type,
            hierarchies,
            country,
            GREATEST(primary_similarity, common_similarity) as similarity,
            ST_AsGeoJSON(ST_GeomFromWKB(geometry)) as geometry
        FROM with_similarity
        WHERE {where_clause_str}
        ORDER BY similarity DESC
    """

    # Add LIMIT clause only if limit is specified
    if has_limit:
        sql_query += " LIMIT ?"

    # print(sql_query)

    return sql_query


if __name__ == "__main__":
    import time

    start_time = time.time()
    geocode("new york", limit=20)
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds")
    # pprint(geocode("Amazon"))
