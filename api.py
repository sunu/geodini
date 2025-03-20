from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any
import uvicorn
import os
import dotenv
import pluggy

from geodini.tools.agents import search_places


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
) -> Dict[str, Any]:
    """
    Search for a place in the Overture divisions data.

    Returns search results based on the provided query and parameters.
    """
    try:
        search_term = query

        print(f"Search term: {search_term}")

        # Get dictionary result from search tool
        result = await search_places(search_term)

        return result

    except Exception as e:
        print(f"Error searching divisions data: {str(e)}")
        import traceback

        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Error searching divisions data: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the API is running."""
    return {"status": "healthy"}


if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 9000))

    # Run the FastAPI app with uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
