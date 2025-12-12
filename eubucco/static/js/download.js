let countries = [];
let selectedNutsId = "";
let nutsPartitions = [];
let v01Files = [];
let applyFilters = () => {};
let nutsNames = {};

const cfgElement = document.getElementById("downloadConfig");
if (!cfgElement) {
  console.error("downloadConfig element not found");
}
const cfg = cfgElement ? JSON.parse(cfgElement.textContent) : {};
const API_URL = cfg.apiUrl;
const NUTS_URL = cfg.nutsUrl;
const NUTS_NAMES_URL = cfg.nutsNamesUrl;
const currentVersion = cfg.version || "v0.2";
const versionSelect = document.getElementById("versionSelect");
const searchControls = document.getElementById("searchControls");
const nutsCodeInput = document.getElementById("nutsCodeInput");
const nutsCodeOptions = document.getElementById("nutsCodeOptions");
const nutsNameInput = document.getElementById("nutsNameInput");
const nutsNameOptions = document.getElementById("nutsNameOptions");

let mapInstance = null;
let tooltip = null;

const getApiBase = () => {
  if (API_URL && !API_URL.includes("0.0.0.0")) {
    return API_URL.endsWith("/") ? API_URL : `${API_URL}/`;
  }
  const host = window.location.hostname || "localhost";
  return `${window.location.protocol}//${host}:8001/v1/`;
};

/* ---------- NUTS names mapping ---------- */

const loadNutsNames = async () => {
  if (!NUTS_NAMES_URL) {
    console.error("NUTS names URL not configured");
    nutsNames = {};
    return;
  }
  
  try {
    const resp = await fetch(NUTS_NAMES_URL);
    if (!resp.ok) {
      console.error("Failed to load NUTS names", resp.status, resp.statusText);
      nutsNames = {};
    } else {
      nutsNames = await resp.json();
    }
  } catch (e) {
    console.error("Failed to load NUTS names", e);
    nutsNames = {};
  }
};

const getNutsName = (nutsId) => {
  return nutsNames[nutsId] || 'Unknown region';
};

/* ---------- NUTS partitions + v0.1 files ---------- */

const loadNutsOrFiles = async () => {
  const baseApi = getApiBase();
  try {
    if (currentVersion === "v0.1") {
      const resp = await fetch(`${baseApi}datalake/files/v0.1`);
      if (!resp.ok) {
        console.error("Failed to load v0.1 files", resp.status, resp.statusText);
        v01Files = [];
      } else {
        const data = await resp.json();
        v01Files = Array.isArray(data.files) ? data.files : [];
      }
      return;
    }

    const resp = await fetch(`${baseApi}datalake/nuts?version=${currentVersion}`);
    if (!resp.ok) {
      console.error("Failed to load nuts partitions", resp.status, resp.statusText);
      nutsPartitions = [];
    } else {
      nutsPartitions = await resp.json();
      if (!Array.isArray(nutsPartitions)) nutsPartitions = [];
    }
  } catch (e) {
    console.error("Failed to load data", e);
    if (currentVersion === "v0.1") {
      v01Files = [];
    } else {
      nutsPartitions = [];
    }
  }
};

/* ---------- Search functionality ---------- */

// Simple string similarity score (0-1)
const calculateSimilarity = (str1, str2) => {
  const s1 = str1.toLowerCase();
  const s2 = str2.toLowerCase();
  
  // Exact match
  if (s1 === s2) return 1.0;
  
  // Starts with (high priority)
  if (s2.startsWith(s1)) return 0.9;
  
  // Contains (medium priority)
  if (s2.includes(s1)) return 0.7;
  
  // Levenshtein-like: count matching characters
  let matches = 0;
  const len = Math.min(s1.length, s2.length);
  for (let i = 0; i < len; i++) {
    if (s1[i] === s2[i]) matches++;
  }
  
  return matches / Math.max(s1.length, s2.length) * 0.5;
};

const getNutsLevel = (nutsId) => {
  if (!nutsId) return 0;
  return Math.min(nutsId.length - 1, 3);
};

const formatSuggestion = (name, nutsId) => {
  return `${name} [${nutsId}]`;
};

