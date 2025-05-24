import asyncio
import re
import json
from pprint import pprint, pformat
from dataclasses import dataclass
from typing import List, Optional, Callable, Dict, Any, Literal
from pydantic_ai import Agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from shapely.geometry import shape, mapping
from shapely.ops import transform
from pyproj import Transformer
import numpy
from pydantic_ai.mcp import MCPServerStdio
import traceback


from geodini.agents.simple_geocoder_agent import search_places, SearchContext
from geodini.agents.utils.duckdb_exec import duckdb_sanbox
from geodini.agents.utils.postgis_exec import (
    postgis_agent, run_postgis_query, insert_place, clear_geometries_table, postgis_query_judgement_agent
)

run_python_server_params = StdioServerParameters(
    command='deno',
    args=[
        'run',
        '-N',
        '-R=node_modules',
        '-W=node_modules',
        '--node-modules-dir=auto',
        'jsr:@pydantic/mcp-run-python',
        'stdio',
    ],
)

server = MCPServerStdio(  
    'deno',
    args=[
        'run',
        '-N',
        '-R=node_modules',
        '-W=node_modules',
        '--node-modules-dir=auto',
        'jsr:@pydantic/mcp-run-python',
        'stdio',
    ]
)
python_agent = Agent('openai:gpt-4o', mcp_servers=[server])

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

def clip_coordinates_with_rounding(geojson: Dict[str, Any]) -> Dict[str, Any]:
    converted = recursively_convert(geojson)
    return converted


def simplify_geometry(geometry: Dict[str, Any], tolerance_m: float = 10000) -> Dict[str, Any]:
    to_meters = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    to_degrees = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform

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
    "openai:gpt-4o-mini",
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
    queries: List[str]


@dataclass
class ComplexQueryContext:
    query: str

complex_geocode_query_agent = Agent(
    "openai:gpt-4o-mini",
    output_type=ComplexGeocodeResult,
    deps_type=ComplexQueryContext,
    system_prompt="""
        Given the search query, return ALL relevant places to search for in the query.

        For example, if the query is "Within 100km of Mumbai", return ["Mumbai"].
        for "Either in Canada or in the US", return ["Canada", "US"].
        for "France north of Paris", return ["France", "Paris"].
    """,
)

@dataclass
class PythonCodeResult:
    code: str

@dataclass
class PythonCodeContext:
    query: str
    input_geometry_names: List[str]


python_code_agent = Agent(
    "openai:gpt-4o",
    output_type=PythonCodeResult,
    deps_type=PythonCodeContext,
    system_prompt="""
        You are a geospatial python code agent. 

        You have been supplied a query and a dict of input geometries of the form:
        {
            "name1": <polygon_geojson_dict>,
            "name2": <polygon_geojson_dict>,
            ...
        }

        polygon_geojson_dict is a dictionary with the following keys: type, coordinates

        You need to return a python code with a function that takes in the `input` and returns the geojson geometry of the AOI related to the query.

        Note that we dont need to answer the query, just construct the geometry of the AOI.
        Use shapely, pyproj if needed to perform any spatial operations required.
        Reproject geometry from EPSG:4326 to EPSG:3857, apply any spatial operation in projected coordinates, then reproject the result back to EPSG:4326.

        Name the function `get_geometry`. Make sure it takes in `input_geometries` as an argument and returns the resulting geometry.
        Include the import statements inside the function.
        Return only the resulting geojson geometry in full, nothing else.
    """
)

