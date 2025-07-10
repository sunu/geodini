import asyncio
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pprint import pformat
from typing import Any, Literal

import pluggy
from pydantic_ai import Agent
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from geodini import hookspecs, lib
from geodini.agents.utils.postgis_exec import (
    clear_geometries_table,
    create_geometries_table,
    insert_place,
    postgis_agent,
    postgis_query_judgement_agent,
    run_postgis_query,
    search_subtype_within_aoi,
)
from geodini.cache import cached


logger = logging.getLogger(__name__)


def get_plugin_manager():
    pm = pluggy.PluginManager("geodini")
    pm.add_hookspecs(hookspecs)
    pm.load_setuptools_entrypoints("geodini")
    pm.register(lib)
    return pm


@dataclass
class Place:
    id: str
    hierarchy: list[str]
    name: str
    country: str
    subtype: str


@dataclass
class RephrasedQuery:
    query: str
    country_code: str | None
    exact: bool


@dataclass
class RoutingResult:
    query_type: Literal["simple", "complex"]


@dataclass
class ComplexGeocodeResult:
    queries: list[str]
    rephrased_complex_query: str | None = None
    set_query: bool = False
    subtype: str | None = None


@dataclass
class RerankingResult:
    most_probable: str


class RoundedFloat(float):
    def __repr__(self):
        return f"{self:.2f}"


