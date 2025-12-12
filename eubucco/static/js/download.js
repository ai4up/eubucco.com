let countries = [];
let selectedCountry = null;
let nutsPartitions = [];
let v01Files = [];
let selectedNutsId = "";
let applyFilters = () => {};

const cfgElement = document.getElementById("downloadConfig");
if (!cfgElement) {
  console.error("downloadConfig element not found");
}
const cfg = cfgElement ? JSON.parse(cfgElement.textContent) : {};
const API_URL = cfg.apiUrl;
const NUTS_URL = cfg.nutsUrl;
const currentVersion = cfg.version || "v0.2";
const versionSelect = document.getElementById("versionSelect");
const searchControls = document.getElementById("searchControls");
const countryDropdown = document.getElementById("countryDropdown");
const nutsInput = document.getElementById("nutsInput");
const nutsOptions = document.getElementById("nutsOptions");
const orSeparator = document.getElementById("orSeparator");

let mapInstance = null;

const countryIso2 = {
  "Austria": "AT",
  "Belgium": "BE",
  "Bulgaria": "BG",
  "Croatia": "HR",
  "Cyprus": "CY",
  "Czech Republic": "CZ",
  "Germany": "DE",
  "Denmark": "DK",
  "Estonia": "EE",
  "Spain": "ES",
  "Finland": "FI",
  "France": "FR",
  "Greece": "EL",
  "Hungary": "HU",
  "Ireland": "IE",
  "Italy": "IT",
  "Lithuania": "LT",
  "Luxembourg": "LU",
  "Latvia": "LV",
  "Malta": "MT",
  "Netherlands": "NL",
  "Poland": "PL",
  "Portugal": "PT",
  "Romania": "RO",
  "Sweden": "SE",
  "Slovenia": "SI",
  "Slovakia": "SK",
  "Switzerland": "CH",
};

/* ---------- Helpers ---------- */
const iso2ToCountry = Object.fromEntries(
  Object.entries(countryIso2).map(([name, iso]) => [iso, name])
);

const getApiBase = () => {
  if (API_URL && !API_URL.includes("0.0.0.0")) {
    return API_URL.endsWith("/") ? API_URL : `${API_URL}/`;
  }
  const host = window.location.hostname || "localhost";
  return `${window.location.protocol}//${host}:8001/v1/`;
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
    populateNutsOptions();
  } catch (e) {
    console.error("Failed to load data", e);
    if (currentVersion === "v0.1") {
      v01Files = [];
    } else {
      nutsPartitions = [];
    }
  }
};

const populateNutsOptions = () => {
  if (!nutsOptions) return;

  const codes = new Set();
  nutsPartitions.forEach(part => codes.add(part.nuts_id));

  nutsOptions.innerHTML = "";
  Array.from(codes)
    .sort()
    .forEach(code => {
      nutsOptions.innerHTML += `<option value="${code}">`;
    });
};

/* ---------- Countries ---------- */

const updateCountries = async () => {
  if (!countryDropdown) return;

  const baseApi = getApiBase();
  try {
    const resp = await fetch(`${baseApi}countries`);
    if (!resp.ok) {
      console.error("Failed to load countries", resp.status, resp.statusText);
      countries = [];
    } else {
      countries = await resp.json();
      if (!Array.isArray(countries)) {
        countries = [];
      } else {
        countries.sort((a, b) => a.name.localeCompare(b.name));
        countryDropdown.innerHTML = '<option disabled selected>Select Country</option>';
        countries.forEach(country => {
          countryDropdown.innerHTML += `<option value="${country.id}">${country.name}</option>`;
        });
      }
    }
  } catch (e) {
    console.error("Failed to load countries", e);
    countries = [];
  }
};

const onSelectCountry = () => {
  const selectedId = parseInt(countryDropdown.value, 10);
  selectedCountry = countries.find(country => country.id === selectedId) || null;

  const iso2 = selectedCountry ? (countryIso2[selectedCountry.name] || "") : "";
  selectedNutsId = iso2;
  updateSelectionLayer();
  applyFilters();
  renderNutsResults();
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

  const candidate = nutsInput ? (nutsInput.value || "").trim().toUpperCase() : "";

  if (!candidate) {
    if (selectedCountry) {
      const gpkgCell = selectedCountry.gpkg
        ? `<a class="link" href="${selectedCountry.gpkg.download_link}"
                referrerpolicy="strict-origin-when-cross-origin">
                Download (${Math.round(selectedCountry.gpkg.size_in_mb)} MB)
            </a>`
        : "—";
      const csvCell = selectedCountry.csv
        ? `<a class="link" href="${selectedCountry.csv.download_link}"
                referrerpolicy="strict-origin-when-cross-origin">
                Download (${Math.round(selectedCountry.csv.size_in_mb)} MB)
            </a>`
        : "—";

      tableBody.innerHTML = `<tr>
        <td>${selectedCountry.name}</td>
        <td>—</td>
        <td>${gpkgCell}</td>
        <td>${csvCell}</td>
      </tr>`;
    } else {
      tableBody.innerHTML =
        '<tr><td colspan="4" class="text-center">Select a country or NUTS code to see downloads.</td></tr>';
    }
    selectedNutsId = selectedNutsId || "";
    updateSelectionLayer();
    applyFilters();
    return;
  }

  if (!Array.isArray(nutsPartitions) || nutsPartitions.length === 0) {
    tableBody.innerHTML =
      '<tr><td colspan="4" class="text-error text-center">No partitions available.</td></tr>';
    updateSelectionLayer();
    applyFilters();
    return;
  }

  const matches = nutsPartitions.filter(
    part => (part.nuts_id || "").toUpperCase().startsWith(candidate),
  );

  if (matches.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="4" class="text-error text-center">
      No partitions match ${candidate}.
    </td></tr>`;
    selectedNutsId = "";
    updateSelectionLayer();
    applyFilters();
    return;
  }

  selectedNutsId = candidate;
  updateSelectionLayer();
  applyFilters();

  let rows = "";
  matches.forEach(part => {
    const file = part.files.find(f => f.key.endsWith(".parquet")) || part.files[0];
    const sizeMb = Math.round(file.size_bytes / 1e6);
    rows += `<tr>
      <td>${part.nuts_id}</td>
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
  const bundleUrl = `${getApiBase()}datalake/nuts/${version}/${candidate}/bundle`;

  if (parquetZipBtn) {
    parquetZipBtn.disabled = false;
    parquetZipBtn.onclick = () => {
      window.location.href = bundleUrl;
    };
  }
};

const onNutsChange = () => renderNutsResults();

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
    minZoom: 2.8,
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

  map.on("click", e => {
    if (currentVersion !== "v0.2") return;
    if (!nutsInput) return;

    const feats = map.queryRenderedFeatures(e.point, { layers: ["nuts-fill"] });
    if (!feats || feats.length === 0) {
      selectedNutsId = "";
      nutsInput.value = "";
      updateFilters();
      renderNutsResults();
      return;
    }
    const feature = feats.sort((a, b) => b.properties.nuts_level - a.properties.nuts_level)[0];
    selectedNutsId = feature.properties.nuts_id;
    nutsInput.value = selectedNutsId;
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

  if (countryDropdown) {
    countryDropdown.addEventListener("change", onSelectCountry);
  }

  if (nutsInput) {
    nutsInput.addEventListener("input", onNutsChange);
  }

  initMap();
  await updateCountries();
  await loadNutsOrFiles();
  renderNutsResults();
});