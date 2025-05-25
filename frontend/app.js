// Configuration
// const API_BASE_URL = 'http://localhost:9000'; // Change this to match your API server
const API_BASE_URL = "https://api.geodini.labs.sunu.in"; // Change this to match your API server

// DOM Elements
let searchForm;
let searchQuery;
let resultsContainer;
let resultsBody;
let resultCount;
let queryTime;
let noResults;
let mapDrawer;
let mapTitle;
let closeMap;
let overlay;
let loading;
let searchInfo;

// Map instance
let map = null;

// Store search results
let searchResults = [];

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // Initialize DOM elements
  searchForm = document.getElementById("search-form");
  searchQuery = document.getElementById("search-query");
  resultsContainer = document.getElementById("results-container");
  resultsBody = document.getElementById("results-body");
  resultCount = document.getElementById("result-count");
  queryTime = document.getElementById("query-time");
  noResults = document.getElementById("no-results");
  mapDrawer = document.getElementById("map-drawer");
  mapTitle = document.getElementById("map-title");
  closeMap = document.getElementById("close-map");
  overlay = document.getElementById("overlay");
  loading = document.getElementById("loading");
  searchInfo = document.getElementById("search-info");

  // Initialize the map
  initMap();

  // Form submission
  searchForm.addEventListener("submit", handleSearch);

  // Close map drawer
  closeMap.addEventListener("click", closeMapDrawer);
  overlay.addEventListener("click", closeMapDrawer);

  // Clear search and reset UI when search input is cleared
  searchQuery.addEventListener("input", (e) => {
    if (e.target.value === "") {
      resetSearchUI();
      updateURLParams("");
    }
  });

  // Check for search query in URL parameters
  const urlParams = new URLSearchParams(window.location.search);
  const query = urlParams.get("q");
  if (query) {
    searchQuery.value = query;
    handleSearch(new Event("submit"));
  }

  // Add click handlers for example queries
  document.querySelectorAll(".clickable-example").forEach((example) => {
    example.addEventListener("click", () => {
      const query = example.dataset.query;
      searchQuery.value = query;
      handleSearch(new Event("submit"));
    });
  });
});

// Initialize Leaflet map
function initMap() {
  // Create map instance if it doesn't exist
  if (!map) {
    map = L.map("map").setView([0, 0], 2);

    // Add OpenStreetMap tile layer
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
  }
}

// Update URL with search parameters
function updateURLParams(query) {
  const url = new URL(window.location);
  if (query) {
    url.searchParams.set("q", query);
  } else {
    url.searchParams.delete("q");
  }
  window.history.pushState({}, "", url);
}

// Handle search form submission
async function handleSearch(event) {
  event.preventDefault();

  const query = searchQuery.value.trim();

  // Update URL with search query
  updateURLParams(query);

  // Show loading indicator
  loading.classList.remove("hidden");

  // Build query parameters
  const params = new URLSearchParams({
    query: query,
  });

  try {
    // Make API request
    const response = await fetch(`${API_BASE_URL}/search?${params.toString()}`);

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    const data = await response.json();

    // Store results for later use
    searchResults = data.results || [];

    // Display results
    displayResults(data);
  } catch (error) {
    console.error("Error fetching search results:", error);
    alert(`Error: ${error.message}`);
  } finally {
    // Hide loading indicator
    loading.classList.add("hidden");
  }
}

// Reset search UI to initial state
function resetSearchUI() {
  resultsContainer.classList.add("hidden");
  searchInfo.classList.remove("hidden");
}

