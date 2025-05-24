from mcp.server.fastmcp import FastMCP

from geodini.agents.complex_agents import geocode_complex, simplify_geometry

server = FastMCP('PydanticAI Server', port=9001)



@server.tool()
async def geocode(query: str) -> str:
    """Geocode a complex query and download the geojson geometry"""
    geometry = await geocode_complex(query)
    if "geometry" in geometry:
        return simplify_geometry(geometry["geometry"], tolerance_m=1000)
    return simplify_geometry(geometry, tolerance_m=1000)


if __name__ == '__main__':
    server.run(transport='sse')