import logging
import os
from typing import Any

import dotenv
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from geodini.agents.complex_agents import geocode_complex
from geodini.agents.simple_geocoder_agent import search_places
from geodini.agents.utils.postgis_exec import get_postgis_connection


logger = logging.getLogger(__name__)

# Load environment variables
dotenv.load_dotenv()

# Create FastAPI app
app = FastAPI(
    title="Geodini API",
    description="API for geospatial data search using Geodini",
    version="0.1.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/")
async def root():
    """Root endpoint that returns basic API information."""
    return {
        "name": "Geodini API",
        "version": "0.1.0",
        "description": "API for geospatial data search using Geodini",
    }


@app.get("/search")
async def search(
    query: str = Query(..., description="The search query string"),
) -> dict[str, Any]:
    """
    Search for a place in the Overture divisions data.

    Returns search results based on the provided query and parameters.
    """
    try:
        search_term = query

        logger.info(f"Search term: {search_term}")

        # Get dictionary result from search tool
        result = await search_places(search_term)

        return result

    except Exception as e:
        logger.exception(f"Error searching divisions data: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error searching divisions data: {str(e)}"
        )


@app.get("/search_complex")
async def search_complex(
    query: str = Query(
        ...,
        description="The complex search query string containing spatial logic and operators",
    ),
) -> dict[str, Any]:
    """
    Search for places using complex spatial queries.

    Handles queries containing spatial logic and operators like:
    - "India and Sri Lanka"
    - "Within 100km of Mumbai"
    - "Within 10kms of France and Spain border"

    Returns search results based on the provided complex query.
    """
    try:
        logger.info(f"Searching with complex query: {query}")

        # Get result from complex search tool
        result = await geocode_complex(query)

        return {
            "query": query,
            "result": {
                "geometry": result,
                "country": None,
            },
        }

    except Exception as e:
        logger.exception(f"Error processing complex search query: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error processing complex search query: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the API is running."""
    try:
        # Test PostGIS connection
        conn = get_postgis_connection()
        if conn is None:
            raise Exception("PostGIS connection failed")
        # execute a simple query to check the connection
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
            if result[0] != 1:
                raise Exception("PostGIS failed to execute test query")
    except Exception as e:
        logger.exception(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
    finally:
        if "conn" in locals() and conn is not None:
            conn.close()
    return {"status": "healthy"}


if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 9000))

    # Run the FastAPI app with uvicorn
    uvicorn.run("geodini.api.api:app", host="0.0.0.0", port=port, reload=True)
