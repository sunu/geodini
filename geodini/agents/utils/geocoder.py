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


SUBTYPES = {
    "DIVISION": [
        "country",
        "dependency",
        "region",
        "county",
        "localadmin",
        "locality",
        "macrohood",
        "neighborhood",
        "microhood",
    ],
    "LAND": [
        "sand",
        "wetland",
        "desert",
    ],
}


def geocode(query: str, limit: int | None = None) -> list[dict[str, Any]]:
    conn = duckdb.connect(DATA_PATH)
    conn.execute("INSTALL spatial;")
    conn.execute("LOAD spatial;")
    name_condition = (
        f"(common_en_name ILIKE '%{query}%' OR primary_name ILIKE '%{query}%')"
    )
    sql_query = build_query(name_condition, False, (limit is not None))
    params = [query, f"%{query}%", query, f"%{query}%", query]
    if limit is not None:
        params.append(limit)
    # print(sql_query)
    result = conn.execute(sql_query, params).fetch_df()
    conn.close()
    # convert geometry to geojson
    result["geometry"] = result["geometry"].apply(
        lambda x: json.loads(x) if x is not None else None
    )
    return result.to_dict(orient="records")


def build_query(name_condition: str, has_country_filter: bool, has_limit: bool) -> str:
    """Build SQL query for searching overture unified data"""

    # only include division results for now
    where_clause = "source_type = 'division'"
    # geometry should be not null
    where_clause += " AND geometry IS NOT NULL"

    where_clause += f" AND {name_condition}"

    # Add country code filter if provided
    if has_country_filter:
        where_clause += " AND LOWER(country) = LOWER(?)"

    # Simplified query that takes advantage of our views
    sql_query = f"""
        WITH matched_results AS (
            SELECT 
                id,
                CASE 
                    WHEN LOWER(primary_name) = LOWER(?) OR primary_name ILIKE ? THEN primary_name
                    ELSE common_en_name
                END AS matched_name,
                CASE 
                    WHEN LOWER(primary_name) = LOWER(?) OR primary_name ILIKE ? THEN 'primary'
                    ELSE 'common_en'
                END AS name_type,
                subtype,
                source_type,
                hierarchies,
                country,
                geometry
            FROM all_geometries
            WHERE {where_clause}
        )
        SELECT
            id,
            matched_name AS name,
            name_type,
            subtype,
            source_type,
            hierarchies,
            country,
            ST_AsGeoJSON(ST_GeomFromWKB(geometry)) as geometry
        FROM matched_results
        ORDER BY
            CASE WHEN LOWER(matched_name) = LOWER(?) THEN 0 ELSE 1 END,
            CASE name_type
                WHEN 'primary' THEN 0
                ELSE 1
            END,
            CASE subtype
                WHEN 'country' THEN 1
                WHEN 'dependency' THEN 2
                WHEN 'region' THEN 3
                WHEN 'county' THEN 4
                WHEN 'localadmin' THEN 5
                WHEN 'locality' THEN 6
                WHEN 'macrohood' THEN 7
                WHEN 'neighborhood' THEN 8
                WHEN 'microhood' THEN 9
                WHEN 'sand' THEN 13
                WHEN 'wetland' THEN 13
                WHEN 'desert' THEN 13
                ELSE 13
            END,
            matched_name
    """

    # Add LIMIT clause only if limit is specified
    if has_limit:
        sql_query += " LIMIT ?"

    return sql_query


if __name__ == "__main__":
    pprint(geocode("new york"))
    pprint(geocode("Amazon"))