async def execute_python_code(code: str, input_geometries: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the python code and return the result.
    """
    async with stdio_client(run_python_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            calling_code = f"""
input_geometries = {input_geometries}

{code}

get_geometry(input_geometries)
            """
            await session.initialize()
            result = await session.call_tool('run_python_code', {'python_code': calling_code})
            print(result.content[0].text)
            output_match = re.search(r'<return_value>\s*(.*?)\s*</return_value>', result.content[0].text, re.DOTALL)
            output  = json.loads(output_match.group(1))
            print(f"Output: {output}")
            return output


@dataclass
class DuckDBQueryResult:
    query: str

duckdb_agent = Agent(
    "openai:gpt-4o",
    output_type=DuckDBQueryResult,
    system_prompt="""
        You have access to a duckdb database with a table `place` that has the following columns: name, geojson.
        
        For the given user query, return the duckdb query to execute to construct the geojson geometry of the AOI related to the query as a single geojson geometry.
        Use the `ST_GeomFromGeoJSON` function to construct the geometry from the geojson string.
        Use ST_Transform(geometry, 'EPSG:4326', 'EPSG:3857') and ST_Transform(geometry, 'EPSG:3857', 'EPSG:4326') to reproject the geometry to and from EPSG:3857 as required.
        Note that ST_Transform will always expect two SRID arguments. Explicitly specify both the source and target SRIDs
        Use ST_AsGeoJSON(geometry) to return the final geojson geometry.
        Do not use transforms unnecessarily if not required.
        Return only the duckdb SQL query, nothing else.

        Some duckdb caveats to note:
        - `ST_Union` works with two geometries. Use `ST_Union_Agg` to union multiple geometries.
        - While transforming geometries, make sure reprojections are not applied to already projected geometries.
    """
)

duckdb_query_judgement_agent = Agent(
    "openai:gpt-4o",
    output_type=DuckDBQueryResult,
    system_prompt="""
        You are an expert in duckdb and SQL. Given the user's query, check and fix the given duckdb SQL query
        if needed and return the correct duckdb SQL query.

        If the query is already correct, return the query as is.

        Return only the duckdb SQL query, nothing else.

        Some duckdb caveats to note:
        - the data is in place table in geojson format. Has the following columns: name, geojson.
        - `ST_Union` works with two geometries. Use `ST_Union_Agg` to union multiple geometries.
        - When requesting borders, we are interested in shared borders between the geometries. Use `ST_Intersection` to get the shared borders.
        - For any spatial operation, make sure to reproject the geometries to EPSG:3857 before performing the operation, and then reproject the result back to EPSG:4326 for the final result.
        - ST_Transform will always expect two SRID arguments. And the SRID will of the form 'EPSG:4326' or 'EPSG:3857' etc

        Here are some examples of queries and the correct duckdb SQL query:
        - Query: "10km within the border of France and Spain"
        - SQL: SELECT ST_AsGeoJSON(ST_Transform(ST_Buffer(ST_Intersection(
                (SELECT ST_Union_Agg(ST_Transform(ST_GeomFromGeoJSON(geojson), 'EPSG:4326', 'EPSG:3857')) FROM place WHERE name = 'France'),
                (SELECT ST_Union_Agg(ST_Transform(ST_GeomFromGeoJSON(geojson), 'EPSG:4326', 'EPSG:3857')) FROM place WHERE name = 'Spain')
            ), 10000), 'EPSG:3857', 'EPSG:4326')) AS border_buffer_10km
        - Query: "India east of Delhi"
        - SQL: WITH
                delhi_x AS (
                    SELECT ST_XMax(ST_GeomFromGeoJSON(geojson)) AS x
                    FROM place
                    WHERE name = 'Delhi'
                ),
                india AS (
                    SELECT ST_GeomFromGeoJSON(geojson) AS geom
                    FROM place
                    WHERE name = 'India'
                )
                SELECT ST_AsGeoJSON(
                ST_Intersection(
                    india.geom,
                    ST_MakeEnvelope(delhi_x.x, -90, 180, 90)
                )
                ) AS geojson
                FROM india, delhi_x;
    """
)


async def geocode_complex(query: str) -> Dict[str, Any]:
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
        pprint(results["most_probable"])
        return results.get("most_probable", None)
    else:
        print(f"Complex query: {query}")
        complex_geocode_result = await complex_geocode_query_agent.run(
            user_prompt=f"Search query: {query}",
            deps=ComplexQueryContext(query=query),
        )
        geocoding_queries = complex_geocode_result.output.queries
        print(f"Complex geocode result: {geocoding_queries}")
        input_geometries = {}
        for geocoding_query in geocoding_queries:
            result = await search_places(geocoding_query)
            # input_geometries[geocoding_query] = simplify_geometry(result["most_probable"]["geometry"])
            # when using duckdb, dont need to simplify as much
            input_geometries[geocoding_query] = simplify_geometry(result["most_probable"]["geometry"], 1000)

        ## Python Coding Agent

        # code_result = await python_code_agent.run(
        #     user_prompt=f"Search query: {query}, keys in input_geometries: {input_geometries.keys()}",
        #     deps=PythonCodeContext(query=query, input_geometry_names=list(input_geometries.keys())),
        # )
        # print(f"Python code result: {code_result.output.code}")
        # result = await execute_python_code(code_result.output.code, input_geometries)
        # print(f"Result: {result}")

        ## Python MCP Server

        # input_geometries_xml = "\n".join([f"<{name}>\n{input_geometry}\n</{name}>\n" for name, input_geometry in input_geometries.items()])

        # user_prompt=f"""
        #     <input-geometries>
        #     {input_geometries_xml}
        #     </input-geometries>

        #     <user-query>
        #     {query}
        #     </user-query>

        #     <instructions>
        #     Given the user query and input geometries, check if we need to apply any spatial operation to the input geometries.
            
        #     Calculate the AOI geometry from the input geometries for the query using shapely and geopandas if any spatial operation is needed.

        #     Reproject geometry from EPSG:4326 to EPSG:3857, apply any spatial operation in projected coordinates, then reproject the result back to EPSG:4326.

        #     Return only the resulting geojson geometry in full, nothing else.
        #     </instructions>
        # """

        # print(f"User prompt: {user_prompt}")
        # async with python_agent.run_mcp_servers():
        #     result = await python_agent.run(
        #         user_prompt=user_prompt,
        #     )
        #     print(result.output)

        ## DuckDB Agent

        # duckdb_query_result = await duckdb_agent.run(
        #     user_prompt=f"Search query: {query}. Geometries available in the place table: {input_geometries.keys()}"
        # )
        # sql_query = duckdb_query_result.output.query
        # print(f"DuckDB query result: {sql_query}")
        # checked_query = await duckdb_query_judgement_agent.run(
        #     user_prompt=f"""
        #     If I have geometries of {", ".join(input_geometries.keys())},
        #     what's the duckdb SQL query to answer the query {query}?

        #     Modify and fix this SQL as required:
        #     {sql_query}
        #     """
        # )
        # print(f"Checked query: {checked_query.output.query}")
        # try:
        #     result = duckdb_sanbox(input_geometries, checked_query.output.query)
        #     # print(f"Result: {result}")
        # except Exception as e:
        #     error_traceback = traceback.format_exc()
        #     print(f"Error traceback:\n {error_traceback}")
        #     user_prompt = f"""
        #     If I have geometries of {", ".join(input_geometries.keys())},
        #     what's the duckdb SQL query to answer the query {query}?

        #     Modify and fix this SQL as required:
        #     {checked_query.output.query}

        #     I'm running into the following error:
        #     {error_traceback}
        #     """
        #     rechecked_sql_query = await duckdb_query_judgement_agent.run(
        #         user_prompt=user_prompt
        #     )
        #     print(f"user prompt:\n {user_prompt}")
        #     print(f"Error re-checked query: {rechecked_sql_query.output.query}")
        #     result = duckdb_sanbox(input_geometries, rechecked_sql_query.output.query)

#         sql_query = """


# """
#         print(f"SQL query: {sql_query}")
#         print(f"Input geometries: {input_geometries.keys()}")
#         result = duckdb_sanbox(input_geometries, sql_query)


        ## PostGIS Agent
        postgis_query_result = await postgis_agent.run(
            user_prompt=f"Search query: {query}. Geometries available in the geometries table: {input_geometries.keys()}"
        )
        sql_query = postgis_query_result.output.query
        print(f"PostGIS query result: {sql_query}")
        for name, geometry in input_geometries.items():
            # Convert geometry dictionary to GeoJSON string
            geometry_json = json.dumps(geometry)
            insert_place(name, geometry_json)
        # result = run_postgis_query(sql_query)

        # checked_query = await postgis_query_judgement_agent.run(
        #     user_prompt=f"""
        #     If I have geometries of {", ".join(input_geometries.keys())},
        #     what's the PostGIS SQL query to answer the query: {query}?

        #     Modify and fix this SQL as required:
        #     {sql_query}
        #     """
        # )
        # print(f"Checked query: {checked_query.output.query}")
        try:
            result = run_postgis_query(sql_query)
        except Exception as e:
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
