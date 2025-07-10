import os
import time
from typing import Optional

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium


API_URL = os.getenv("API_URL", "http://api:9000")


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
        "API Base URL", value=f"{API_URL}", help="The base URL of the Geodini API"
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

    set_examples = [
        "regions in India",
        "localities within 100km of Mumbai",
        "localadmin in California",
        "localities in France",
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

    st.sidebar.markdown("**Set queries (multiple results):**")
    for example in set_examples:
        if st.sidebar.button(
            f"📋 {example}", key=f"set_{example}", use_container_width=True
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

                # Update map data - store results with names for map display
                results = data.get("results", [])
                if results:
                    st.session_state.map_data = results
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

        # Handle results list
        results = data.get("results", [])
        if results:
            # Display multiple results
            st.success(f"✅ Found {len(results)} result(s)!")

            # Display results in tabs or expandable sections
            if len(results) == 1:
                result = results[0]
                geometry = result.get("geometry")
                country = result.get("country")
                name = result.get("name")

                # Show metadata
                if name:
                    st.markdown(f"**Name:** {name}")
                if country:
                    st.markdown(f"**Country:** {country}")

                # Show raw geometry data in expander
                with st.expander("🔍 Raw Geometry Data"):
                    st.json(geometry)
            else:
                # Multiple results - show all results
                st.markdown(f"**Results Count:** {len(results)}")

                # Put all results under an expander
                with st.expander(f"📋 View All {len(results)} Results", expanded=False):
                    # Show all results with basic info
                    for i, result in enumerate(results):
                        geometry = result.get("geometry")
                        country = result.get("country")
                        name = result.get("name", f"Result {i+1}")

                        with st.expander(
                            f"📍 {name}" + (f" ({country})" if country else "")
                        ):
                            col1, col2 = st.columns(2)
                            with col1:
                                if country:
                                    st.markdown(f"**Country:** {country}")
                            with col2:
                                if geometry:
                                    st.markdown(
                                        f"**Type:** {geometry.get('type', 'Unknown')}"
                                    )

                            # Put JSON data under a toggle to save space
                            with st.expander("🔍 View Geometry JSON", expanded=False):
                                if geometry:
                                    st.json(geometry)
                                else:
                                    st.warning("No geometry data")
        else:
            st.warning("⚠️ No results found for this query.")

            # Show raw response
            with st.expander("🔍 Raw Response"):
                st.json(data)

    # Create and display map
    if st.session_state.map_data:
        # Create map with search results (now handles multiple geometries)
        map_obj = create_map_with_geometries(st.session_state.map_data)
        if map_obj:
            st_folium(map_obj, width=700, height=500, key="result_map")
        else:
            st.error("Could not create map visualization")
    else:
        # Show message when no geometry is available
        st.info("🗺️ No geometry data available for visualization")


def create_map_with_geometries(results: list) -> Optional[folium.Map]:
    """Create a Folium map with multiple result objects containing geometries and names."""

    try:
        # Create map
        m = folium.Map(location=[0, 0], zoom_start=2)

        # Colors for different results
        colors = [
            "#3498db",
            "#e74c3c",
            "#2ecc71",
            "#f39c12",
            "#9b59b6",
            "#1abc9c",
            "#34495e",
            "#e67e22",
        ]

        all_bounds = []

        # Add each result to map
        for i, result in enumerate(results):
            geometry = result.get("geometry")
            name = result.get("name", f"Result {i+1}")
            country = result.get("country")

            if not geometry:
                continue

            color = colors[i % len(colors)]

            # Create tooltip text with name and country
            tooltip_text = name
            if country:
                tooltip_text += f" ({country})"

            # Add geometry to map
            folium.GeoJson(
                geometry,
                style_function=lambda _, color=color: {
                    "fillColor": color,
                    "color": color,
                    "weight": 2,
                    "fillOpacity": 0.3,
                    "opacity": 0.8,
                },
                tooltip=folium.Tooltip(tooltip_text),
            ).add_to(m)

            # Collect bounds for fitting
            try:
                from shapely.geometry import shape

                geom_shape = shape(geometry)
                bounds = geom_shape.bounds
                all_bounds.append(bounds)
            except Exception:
                pass

        # Fit map to all geometries
        if all_bounds:
            # Calculate overall bounds
            min_x = min(b[0] for b in all_bounds)
            min_y = min(b[1] for b in all_bounds)
            max_x = max(b[2] for b in all_bounds)
            max_y = max(b[3] for b in all_bounds)

            sw = [min_y, min_x]  # [min_lat, min_lon]
            ne = [max_y, max_x]  # [max_lat, max_lon]

            m.fit_bounds([sw, ne])
        elif len(results) == 1:
            # Single result fallback
            geometry = results[0].get("geometry")
            if geometry and geometry.get("type") == "Point":
                coords = geometry["coordinates"]
                m.location = [coords[1], coords[0]]
                m.zoom_start = 10

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