const findTopMatches = (searchText, maxResults = 8) => {
  if (!searchText || searchText.length < 2) return [];
  
  const normalizedSearch = searchText.trim().toLowerCase();
  const matches = [];
  
  for (const [code, name] of Object.entries(nutsNames)) {
    const score = calculateSimilarity(normalizedSearch, name);
    if (score > 0.3) {
      matches.push({ code, name, score });
    }
  }
  
  // Sort by score descending, then by NUTS level (lower first), then by name
  matches.sort((a, b) => {
    if (Math.abs(a.score - b.score) < 0.01) {
      const levelDiff = getNutsLevel(a.code) - getNutsLevel(b.code);
      if (levelDiff !== 0) return levelDiff;
      return a.name.localeCompare(b.name);
    }
    return b.score - a.score;
  });
  
  return matches.slice(0, maxResults);
};

const updateNameSuggestions = (searchText) => {
  if (!nutsNameOptions) return;
  
  const matches = findTopMatches(searchText);
  
  nutsNameOptions.innerHTML = '';
  matches.forEach(match => {
    const option = document.createElement('option');
    option.value = formatSuggestion(match.name, match.code);
    nutsNameOptions.appendChild(option);
  });
};

const findNutsIdByInput = (inputValue) => {
  if (!inputValue) return null;
  
    // Check if input matches our formatted suggestion pattern: "Name [CODE]"
  const match = inputValue.match(/\[([A-Z0-9]+)\]$/);
  if (match) {
    return match[1]; // Extract the NUTS code
  }
  
  // Otherwise try fuzzy search
  const normalizedSearch = inputValue.trim().toLowerCase();
  
  // Exact match first
  for (const [code, name] of Object.entries(nutsNames)) {
    if (name.toLowerCase() === normalizedSearch) {
      return code;
    }
  }
  
  // Try to find best match
  const matches = findTopMatches(inputValue, 1);
  return matches.length > 0 ? matches[0].code : null;
};

// Debounce function to avoid too many renders
let searchTimeout = null;
let suggestionTimeout = null;

const onNutsCodeChange = () => {
  // Clear the name input when typing in code input
  if (nutsNameInput && nutsCodeInput && nutsCodeInput.value) {
    nutsNameInput.value = '';
  }
  
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    renderNutsResults();
  }, 300);
};

const onNutsNameChange = () => {
  // Clear the code input when typing in name input
  if (nutsCodeInput && nutsNameInput && nutsNameInput.value) {
    nutsCodeInput.value = '';
  }
  
  const searchText = nutsNameInput.value.trim();
  
  // Update suggestions dynamically
  clearTimeout(suggestionTimeout);
  if (searchText.length >= 2) {
    suggestionTimeout = setTimeout(() => {
      updateNameSuggestions(searchText);
    }, 150);
  }
  
  // Update results
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    renderNutsResults();
  }, 300);
};

/* ---------- Rendering table ---------- */