def recursively_convert(obj):
    if isinstance(obj, float):
        return RoundedFloat(obj)
    elif isinstance(obj, (list, tuple)):
        return [recursively_convert(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: recursively_convert(v) for k, v in obj.items()}
    return obj


def clip_coordinates_with_rounding(geojson: dict[str, Any]) -> dict[str, Any]:
    converted = recursively_convert(geojson)
    return converted


def simplify_geometry(
    geometry: dict[str, Any], tolerance_m: float = 10000
) -> dict[str, Any]:
    to_meters = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    to_degrees = Transformer.from_crs(
        "EPSG:3857", "EPSG:4326", always_xy=True
    ).transform

    geom = shape(geometry)
    projected = transform(to_meters, geom)
    simplified = projected.simplify(tolerance_m, preserve_topology=True)
    back_transformed = transform(to_degrees, simplified)
    geojson_raw = mapping(back_transformed)

    geojson = clip_coordinates_with_rounding(geojson_raw)

    return geojson


rephrase_agent = Agent(
    "openai:gpt-4.1-mini",
    output_type=RephrasedQuery,
    system_prompt="""
        Given the search query, rephrase it to be more specific and accurate. We will be using this query to search for places in the overture database. So it helps to make the query be full formal name of the place.
        
        Extract:
        1. The main search term (place name) - for example, "the city of San Francisco" should return "San Francisco", "New York City" should return "New York", "Paris, TX" should return "Paris",
            "Sahara Desert" should return "Sahara", "The Himalayan mountain range" should return "Himalaya", "The Amazon rainforest" should return "Amazon".
            If the query is a shortened name, return the full name - for example, "usa" or "The US" should return "United States" and so on.
            If the query is a informal name, return the formal name along with the informal name - for example, "Washington DC" should return "Washington, District of Columbia".
        2. Country code (ISO 2-letter code) if a specific country is mentioned
        3. Whether an exact match is requested (e.g., "exactly", "precisely")
        
        Only return the JSON object, nothing else.
    """,
)


routing_agent = Agent(
    "openai:gpt-4.1-mini",
    output_type=RoutingResult,
    system_prompt="""
        Given the search query, determine if it is a simple or complex query.
        A simple query is directly geocodable location description. For example: "New York City", "London in Canada", "India"
        A complex query contains spatial logic and operators. For example: "India and Sri Lanka", "Within 100km of Mumbai", "France north of Paris", "Area within 100kms to 200kms of Delhi", "Border of India and China".
        Set queries are also complex queries. For example: "regions in India", "localities within 100km of Mumbai", "localadmins in California", "localities in France" where we are looking for a set of places within an area of interest (AOI) defined by the query.
    """,
)


complex_geocode_query_agent = Agent(
    "openai:gpt-4.1-mini",
    output_type=ComplexGeocodeResult,
    system_prompt="""
        Given the search query, return ALL relevant places to search for in the query as queries.

        For example, if the query is "Within 100km of Mumbai", return ["Mumbai"] as queries.
        for "Either in Canada or in the US", return ["Canada", "US"] as queries.
        for "France north of Paris", return ["France", "Paris"] as queries.

        If the query is for a set of places within an aoi, set the set_query field to True.
        When set_query is True, set the subtype field to the type of places in the set.
        When set_query is True, set the rephrased_complex_query field to the query to use for target area calculation without the subtype details.

        For examples, if the query is "regions in India", return ["India"] as queries, set set_query to True and subtype to "region" and rephrased_complex_query to "India".
        If the query is "localities within 100km of Mumbai", return ["Mumbai"] as queries, set set_query to True and subtype to "locality" and rephrased_complex_query to "within 100km of Mumbai".

        The set of allowed subtypes is: "region", "locality", "localadmin".

        If the query is not a set query, dont set the set_query field, subtype field and rephrased_complex_query field.
        For example, the query "within 100km of Mumbai" because we are not looking for a set of subtypes, but rather just an area of interest (AOI) around Mumbai.

        If you dont know the subtype, set it to the most appropriate match in the allowed subtype list.
    """,
)


rerank_agent = Agent(
    # 4o-mini is smarter than 3.5-turbo. And does better in edge cases.
    "openai:gpt-4.1-mini",
    output_type=RerankingResult,
    system_prompt="""
        Given the search query and results, rank them in order of 
        relevance to the query.
        Results can be administrative regions, cities, countries, lakes, mountains, forests
        or any other geographical entity. This is described by the subtype field.
        The hierarchy field describes the administrative hierarchy of the place if known.
        Consider name, hierarchy, subtype, and country to determine the relevance to the query.
        
        From the results list, return a JSON object with:
        1. "most_probable": The ID of the most relevant result

        Make sure the returned ID is in the results list.

        While reranking, consider the following:
        - The query might be a shortened name and the result might be a full name. For example, "United States" or "United States of America" is a match for "USA" or "The US".
        - The query might be a informal name and the result might be a formal name. For example, "District of Columbia" is a candidate for "DC" or "Washington, D.C." or even just "Washington". So consider all possible variations of the query when matching.
        - Consider geographical context. For example, "London in Canada" should rank "London, Ontario" higher than "London, England" because it is more likely to be the correct answer.   
""",
)


@cached(prefix="simple_geocode", ttl=3600)
async def simple_geocode(query: str, simplify_geometry: bool = True) -> dict:
    """Handle simple geocoding queries."""
    logger.info(f"Starting simple geocode for {query}")
    pm = get_plugin_manager()
    geocoders = pm.hook.get_geocoders(geocoders=list())
    logger.info(f"Geocoders: {geocoders}")
    start_time = time.time()

    rephrased_query = await rephrase_agent.run(user_prompt=f"Search query: {query}")
    logger.info(f"Rephrased query: {pformat(rephrased_query.output)}")

    results = []
    for geocoder_group in geocoders:
        with ThreadPoolExecutor() as executor:
            futures = []
            for geocoder in geocoder_group:
                # Check if geocoder supports simplify_geometry parameter (like our postgis geocoder)
                try:
                    import inspect
                    sig = inspect.signature(geocoder)
                    if 'simplify_geometry' in sig.parameters:
                        futures.append(executor.submit(geocoder, rephrased_query.output.query, simplify_geometry))
                    else:
                        futures.append(executor.submit(geocoder, rephrased_query.output.query))
                except:
                    # Fallback to original call if inspection fails
                    futures.append(executor.submit(geocoder, rephrased_query.output.query))
            
            for future in futures:
                results.extend(future.result())

    for result in results:
        if result["hierarchies"] is not None:
            result["hierarchy"] = result["hierarchies"][0]
        else:
            result["hierarchy"] = []
        hierarchy = []
        for level in result["hierarchy"]:
            hierarchy.append(level["name"])
        result["hierarchy"] = hierarchy

    places = []
    for result in results:
        places.append(
            Place(
                id=result["id"],
                hierarchy=result["hierarchy"],
                name=result["name"],
                country=result["country"],
                subtype=result["subtype"],
            )
        )

    results_dict = {
        result["id"]: {
            "id": result["id"],
            "name": result["name"],
            "country": result["country"],
            "subtype": result["subtype"],
            "source_type": result["source_type"],
            "geometry": result["geometry"],
            "hierarchy": result["hierarchy"],
        }
        for result in results
    }

    if places:
        # Check if top result has perfect score and others don't - skip LLM if so
        results_with_scores = [r for r in results if "similarity" in r]
        if results_with_scores:
            # Sort by similarity score (highest first)
            results_with_scores.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            top_score = results_with_scores[0].get("similarity", 0)

            # If top result has perfect score (1.0) and others don't, use it directly
            if top_score == 1.0 and (
                len(results_with_scores) == 1
                or results_with_scores[1].get("similarity", 0) < 1.0
            ):
                logger.info(
                    f"Perfect match found with score 1.0, skipping LLM reranking"
                )
                most_probable = results_dict.get(results_with_scores[0]["id"])
            else:
                # Use reranking agent to select the most relevant result
                user_prompt = f"""
                Rerank the following results based on the search query:
                search query: {query},
                results: {places}
                """
                rerank_result = await rerank_agent.run(
                    user_prompt=user_prompt,
                )
                logger.info(f"Reranking result: {pformat(rerank_result.output)}")
                most_probable = results_dict.get(rerank_result.output.most_probable)
        else:
            # No scores available, use reranking
            user_prompt = f"""
            Rerank the following results based on the search query:
            search query: {query},
            results: {places}
            """
            rerank_result = await rerank_agent.run(
                user_prompt=user_prompt,
            )
            logger.info(f"Reranking result: {pformat(rerank_result.output)}")
            most_probable = results_dict.get(rerank_result.output.most_probable)
    else:
        most_probable = None

    total_time = time.time() - start_time
    logger.info(f"Simple geocode total time: {total_time} seconds")

    return {
        "query": query,
        "results": [
            {
                "geometry": most_probable["geometry"] if most_probable else None,
                "country": most_probable["country"] if most_probable else None,
                "name": most_probable["name"] if most_probable else query,
            }
        ],
    }


async def complex_geocode(query: str) -> dict:
    """Handle complex geocoding queries with spatial logic."""
    logger.info(f"Starting complex geocode for {query}")

    complex_geocode_result = await complex_geocode_query_agent.run(
        user_prompt=f"Search query: {query}"
    )

    logger.info(f"Complex geocode result: {pformat(complex_geocode_result.output)}")

    geocoding_queries = complex_geocode_result.output.queries
    input_geometries = {}

    for geocoding_query in geocoding_queries:
        # For set queries, get unsimplified geometry from the database
        # For non-set queries, allow simplification for performance
        result = await simple_geocode(geocoding_query, simplify_geometry=not complex_geocode_result.output.set_query)
        if result["results"] and result["results"][0]["geometry"]:
            input_geometries[geocoding_query] = result["results"][0]["geometry"]

    postgis_query_result = await postgis_agent.run(
        user_prompt=f"Search query: {complex_geocode_result.output.rephrased_complex_query or query}. Geometries available in the geometries table: {input_geometries.keys()}"
    )
    sql_query = postgis_query_result.output.query
    logger.info(f"PostGIS query result: {sql_query}")

    for name, geometry in input_geometries.items():
        geometry_json = json.dumps(geometry)
        create_geometries_table()
        insert_place(name, geometry_json)

    try:
        result_geometry = run_postgis_query(sql_query)
    except Exception:
        error_traceback = traceback.format_exc()
        logger.info(f"Error traceback:\n {error_traceback}")
        user_prompt = f"""
        If I have geometries of {", ".join(input_geometries.keys())},
        what's the PostGIS SQL query to answer the query: {query}?

        Modify and fix this SQL as required:
        {sql_query}

        I'm running into the following error:
        {error_traceback}
        """
        rechecked_query = await postgis_query_judgement_agent.run(
            user_prompt=user_prompt
        )
        logger.info(f"user prompt:\n {user_prompt}")
        logger.info(f"Error re-checked query: {rechecked_query.output.query}")
        result_geometry = run_postgis_query(rechecked_query.output.query)

    clear_geometries_table()

    if complex_geocode_result.output.set_query:
        # If this is a set query, we need to search for the set of results within an aoi
        results = search_subtype_within_aoi(
            subtype=complex_geocode_result.output.subtype, aoi=result_geometry
        )
        # Note: search_subtype_within_aoi already returns results with name field
    else:
        results = [
            {
                "geometry": result_geometry,
                "country": None,  # Complex queries may not have a specific country
                "name": query,  # Use the query as name for complex queries
            }
        ]

    return {
        "query": query,
        "results": results,
    }


@cached(
    prefix="unified_search",
    ttl=1800,  # 30 minutes
    cache_condition=lambda result: result
    and result.get("result")
    and result["result"].get("geometry") is not None,
)
async def search(query: str) -> dict[str, Any]:
    """
    Unified search function that handles both simple and complex queries.
    Returns a single result with geometry and country information.
    """
    logger.info(f"Starting unified search for: {query}")

    routing_result = await routing_agent.run(user_prompt=f"Search query: {query}")

    if routing_result.output.query_type == "simple":
        logger.info(f"Routing to simple geocode: {query}")
        return await simple_geocode(query)
    else:
        logger.info(f"Routing to complex geocode: {query}")
        return await complex_geocode(query)


async def main():
    test_queries = [
        "New York City",
        "London in Canada",
        "India and Sri Lanka",
        "Within 100km of Mumbai",
        "France north of Paris",
    ]

    for query in test_queries:
        print(f"\n--- Testing: {query} ---")
        result = await search(query)
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
