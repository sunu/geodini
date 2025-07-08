import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
import json
import time
from typing import Dict, Any, Optional


def main():
    st.set_page_config(
        page_title="Geodini - Natural Language Geocoding",
        page_icon="🌍",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialize session state
    if "map_data" not in st.session_state:
        st.session_state.map_data = None
    if "search_results" not in st.session_state:
        st.session_state.search_results = None
    if "query_input" not in st.session_state:
        st.session_state.query_input = ""

    st.title("🌍 Geodini")
    st.markdown("### Natural Language Geocoding API")
    st.markdown(
        "Search for places using natural language queries. Try both simple and complex queries!"
    )

    # API configuration
    api_base_url = st.sidebar.text_input(
        "API Base URL", value="http://api:9000", help="The base URL of the Geodini API"
    )

    # Examples in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💡 Example queries")

    simple_examples = [
        "Delhi",
        "New York City",
        "London in Canada",
        "Osaka, Japan",
    ]

    complex_examples = [
        "India and Sri Lanka",
        "Within 100km of Mumbai",
        "France north of Paris",
        "Area within 50km of Berlin or Paris",
    ]

    st.sidebar.markdown("**Simple queries:**")
    for example in simple_examples:
        if st.sidebar.button(
            f"📍 {example}", key=f"simple_{example}", use_container_width=True
        ):
            st.session_state.query_input = example
            search_and_display(example, api_base_url)

    st.sidebar.markdown("**Complex spatial queries:**")
    for example in complex_examples:
        if st.sidebar.button(
            f"🗺️ {example}", key=f"complex_{example}", use_container_width=True
        ):
            st.session_state.query_input = example
            search_and_display(example, api_base_url)

    # Search interface
    query = st.text_input(
        "🔍 Enter your search query:",
        value=st.session_state.query_input,
        placeholder="e.g., New York City, India and Sri Lanka, Within 100km of Mumbai...",
        help="Type a place name or spatial query",
    )

    search_button = st.button("Search", type="primary")

    if search_button and query:
        # Clear the query input after search
        st.session_state.query_input = ""
        search_and_display(query, api_base_url)

    # Only show map section after search
    if st.session_state.search_results:
        st.markdown("---")
        st.markdown("#### 🗺️ Result on Map")
        display_map()


def search_and_display(query: str, api_base_url: str):
    """Search for a query and store results in session state."""

    with st.spinner("🔍 Searching..."):
        try:
            start_time = time.time()

            # Make API request
            response = requests.get(
                f"{api_base_url}/search", params={"query": query}, timeout=30
            )

            end_time = time.time()
            query_time = end_time - start_time

            if response.status_code == 200:
                data = response.json()

                # Store results in session state
                st.session_state.search_results = {
                    "data": data,
                    "query_time": query_time,
                }

                # Update map data
                result = data.get("result", {})
                geometry = result.get("geometry")
                if geometry:
                    st.session_state.map_data = geometry
                else:
                    st.session_state.map_data = None

            else:
                st.error(f"API Error: {response.status_code} - {response.text}")
                st.session_state.search_results = None
                st.session_state.map_data = None

        except requests.exceptions.ConnectionError:
            st.error(
                "❌ Could not connect to the API. Make sure the API server is running."
            )
            st.session_state.search_results = None
            st.session_state.map_data = None
        except requests.exceptions.Timeout:
            st.error("⏱️ Request timed out. Please try again.")
            st.session_state.search_results = None
            st.session_state.map_data = None
        except Exception as e:
            st.error(f"❌ An error occurred: {str(e)}")
            st.session_state.search_results = None
            st.session_state.map_data = None


def display_map():
    """Display the map with current data from session state."""

    # Show search results info if available
    if st.session_state.search_results:
        data = st.session_state.search_results["data"]
        query_time = st.session_state.search_results["query_time"]

        # Show query info
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"**Query:** {data.get('query', 'N/A')}")

        with col2:
            st.markdown(f"**Time:** {query_time:.2f}s")

        result = data.get("result", {})
        geometry = result.get("geometry")
        country = result.get("country")

        if geometry:
            # Display result info
            st.success("✅ Found result!")

            # Show metadata
            if country:
                st.markdown(f"**Country:** {country}")

            # Show raw geometry data in expander
            with st.expander("🔍 Raw Geometry Data"):
                st.json(geometry)
        else:
            st.warning("⚠️ No geometry data found for this query.")

            # Show raw response
            with st.expander("🔍 Raw Response"):
                st.json(data)

    # Create and display map
    if st.session_state.map_data:
        # Create map with search results
        map_obj = create_map_with_geometry(st.session_state.map_data)
        if map_obj:
            st_folium(map_obj, width=700, height=500, key="result_map")
        else:
            st.error("Could not create map visualization")
    else:
        # Show message when no geometry is available
        st.info("🗺️ No geometry data available for visualization")


def create_map_with_geometry(geometry: Dict[str, Any]) -> Optional[folium.Map]:
    """Create a Folium map with the given geometry."""

    try:
        # Create map
        m = folium.Map(location=[0, 0], zoom_start=2)

        # Add geometry to map
        folium.GeoJson(
            geometry,
            style_function=lambda _: {
                "fillColor": "#3498db",
                "color": "#2980b9",
                "weight": 2,
                "fillOpacity": 0.3,
                "opacity": 0.8,
            },
            tooltip=folium.Tooltip("Search Result"),
        ).add_to(m)

        # Fit map to geometry bounds
        if geometry.get("type") == "Point":
            coords = geometry["coordinates"]
            m.location = [coords[1], coords[0]]
            m.zoom_start = 10
        else:
            # For polygons and other geometries, try to fit bounds
            try:
                from shapely.geometry import shape

                geom_shape = shape(geometry)
                bounds = geom_shape.bounds

                # bounds are (minx, miny, maxx, maxy)
                sw = [bounds[1], bounds[0]]  # [min_lat, min_lon]
                ne = [bounds[3], bounds[2]]  # [max_lat, max_lon]

                m.fit_bounds([sw, ne])

            except Exception:
                # Fallback: try to get center from coordinates
                if "coordinates" in geometry:
                    coords = geometry["coordinates"]
                    if coords and len(coords) > 0:
                        if isinstance(coords[0], list):
                            # Multi-dimensional coordinates
                            flat_coords = flatten_coordinates(coords)
                            if flat_coords:
                                center_lat = sum(
                                    coord[1] for coord in flat_coords
                                ) / len(flat_coords)
                                center_lon = sum(
                                    coord[0] for coord in flat_coords
                                ) / len(flat_coords)
                                m.location = [center_lat, center_lon]
                                m.zoom_start = 8

        return m

    except Exception as e:
        st.error(f"Error creating map: {str(e)}")
        return None


def flatten_coordinates(coords) -> list:
    """Flatten nested coordinate arrays."""
    result = []

    def _flatten(item):
        if isinstance(item, list):
            if (
                len(item) == 2
                and isinstance(item[0], (int, float))
                and isinstance(item[1], (int, float))
            ):
                # This is a coordinate pair
                result.append(item)
            else:
                # This is a nested structure
                for sub_item in item:
                    _flatten(sub_item)

    _flatten(coords)
    return result


if __name__ == "__main__":
    main()