const renderNutsResults = () => {
  const tableBody = document.getElementById("downloadsBody");
  const parquetZipBtn = document.getElementById("btnParquet");

  if (!tableBody) return;
  if (currentVersion === "v0.1") return;

  if (parquetZipBtn) {
    parquetZipBtn.disabled = true;
    parquetZipBtn.onclick = null;
  }

  // Get search input from either code or name search
  let candidateCode = "";
  
  if (nutsCodeInput && nutsCodeInput.value.trim()) {
    candidateCode = nutsCodeInput.value.trim().toUpperCase();
  } else if (nutsNameInput && nutsNameInput.value.trim()) {
    const foundCode = findNutsIdByInput(nutsNameInput.value);
    if (foundCode) {
      candidateCode = foundCode.toUpperCase();
    }
  }

  if (!candidateCode) {
    tableBody.innerHTML =
      '<tr><td colspan="5" class="text-center">Search by NUTS code or region name to see downloads.</td></tr>';
    selectedNutsId = "";
    updateSelectionLayer();
    applyFilters();
    return;
  }

  if (!Array.isArray(nutsPartitions) || nutsPartitions.length === 0) {
    tableBody.innerHTML =
      '<tr><td colspan="5" class="text-error text-center">No data available.</td></tr>';
    updateSelectionLayer();
    applyFilters();
    return;
  }

  const matches = nutsPartitions.filter(
    part => (part.nuts_id || "").toUpperCase().startsWith(candidateCode),
  );

  if (matches.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="5" class="text-error text-center">
      No data found for "${candidateCode}".
    </td></tr>`;
    selectedNutsId = "";
    updateSelectionLayer();
    applyFilters();
    return;
  }

  selectedNutsId = candidateCode;
  updateSelectionLayer();
  applyFilters();

  let rows = "";
  matches.forEach(part => {
    const file = part.files.find(f => f.key.endsWith(".parquet")) || part.files[0];
    const sizeMb = Math.round(file.size_bytes / 1e6);
    const nutsName = getNutsName(part.nuts_id);
    rows += `<tr>
      <td>${part.nuts_id}</td>
      <td>${nutsName}</td>
      <td><a class="link" href="${file.presigned_url}"
              referrerpolicy="strict-origin-when-cross-origin">
              Download (${sizeMb} MB)
      </a></td>
      <td class="text-center">—</td>
      <td class="text-center">—</td>
    </tr>`;
  });

  tableBody.innerHTML = rows;

  const version = matches[0].version;
  const bundleUrl = `${getApiBase()}datalake/nuts/${version}/${candidateCode}/bundle`;

  if (parquetZipBtn) {
    parquetZipBtn.disabled = false;
    parquetZipBtn.onclick = () => {
      window.location.href = bundleUrl;
    };
  }
};

/* ---------- Map tooltip ---------- */

const createTooltip = () => {
  const el = document.createElement('div');
  el.className = 'map-tooltip';
  el.style.cssText = `
    position: absolute;
    background: rgba(15, 23, 42, 0.95);
    color: #f1f5f9;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 13px;
    pointer-events: none;
    z-index: 1000;
    display: none;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(148, 163, 184, 0.3);
    max-width: 300px;
    white-space: nowrap;
  `;
  document.body.appendChild(el);
  return el;
};

const showTooltip = (e, feature) => {
  if (!tooltip) return;
  
  const nutsId = feature.properties.nuts_id || '';
  const nutsName = getNutsName(nutsId);
  
  tooltip.innerHTML = `<strong>${nutsId}</strong><br>${nutsName}`;
  tooltip.style.display = 'block';
  tooltip.style.left = e.pageX + 10 + 'px';
  tooltip.style.top = e.pageY + 10 + 'px';
};

const hideTooltip = () => {
  if (tooltip) {
    tooltip.style.display = 'none';
  }
};

/* ---------- Map / NUTS highlighting ---------- */

const initMap = () => {
  if (!NUTS_URL || !window.maplibregl || !window.pmtiles) {
    console.warn("Map configuration missing or libraries not loaded.");
    return;
  }

  const mapContainer = document.getElementById("map");
  if (!mapContainer) {
    console.warn("Map container not found in DOM.");
    return;
  }

  // Create tooltip
  tooltip = createTooltip();

  const protocol = new window.pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  const pmtilesUrl = NUTS_URL.startsWith("pmtiles://")
    ? NUTS_URL
    : `pmtiles://${NUTS_URL}`;

  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        nuts: { type: "vector", url: pmtilesUrl },
      },
      layers: [
        {
          id: "background",
          type: "background",
          paint: { "background-color": "#0b1221" },
        },
        {
          id: "nuts-fill",
          type: "fill",
          source: "nuts",
          "source-layer": "nuts",
          paint: {
            "fill-color": "#4f46e5",
            "fill-opacity": 0.12,
          },
          filter: ["<=", ["get", "nuts_level"], 3],
        },
        {
          id: "nuts-outline",
          type: "line",
          source: "nuts",
          "source-layer": "nuts",
          paint: {
            "line-color": "#94a3b8",
            "line-width": 0.4,
          },
          filter: ["<=", ["get", "nuts_level"], 3],
        },
        {
          id: "nuts-selected",
          type: "line",
          source: "nuts",
          "source-layer": "nuts",
          paint: { "line-color": "#e11d48", "line-width": 2.5 },
          filter: ["==", ["get", "nuts_id"], ""],
        },
      ],
    },
    center: [10, 55],
    zoom: 3.2,
    maxZoom: 10,
    minZoom: 3,
    attributionControl: true,
  });

  mapInstance = map;

  const updateFilters = () => {
    if (!mapInstance || !mapInstance.isStyleLoaded()) return;

    if (selectedNutsId) {
      const targetLevel = Math.min(selectedNutsId.length - 1, 3);
      const nextLevel = Math.min(targetLevel + 1, 3);
      const prefix = selectedNutsId;

      const prefixFilter = ["==", ["slice", ["get", "nuts_id"], 0, prefix.length], prefix];
      const childrenFilter = ["all", ["==", ["get", "nuts_level"], nextLevel], prefixFilter];
      const selectedFilter = ["all", ["==", ["get", "nuts_id"], selectedNutsId]];

      const filter = ["any", ["==", ["get", "nuts_level"], 0], childrenFilter, selectedFilter];
      mapInstance.setFilter("nuts-fill", filter);
      mapInstance.setFilter("nuts-outline", filter);
      mapInstance.setFilter("nuts-selected", ["==", ["get", "nuts_id"], selectedNutsId]);
    } else {
      mapInstance.setFilter("nuts-fill", ["==", ["get", "nuts_level"], 0]);
      mapInstance.setFilter("nuts-outline", ["==", ["get", "nuts_level"], 0]);
      mapInstance.setFilter("nuts-selected", ["==", ["get", "nuts_id"], ""]);
    }
  };

  map.on("load", updateFilters);
  applyFilters = updateFilters;

  // Hover tooltip
  map.on("mousemove", "nuts-fill", e => {
    map.getCanvas().style.cursor = "pointer";
    if (e.features && e.features.length > 0) {
      // Sort by nuts_level descending to get the most specific region (highest level number)
      const sortedFeatures = e.features.sort((a, b) => 
        (b.properties.nuts_level || 0) - (a.properties.nuts_level || 0)
      );
      showTooltip(e.originalEvent, sortedFeatures[0]);
    }
  });

  map.on("mouseleave", "nuts-fill", () => {
    map.getCanvas().style.cursor = "";
    hideTooltip();
  });

  map.on("click", e => {
    if (currentVersion !== "v0.2") return;
    if (!nutsCodeInput && !nutsNameInput) return;

    const feats = map.queryRenderedFeatures(e.point, { layers: ["nuts-fill"] });
    if (!feats || feats.length === 0) {
      selectedNutsId = "";
      if (nutsCodeInput) nutsCodeInput.value = "";
      if (nutsNameInput) nutsNameInput.value = "";
      updateFilters();
      renderNutsResults();
      return;
    }
    const feature = feats.sort((a, b) => b.properties.nuts_level - a.properties.nuts_level)[0];
    selectedNutsId = feature.properties.nuts_id;
    if (nutsCodeInput) {
      nutsCodeInput.value = selectedNutsId;
      if (nutsNameInput) nutsNameInput.value = "";
    }
    updateFilters();
    renderNutsResults();
  });
};