// Display search results
function displayResults(data) {
  // Clear previous results
  resultsBody.innerHTML = "";

  // Hide search info section
  searchInfo.classList.add("hidden");

  // Update result metadata
  resultCount.textContent = `${data.results.length} results found`;
  queryTime.textContent = `Query time: ${data.time_taken.toFixed(2)}s`;

  // Get AI preferred result ID if ranking was enabled
  let aiPreferredId = null;
  let aiNextProbableIds = [];

  if (data.most_probable) {
    aiPreferredId = data.most_probable.id;
  }

  if (data.next_probable && Array.isArray(data.next_probable)) {
    aiNextProbableIds = data.next_probable.map((place) => place.id);
  }

  // Show/hide appropriate containers
  if (data.results.length > 0) {
    resultsContainer.classList.remove("hidden");
    noResults.classList.add("hidden");

    // Remove any existing AI ranking info banners
    const existingAiInfoElements =
      document.querySelectorAll(".ai-ranking-info");
    existingAiInfoElements.forEach((element) => element.remove());

    // Add AI ranking info if available
    if (data.most_probable || data.next_probable) {
      const aiInfoElement = document.createElement("div");
      aiInfoElement.className = "ai-ranking-info";
      aiInfoElement.innerHTML = `
                <div class="ai-badge">
                    <i class="fas fa-robot"></i> AI Ranked
                </div>
                <div class="ai-explanation">
                    Results have been ranked by AI. The most probable match is highlighted in purple, 
                    and next probable matches are highlighted in lighter colors.
                </div>
            `;

      // Insert before the table
      const tableContainer = document.querySelector(".results-table-container");
      tableContainer.parentNode.insertBefore(aiInfoElement, tableContainer);
    }

    // Sort results to prioritize AI-highlighted items
    const sortedResults = [...data.results];

    // Sort function to put AI preferred first, then next probable by rank, then the rest
    sortedResults.sort((a, b) => {
      const aIsPreferred = a.id === aiPreferredId;
      const bIsPreferred = b.id === aiPreferredId;

      // If one is preferred, it comes first
      if (aIsPreferred && !bIsPreferred) return -1;
      if (!aIsPreferred && bIsPreferred) return 1;

      // If neither is preferred, check if they're in next probable
      const aNextProbableIndex = aiNextProbableIds.indexOf(a.id);
      const bNextProbableIndex = aiNextProbableIds.indexOf(b.id);

      const aIsNextProbable = aNextProbableIndex !== -1;
      const bIsNextProbable = bNextProbableIndex !== -1;

      // If one is next probable and the other isn't, the next probable comes first
      if (aIsNextProbable && !bIsNextProbable) return -1;
      if (!aIsNextProbable && bIsNextProbable) return 1;

      // If both are next probable, sort by their rank
      if (aIsNextProbable && bIsNextProbable) {
        return aNextProbableIndex - bNextProbableIndex;
      }

      // Otherwise, keep original order
      return 0;
    });

    // Populate table with sorted results
    sortedResults.forEach((place, index) => {
      const row = document.createElement("tr");

      // Find the original index in data.results for the "Show on Map" functionality
      const originalIndex = data.results.findIndex((p) => p.id === place.id);

      // Check if this is the AI preferred result or one of the next probable matches
      const isAiPreferred = place.id === aiPreferredId;
      const nextProbableIndex = aiNextProbableIds.indexOf(place.id);
      const isNextProbable = nextProbableIndex !== -1;

      // Add appropriate class based on ranking
      if (isAiPreferred) {
        row.classList.add("ai-preferred");
      } else if (isNextProbable) {
        row.classList.add("ai-next-probable");
        row.dataset.rank = nextProbableIndex + 1; // Store the rank (1-based)
      }

      // Format hierarchy
      const hierarchy =
        place.hierarchy && place.hierarchy.length > 0
          ? place.hierarchy.join(" > ")
          : "";

      // Create table cells
      row.innerHTML = `
                <td>
                    ${
                      isAiPreferred
                        ? '<span class="ai-star-container"><i class="fas fa-star ai-star" title="AI Preferred Match"></i></span>'
                        : isNextProbable
                          ? `<span class="ai-rank-container" title="AI Rank #${nextProbableIndex + 1}">${nextProbableIndex + 1}</span>`
                          : ""
                    }
                    ${place.name}
                </td>
                <td>${place.subtype}</td>
                <td>${place.country}</td>
                <td>${hierarchy}</td>
                <td>
                    ${
                      place.geometry
                        ? `<button class="action-button" data-index="${originalIndex}">
                            <i class="fas fa-map-marker-alt"></i> Show on Map
                        </button>`
                        : '<span class="no-geometry">No geometry data</span>'
                    }
                </td>
            `;

      // Add event listener to the "Show on Map" button if it exists
      const mapButton = row.querySelector(".action-button");
      if (mapButton) {
        mapButton.addEventListener("click", () => showOnMap(originalIndex));
      }

      resultsBody.appendChild(row);
    });
  } else {
    resultsContainer.classList.remove("hidden");
    noResults.classList.remove("hidden");
  }
}

// Show place on map
function showOnMap(index) {
  const place = searchResults[index];

  if (!place || !place.geometry) {
    alert("No geometry data available for this location.");
    return;
  }

  // Clear previous layers
  map.eachLayer((layer) => {
    if (layer instanceof L.GeoJSON) {
      map.removeLayer(layer);
    }
  });

  // Add GeoJSON to map
  const geoJsonLayer = L.geoJSON(place.geometry, {
    style: {
      color: "#3498db",
      weight: 2,
      opacity: 0.8,
      fillColor: "#3498db",
      fillOpacity: 0.2,
    },
  }).addTo(map);

  // Fit map to the bounds of the geometry
  map.fitBounds(geoJsonLayer.getBounds());

  // Update map title
  mapTitle.textContent = `${place.name} (${place.subtype}, ${place.country})`;

  // Open map drawer
  openMapDrawer();
}

// Open map drawer
function openMapDrawer() {
  mapDrawer.classList.add("open");
  overlay.classList.remove("hidden");

  // Trigger a resize event to ensure the map renders correctly
  setTimeout(() => {
    map.invalidateSize();
  }, 300);
}

// Close map drawer
function closeMapDrawer() {
  mapDrawer.classList.remove("open");
  overlay.classList.add("hidden");
}
