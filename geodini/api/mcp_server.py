from mcp.server.fastmcp import FastMCP

from geodini.agents.geocoder_agent import search, simplify_geometry

server = FastMCP("PydanticAI Server", port=9001)


@server.tool()
async def geocode(query: str) -> str:
    """Geocode a query and download the geojson geometry"""
    result = await search(query)
    if "result" in result and "geometry" in result["result"]:
        return simplify_geometry(result["result"]["geometry"], tolerance_m=1000)
    return "No geometry found for query"


if __name__ == "__main__":
    server.run(transport="sse")
