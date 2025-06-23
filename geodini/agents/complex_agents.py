import asyncio
import json
import traceback
from dataclasses import dataclass
from pprint import pprint  # noqa: F401
from typing import Any, Literal

from pydantic_ai import Agent
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from geodini.agents.simple_geocoder_agent import search_places
from geodini.agents.utils.postgis_exec import (
    clear_geometries_table,
    create_geometries_table,
    insert_place,
    postgis_agent,
    postgis_query_judgement_agent,
    run_postgis_query,
)


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

    # Apply new rounding logic
    geojson = clip_coordinates_with_rounding(geojson_raw)

    print(f"Simplified geometry: {geojson}")
    return geojson


@dataclass
class RoutingResult:
    query_type: Literal["simple", "complex"]


@dataclass
class RoutingContext:
    query: str


routing_agent = Agent(
    "openai:gpt-4.1-mini",
    output_type=RoutingResult,
    deps_type=RoutingContext,
    system_prompt="""
        Given the search query, determine if it is a simple or complex query.
        A simple query is directly geocodable location description. For example: "New York City", "London in Canada", "India"
        A complex query contains spatial logic and operators. For example: "India and Sri Lanka", "Within 100km of Mumbai", "France north of Paris"
    """,
)


@dataclass
class ComplexGeocodeResult:
    queries: list[str]


@dataclass
class ComplexQueryContext:
    query: str


complex_geocode_query_agent = Agent(
    "openai:gpt-4.1-mini",
    output_type=ComplexGeocodeResult,
    deps_type=ComplexQueryContext,
    system_prompt="""
        Given the search query, return ALL relevant places to search for in the query.

        For example, if the query is "Within 100km of Mumbai", return ["Mumbai"].
        for "Either in Canada or in the US", return ["Canada", "US"].
        for "France north of Paris", return ["France", "Paris"].
    """,
)


async def geocode_complex(query: str) -> dict[str, Any]:
    """
    Geocode a complex query containing spatial logic and operators.
    """

    routing_result = await routing_agent.run(
        user_prompt=f"Search query: {query}",
        deps=RoutingContext(query=query),
    )
    if routing_result.output.query_type == "simple":
        print(f"Simple query: {query}")
        results = await search_places(query)
        most_probable = results.get("most_probable", {})
        return most_probable.get("geometry", None)
    else:
        print(f"Complex query: {query}")
        complex_geocode_result = await complex_geocode_query_agent.run(
            user_prompt=f"Search query: {query}",
            deps=ComplexQueryContext(query=query),
        )
        geocoding_queries = complex_geocode_result.output.queries
        input_geometries = {}
        for geocoding_query in geocoding_queries:
            result = await search_places(geocoding_query)
            # input_geometries[geocoding_query] = simplify_geometry(result["most_probable"]["geometry"])
            # when using duckdb, dont need to simplify as much
            input_geometries[geocoding_query] = simplify_geometry(
                result["most_probable"]["geometry"], 1000
            )

        ## PostGIS Agent
        postgis_query_result = await postgis_agent.run(
            user_prompt=f"Search query: {query}. Geometries available in the geometries table: {input_geometries.keys()}"
        )
        sql_query = postgis_query_result.output.query
        print(f"PostGIS query result: {sql_query}")
        for name, geometry in input_geometries.items():
            # Convert geometry dictionary to GeoJSON string
            geometry_json = json.dumps(geometry)
            create_geometries_table()
            insert_place(name, geometry_json)

        try:
            result = run_postgis_query(sql_query)
        except Exception:
            error_traceback = traceback.format_exc()
            print(f"Error traceback:\n {error_traceback}")
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
            print(f"user prompt:\n {user_prompt}")
            print(f"Error re-checked query: {rechecked_query.output.query}")
            result = run_postgis_query(rechecked_query.output.query)
        clear_geometries_table()

        return result


async def main():
    # query = "India north of Mumbai"
    # query = "Area within 100kms to 200kms of Paris - not nearer than 100kms but not further than 200kms"
    # query = "the great city of New York"
    # query = "France north of Paris (means latitude north of Paris)"
    query = "Area within 100kms Paris or Berlin"
    # query = "Northern part of India"
    await geocode_complex(query)


if __name__ == "__main__":
    asyncio.run(main())