const updateSelectionLayer = () => {
  if (!mapInstance || !mapInstance.isStyleLoaded()) return;
  mapInstance.setFilter("nuts-selected", ["==", ["get", "nuts_id"], selectedNutsId || ""]);
};

/* ---------- Bottom bar alignment ---------- */

function alignDownloadsBottomBar() {
  const table = document.getElementById("downloadsTable");
  const bar = document.getElementById("downloadsBottomBar");
  if (!table || !bar) return;

  const firstRow = table.querySelector("thead tr");
  if (!firstRow) return;

  const cells = Array.from(firstRow.children);
  const widths = cells.map(th => th.getBoundingClientRect().width + "px");
  bar.style.gridTemplateColumns = widths.join(" ");
}

/* ---------- Version switching ---------- */

const onVersionChange = () => {
  const newVersion = versionSelect.value;
  // Navigate to the new URL with the selected version
  window.location.href = `/files/${newVersion}`;
};

/* ---------- Bootstrap ---------- */

window.addEventListener("resize", alignDownloadsBottomBar);

document.addEventListener("DOMContentLoaded", async () => {
  setTimeout(alignDownloadsBottomBar, 50);

  if (versionSelect) {
    versionSelect.addEventListener("change", onVersionChange);
  }

  if (nutsCodeInput) {
    nutsCodeInput.addEventListener("input", onNutsCodeChange);
  }

  if (nutsNameInput) {
    nutsNameInput.addEventListener("input", onNutsNameChange);
  }

  initMap();
  await loadNutsNames();
  await loadNutsOrFiles();
  renderNutsResults();
});