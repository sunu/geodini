"""
Search tool for Geodini - provides search functionality for geospatial data
"""

import duckdb
import os
import time
import json
from typing import Dict, Any, Optional, Literal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Minimum similarity threshold for Jaro-Winkler matching
SIMILARITY_THRESHOLD = 0.7

def search(
    query: str,
    limit: Optional[int] = 100,
    exact: bool = False,
    country_code: Optional[str] = None,
    include_geometry: bool = False,
    search_type: Literal["divisions", "places", "all"] = "divisions",
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """
    Search for a place in the Overture data and return results.

    Args:
        query: The search query string
        limit: Maximum number of results to return (None for no limit)
        exact: Whether to perform an exact match (True) or a fuzzy match (False)
        country_code: Optional ISO country code to filter results (e.g., "US", "CA")
        include_geometry: Whether to include geometry data as GeoJSON (default: False)
        search_type: Type of search to perform:
            - "divisions" (default): Search only administrative divisions
            - "places": Search only land features (parks, mountains, etc.)
            - "all": Search both divisions and places
        similarity_threshold: Minimum Jaro-Winkler similarity score (0.0 to 1.0)

    Returns:
        A dictionary with search results and metadata
    """
    data_path = os.path.join("data", "overture.duckdb")

    result = {
        "success": False,
        "query": query,
        "exact_match": exact,
        "country_code": country_code,
        "include_geometry": include_geometry,
        "search_type": search_type,
        "similarity_threshold": similarity_threshold,
        "results": [],
        "count": 0,
        "query_time_seconds": 0,
        "error": None,
    }

    if not os.path.exists(data_path):
        result["error"] = (
            "Database file not found. Please make sure overture.duckdb exists in the data directory."
        )
        return result

    try:
        start_time = time.time()
        # Connect to the existing DuckDB database
        con = duckdb.connect(data_path)

        # Load spatial extension if geometry is requested
        if include_geometry:
            try:
                con.execute("INSTALL spatial;")
                con.execute("LOAD spatial;")
            except Exception as e:
                result["error"] = f"Failed to load spatial extension: {str(e)}"
                return result

        places = []

        # Search in divisions if requested
        if search_type in ["divisions", "all"]:
            # Create conditions for searching in divisions name fields
            if exact:
                divisions_condition = "(LOWER(dn.primary_name) = LOWER(?) OR LOWER(dn.common_en_name) = LOWER(?))"
            else:
                divisions_condition = "TRUE"  # We'll filter by similarity score in the outer query

            division_query = build_division_query(
                divisions_condition,
                country_code is not None,
                limit if search_type == "divisions" else None,
            )

            # Set up parameters for the query
            params = []

            # Parameters for the CASE statements
            params.extend([query, query])

            # Parameters for the similarity calculation
            params.extend([query, query])

            # Add country code parameter if provided
            if country_code:
                params.append(country_code)

            # Add similarity threshold parameter
            params.append(similarity_threshold)

            # Parameter for the ORDER BY clause
            params.append(query)

            # Add LIMIT parameter if applicable
            if search_type == "divisions" and limit is not None:
                params.append(limit)

            # Query the database for divisions
            logger.info(f"Division Query: {division_query}")
            logger.info(f"Parameters: {params}")

            t1 = time.time()
            df = con.execute(division_query, params).fetchdf()
            t2 = time.time()
            logger.info(f"Division query time: {t2 - t1} seconds")

            # Process division results
            for _, row in df.iterrows():
                place = {
                    "id": row["id"],
                    "name": row["name"],
                    "name_type": row["name_type"],
                    "type": row["subtype"],
                    "entity_type": "division",
                    "country": row["country"],
                    "similarity_score": row["similarity_score"],
                    "hierarchy": [],
                }

                # Process hierarchy data
                try:
                    if row["hierarchies"] is not None and len(row["hierarchies"]) > 0:
                        h = row["hierarchies"][0]
                        for level in h:
                            if "name" in level:
                                place["hierarchy"].append(level["name"])
                except Exception:
                    pass

                # Fetch geometry data if requested
                if include_geometry:
                    try:
                        # Query to get geometry as GeoJSON for this division
                        geojson_query = """
                            SELECT ST_AsGeoJSON(ST_GeomFromWKB(geometry)) AS geojson
                            FROM main.division_areas
                            WHERE division_id = ?
                            LIMIT 1
                        """
                        geojson_df = con.execute(geojson_query, [place["id"]]).fetchdf()

                        if not geojson_df.empty:
                            # Parse the GeoJSON string to a dictionary
                            geojson_str = geojson_df["geojson"][0]
                            if geojson_str:
                                place["geometry"] = json.loads(geojson_str)
                    except Exception as e:
                        print(f"Error getting geometry for division {place['id']}: {e}")
                    if not place.get("geometry"):
                        continue

                places.append(place)

        # Search in land features if requested
        if search_type in ["places", "all"]:
            # Create conditions for searching in land name fields
            if exact:
                land_condition = "(LOWER(ln.primary_name) = LOWER(?) OR LOWER(ln.common_en_name) = LOWER(?))"
            else:
                land_condition = "TRUE"  # We'll filter by similarity score in the outer query

            land_query = build_land_query(
                land_condition,
                country_code is not None,
                limit if search_type == "places" else None,
            )

            # Set up parameters for the query
            params = []

            # Parameters for the CASE statements
            params.extend([query, query])

            # Parameters for the similarity calculation
            params.extend([query, query])

            # Add country code parameter if provided
            if country_code:
                params.append(country_code)

            # Add similarity threshold parameter
            params.append(similarity_threshold)

            # Parameter for the ORDER BY clause
            params.append(query)

            # Add LIMIT parameter if applicable
            if search_type == "places" and limit is not None:
                params.append(limit)

            # Query the database for land features
            logger.info(f"Land Query: {land_query}")
            logger.info(f"Parameters: {params}")

            t1 = time.time()
            df = con.execute(land_query, params).fetchdf()
            t2 = time.time()
            logger.info(f"Land query time: {t2 - t1} seconds")

            # Process land results
            for _, row in df.iterrows():
                place = {
                    "id": row["id"],
                    "name": row["name"],
                    "name_type": row["name_type"],
                    "type": row["subtype"],
                    "entity_type": "place",
                    "class": row["class"],
                    "similarity_score": row["similarity_score"],
                }

                # Fetch geometry data if requested
                if (
                    include_geometry
                    and "geometry" in row
                    and row["geometry"] is not None
                ):
                    try:
                        # Land features already have geometry in the table
                        geojson_query = """
                            SELECT ST_AsGeoJSON(ST_GeomFromWKB(?)) AS geojson
                        """
                        geojson_df = con.execute(
                            geojson_query, [row["geometry"]]
                        ).fetchdf()

                        if not geojson_df.empty:
                            # Parse the GeoJSON string to a dictionary
                            geojson_str = geojson_df["geojson"][0]
                            if geojson_str:
                                place["geometry"] = json.loads(geojson_str)
                    except Exception as e:
                        place["geometry_error"] = str(e)

                places.append(place)

        # If we're searching both types and have a limit, apply it after combining
        if search_type == "all" and limit is not None:
            places = sorted(
                places,
                key=lambda x: (
                    0 if x["name"].lower() == query.lower() else 1,
                    -x["similarity_score"],
                ),
            )
            places = places[:limit]

        query_time = time.time() - start_time
        result["query_time_seconds"] = round(query_time, 3)

        logger.info(
            f"Finished query in {query_time} seconds. Found {len(places)} results."
        )

        result["results"] = places
        result["count"] = len(places)
        result["success"] = True

        return result

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error: {str(e)}")
        return result


def build_division_query(
    name_condition: str, has_country_filter: bool, limit: Optional[int] = None
) -> str:
    """Build SQL query for searching divisions"""
    where_clause = name_condition

    # Add country code filter if provided
    if has_country_filter:
        where_clause += " AND LOWER(dn.country) = LOWER(?)"

    # Query using Jaro-Winkler similarity
    sql_query = f"""
        WITH matched_results AS (
            SELECT 
                dn.*,
                d.hierarchies,
                CASE 
                    WHEN LOWER(dn.primary_name) = LOWER(?) THEN dn.primary_name
                    ELSE dn.common_en_name
                END AS matched_name,
                CASE 
                    WHEN LOWER(dn.primary_name) = LOWER(?) THEN 'primary'
                    ELSE 'common_en'
                END AS name_type,
                GREATEST(
                    jaro_winkler_similarity(LOWER(dn.primary_name), LOWER(?)),
                    jaro_winkler_similarity(LOWER(dn.common_en_name), LOWER(?))
                ) as similarity_score
            FROM main.all_division_names dn
            JOIN main.divisions d ON dn.id = d.id
            WHERE {where_clause}
        )
        SELECT 
            id,
            matched_name AS name,
            name_type,
            subtype,
            hierarchies,
            country,
            similarity_score
        FROM matched_results
        WHERE similarity_score >= ?
        ORDER BY 
            CASE WHEN LOWER(matched_name) = LOWER(?) THEN 0 ELSE 1 END,
            similarity_score DESC,
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
                ELSE 10
            END,
            matched_name
    """

    # Add LIMIT clause only if limit is specified
    if limit is not None:
        sql_query += " LIMIT ?"

    return sql_query


def build_land_query(
    name_condition: str, has_country_filter: bool, limit: Optional[int] = None
) -> str:
    """Build SQL query for searching land features (places)"""
    where_clause = name_condition

    # Add country code filter if provided
    if has_country_filter:
        pass

    # Query using Jaro-Winkler similarity
    sql_query = f"""
        WITH matched_results AS (
            SELECT 
                ln.*,
                CASE 
                    WHEN LOWER(ln.primary_name) = LOWER(?) THEN ln.primary_name
                    ELSE ln.common_en_name
                END AS matched_name,
                CASE 
                    WHEN LOWER(ln.primary_name) = LOWER(?) THEN 'primary'
                    ELSE 'common_en'
                END AS name_type,
                GREATEST(
                    jaro_winkler_similarity(LOWER(ln.primary_name), LOWER(?)),
                    jaro_winkler_similarity(LOWER(ln.common_en_name), LOWER(?))
                ) as similarity_score
            FROM main.all_land_names ln
            WHERE {where_clause}
        )
        SELECT 
            id,
            matched_name AS name,
            name_type,
            subtype,
            class,
            geometry,
            similarity_score
        FROM matched_results
        WHERE similarity_score >= ?
        ORDER BY 
            CASE WHEN LOWER(matched_name) = LOWER(?) THEN 0 ELSE 1 END,
            similarity_score DESC,
            CASE name_type
                WHEN 'primary' THEN 0
                ELSE 1
            END,
            matched_name
    """

    # Add LIMIT clause only if limit is specified
    if limit is not None:
        sql_query += " LIMIT ?"

    return sql_query


if __name__ == "__main__":
    # Example usage
    print("Search divisions:")
    results = search("San Francisco", search_type="divisions")
    print(json.dumps(results, indent=2))

    # print("\nSearch places:")
    # results = search("Yosemite", search_type="places")
    # print(json.dumps(results, indent=2))

    # print("\nSearch both:")
    # results = search("London", search_type="all", limit=5)
    # print(json.dumps(results, indent=2))

    # print("\nSearch with country filter:")
    # results = search("London", country_code="GB", search_type="divisions")
    # print(json.dumps(results, indent=2))

    # print("\nSearch with geometry:")
    # results = search("Yosemite", search_type="places", include_geometry=True)
    # print(json.dumps(results, indent=2))
