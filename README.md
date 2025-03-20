# Geodini CLI

A powerful command line interface tool built with Python.

## Installation

This project uses `uv` for dependency management. To install:

```bash
# Create a new virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Unix/macOS
uv pip install -e .
```

## Usage

After installation, you can use the CLI with the following commands:

```bash
# Say hello
geodini hello
geodini hello "Your Name"

# Check version
geodini version
```

## Development

To set up the development environment:

1. Clone the repository
2. Create a virtual environment with `uv venv`
3. Activate the virtual environment: `source .venv/bin/activate`
4. Install dependencies with `uv pip install -e .`

## Download Overture Data

To download the Overture data, run the following command:

```bash
duckdb < scripts/download_overture_data.sql
```

## API

Geodini also provides a REST API for accessing the search functionality.

### Running the API

To start the API server:

```bash
# Activate your virtual environment first
source .venv/bin/activate  # On Unix/macOS

# Start the API server
python api.py
```

By default, the server runs on http://localhost:8000. You can change the port by setting the `PORT` environment variable.

### API Endpoints

- `GET /`: Root endpoint with API information
- `GET /search`: Search for places with various parameters
  - Query Parameters:
    - `query` (required): The search query string
    - `limit` (optional): Maximum number of results to return (default: 100)
    - `exact` (optional): Whether to perform an exact match (default: false)
    - `country_code` (optional): ISO country code to filter results (e.g., 'US', 'CA')
    - `include_geometry` (optional): Whether to include geometry data as GeoJSON (default: false)
    - `rank` (optional): Whether to use OpenAI to rank results by relevance (default: false)
    - `smart_parse` (optional): Whether to use OpenAI to parse the query for parameters (default: false)
    - `api_key` (optional): OpenAI API key (will use environment variable if not provided)
- `GET /health`: Health check endpoint

### Example API Usage

```bash
# Basic search
curl "http://localhost:8000/search?query=San%20Francisco"

# Search with country filter and geometry
curl "http://localhost:8000/search?query=London&country_code=GB&include_geometry=true"

# Search with AI ranking and smart parsing
curl "http://localhost:8000/search?query=capital%20of%20France&rank=true&smart_parse=true"
```

## Frontend

Geodini also includes a web frontend for easy interaction with the API.

### Running the Frontend

The frontend is a simple static web application that can be served using any web server. For development, you can use Python's built-in HTTP server:

```bash
# Navigate to the frontend directory
cd frontend

# Start a simple HTTP server
python -m http.server 8080
```

Then open your browser and navigate to http://localhost:8080

### Frontend Features

- Modern, responsive UI
- Search for places with all available API parameters
- View results in a clean, sortable table
- View place geometries on an interactive map
- Enhanced AI ranking visualization:
  - Most probable match highlighted in purple with a star icon
  - Next probable matches highlighted in blue with rank indicators
  - Progressively fading highlight for lower-ranked matches
- Mobile-friendly design

### Using the Frontend with a Different API Server

By default, the frontend connects to the API at http://localhost:8000. If your API is running on a different host or port, you can modify the `API_BASE_URL` variable in the `frontend/app.js` file.

## License

MIT License - see the LICENSE file for details.