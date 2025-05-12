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


from geodini.tools.agents import search_places, SearchContext
from geodini.tools.utils.duckdb_exec import duckdb_sanbox

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
        Use ST_AsGeoJSON(geometry) to return the final geojson geometry.
        Return only the duckdb SQL query, nothing else.

        Some duckdb caveats to note:
        - `ST_Union` works with two geometries. Use `ST_Union_Agg` to union multiple geometries.
        - While transforming geometries, make sure reprojections are not applied to already projected geometries.
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
            input_geometries[geocoding_query] = simplify_geometry(result["most_probable"]["geometry"])

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

        duckdb_query_result = await duckdb_agent.run(
            user_prompt=f"Search query: {query}. Geometries available in the place table: {input_geometries.keys()}"
        )
        print(f"DuckDB query result: {duckdb_query_result.output.query}")
        result = duckdb_sanbox(input_geometries, duckdb_query_result.output.query)
        print(f"Result: {result}")


        return complex_geocode_result.output.queries


async def main():
    # query = "India north of Mumbai"
    # query = "Area within 100kms to 200kms of Paris - not nearer than 100kms but not further than 200kms"
    # query = "the great city of New York"
    query = "France north of Paris (means latitude north of Paris)"
    # query = "Area within 100kms Paris or Berlin"
    await geocode_complex(query)


if __name__ == "__main__":
    asyncio.run(main())
