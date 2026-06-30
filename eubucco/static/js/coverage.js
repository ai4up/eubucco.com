/**
 * EUBUCCO Regional Coverage & Quality Visualization
 *
 * Interactive NUTS0-3 choropleth backed by coverage-stats.pmtiles, with a stats
 * panel that shows Europe-wide figures by default and detailed figures for a
 * single selected region.
 */

/* ============ GLOBAL STATE ============ */

let map = null;
let nutsNames = {};
let europeSummary = null;
let selectedRegion = null;            // { nuts_id, nuts_level, ...props } or null
let currentMetric = 'source_gov_pct'; // req: default metric = Government source
// Region from a shared URL, applied once the tiles carrying it have loaded.
let pendingRegion = null;             // { nuts_id, nuts_level } or null

const charts = {
  source: null,
  coverage: null,
  type: null,
  subtype: null,
  height: null,
  floor: null,
  floorArea: null,
  floorAreaRes: null,
};

// Label-only basemap overlay (place names from a standard basemap, on top of
// the choropleth). No API key required; if the tiles fail to load the
// choropleth is unaffected.
const LABEL_TILES = {
  light: 'https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png',
  dark: 'https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}@2x.png',
};
const LABEL_ATTRIBUTION = '© OpenStreetMap contributors © CARTO';

/* ============ CONFIG ============ */

const cfgElement = document.getElementById('coverageConfig');
if (!cfgElement) {
  console.error('coverageConfig element not found');
}
const cfg = cfgElement ? JSON.parse(cfgElement.textContent) : {};
const PMTILES_URL = cfg.pmtilesUrl;
const SUMMARY_URL = cfg.summaryUrl;
const NUTS_NAMES_URL = cfg.nutsNamesUrl;

/* ============ PALETTES ============ */

// Provenance split colours, reused by the stacked bar.
const PROVENANCE = {
  gt: '#7ec8a3',       // ground truth (green)
  merged: '#7c9ed9',   // merged (blue)
  est: '#fcd7a1',      // ML-estimated (orange)
  none: '#d4dae3',     // no value (grey)
};

// Thresholds calibrated to the real NUTS density distribution (median ~110,
// p90 ~590, max ~1800 buildings/km²) so the six bands are actually used.
const DENSITY_COLORS = ['#ede7f6', '#c7b3e0', '#a585cf', '#8458bd', '#6a3aa0', '#4a2480'];
const DENSITY_STOPS = [50, 100, 200, 400, 800]; // 6 classes

// Modern emerald sequential for ground-truth coverage (low → high = light → deep).
const COVERAGE_RAMP = [
  [0, '#eef2f0'], [25, '#a7d9c6'], [50, '#5cbfa0'], [75, '#1f9e78'], [100, '#0b6e57'],
];
const SOURCE_RAMP = [
  [0, '#e3f2fd'], [25, '#b3d9f2'], [50, '#81c3e8'], [75, '#5ba8cf'], [100, '#3d8fb5'],
];

// Diverging ramp for non-residential floor-area share. Values cluster tightly
// (~p10 34%, median 48%, ~p90 61%), so the ramp is stretched to the populated
// 26–68% band and centred (neutral) at the median to surface mid-range nuance;
// teal = more residential, amber = more non-residential.
const SHARE_RAMP = [
  [26, '#5a9e8c'], [37, '#a9cbc0'], [48, '#eceee8'], [59, '#e3c08a'], [68, '#c98a4e'],
];

// Residential subtypes: a cohesive but muted cool ramp (all "residential"),
// spread across green → teal → blue → indigo so the slices stay distinguishable.
const RES_COLORS = ['#6aa784', '#5aa9a0', '#6f9ec6', '#8e90cf'];

// Binary building type — muted teal (residential) vs muted amber (non-res).
const TYPE_COLORS = ['#6aa784', '#d9a86b'];

const SUBTYPE_KEYS = [
  'detached', 'semi_detached', 'terraced', 'apartment',
  'commercial', 'industrial', 'agricultural', 'public', 'others',
];
const SUBTYPE_LABELS = ['Detached', 'Semi-detached', 'Terraced', 'Apartment',
  'Commercial', 'Industrial', 'Agricultural', 'Public', 'Other'];
// Residential (cool) + non-residential (warm), all muted to match the palette.
const SUBTYPE_COLORS = [...RES_COLORS,
  '#d9a86b', '#cf8a6a', '#c2bd8e', '#b9a3d1', '#b6c0cb'];

// English NUTS0 country names for the panel header (data carries only codes /
// local-language names).
const COUNTRY_NAMES = {
  AL: 'Albania', AT: 'Austria', BA: 'Bosnia and Herzegovina', BE: 'Belgium',
  BG: 'Bulgaria', CH: 'Switzerland', CY: 'Cyprus', CZ: 'Czechia',
  DE: 'Germany', DK: 'Denmark', EE: 'Estonia', EL: 'Greece', ES: 'Spain',
  FI: 'Finland', FR: 'France', HR: 'Croatia', HU: 'Hungary', IE: 'Ireland',
  IS: 'Iceland', IT: 'Italy', LI: 'Liechtenstein', LT: 'Lithuania',
  LU: 'Luxembourg', LV: 'Latvia', ME: 'Montenegro', MK: 'North Macedonia',
  MT: 'Malta', NL: 'Netherlands', NO: 'Norway', PL: 'Poland', PT: 'Portugal',
  RO: 'Romania', RS: 'Serbia', SE: 'Sweden', SI: 'Slovenia', SK: 'Slovakia',
  UK: 'United Kingdom', XK: 'Kosovo',
};

const COVERAGE_ATTRS = ['height', 'floors', 'type', 'subtype', 'construction_year'];
const COVERAGE_ATTR_LABELS = ['Height', 'Floors', 'Type', 'Subtype', 'Constr. year'];

/* ============ THEME UTILITIES ============ */

function isDarkTheme() {
  return !!(document.documentElement.classList.contains('dark') ||
            document.querySelector('[data-theme="night"]'));
}

function getThemeColors() {
  const isDark = isDarkTheme();
  return {
    background: isDark ? '#1a1a2e' : '#f3f4f6',
    outline: isDark ? '#3f4754' : '#d4dae3',
    selected: isDark ? '#fcd7a1' : '#f59e0b',
    text: isDark ? '#f3f4f6' : '#1f2937',
    chartBg: isDark ? '#2d2d44' : '#ffffff',
    chartText: isDark ? '#e5e7eb' : '#374151',
    chartGrid: isDark ? '#374151' : '#e5e7eb',
  };
}

function watchThemeChanges(callback) {
  const observer = new MutationObserver(() => callback());
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class', 'data-theme'],
  });
  return observer;
}

/* ============ NUTS NAMES (fallback only — tiles carry `name`) ============ */

async function loadNutsNames() {
  if (!NUTS_NAMES_URL) return;
  try {
    const resp = await fetch(NUTS_NAMES_URL);
    if (resp.ok) nutsNames = await resp.json();
  } catch (e) {
    console.warn('Failed to load NUTS names', e);
  }
}

function regionDisplayName(props) {
  return props.name || nutsNames[props.nuts_id] || props.nuts_id || 'Unknown region';
}

/* ============ EUROPE-WIDE SUMMARY ============ */

async function loadEuropeSummary() {
  if (!SUMMARY_URL) return;
  try {
    const resp = await fetch(SUMMARY_URL);
    if (resp.ok) europeSummary = await resp.json();
  } catch (e) {
    console.warn('Failed to load Europe summary', e);
  }
}

/* ============ METRIC HELPERS ============ */

function val(props, key) {
  const v = props ? Number(props[key]) : NaN;
  return Number.isFinite(v) ? v : 0;
}

// Compact building counts: millions as "X.XM", thousands as "Xk".
function formatCount(n) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return n.toLocaleString();
}

// Floor area: m² → km² (with a sensible precision), small areas stay in m².
function formatArea(m2) {
  const km2 = m2 / 1e6;
  if (km2 >= 1) {
    return `${km2.toLocaleString(undefined, { maximumFractionDigits: km2 >= 100 ? 0 : 1 })} km²`;
  }
  return `${Math.round(m2).toLocaleString()} m²`;
}

function metricKind(metric) {
  if (metric === 'density') return 'density';
  if (metric === 'fa_non_residential_pct') return 'share';
  if (metric.startsWith('source_')) return 'source';
  return 'coverage'; // ground-truth coverage
}

function stepExpression(prop, colors, stops) {
  const expr = ['step', ['coalesce', ['get', prop], 0], colors[0]];
  stops.forEach((stop, i) => expr.push(stop, colors[i + 1]));
  return expr;
}

function rampExpression(metric, ramp) {
  const expr = ['interpolate', ['linear'], ['coalesce', ['get', metric], 0]];
  ramp.forEach(([stop, color]) => expr.push(stop, color));
  return expr;
}

function getChoroplethExpression(metric) {
  const kind = metricKind(metric);
  if (kind === 'density') return stepExpression('density', DENSITY_COLORS, DENSITY_STOPS);
  if (kind === 'share') return rampExpression(metric, SHARE_RAMP);
  if (kind === 'source') return rampExpression(metric, SOURCE_RAMP);
  return rampExpression(metric, COVERAGE_RAMP);
}

function generateLegend(metric) {
  const legendEl = document.getElementById('legend');
  if (!legendEl) return;
  legendEl.innerHTML = '';

  const kind = metricKind(metric);
  let items = [];

  if (kind === 'density') {
    items = [
      { color: DENSITY_COLORS[5], label: '>800 /km²' },
      { color: DENSITY_COLORS[4], label: '400–800 /km²' },
      { color: DENSITY_COLORS[3], label: '200–400 /km²' },
      { color: DENSITY_COLORS[2], label: '100–200 /km²' },
      { color: DENSITY_COLORS[1], label: '50–100 /km²' },
      { color: DENSITY_COLORS[0], label: '<50 /km²' },
    ];
  } else if (kind === 'share') {
    items = [
      { color: SHARE_RAMP[4][1], label: '≥65% non-res.' },
      { color: SHARE_RAMP[3][1], label: '55–65%' },
      { color: SHARE_RAMP[2][1], label: '~48% (median)' },
      { color: SHARE_RAMP[1][1], label: '37–43%' },
      { color: SHARE_RAMP[0][1], label: '≤30% residential' },
    ];
  } else {
    const ramp = kind === 'source' ? SOURCE_RAMP : COVERAGE_RAMP;
    items = [
      { color: ramp[4][1], label: '80–100%' },
      { color: ramp[3][1], label: '60–80%' },
      { color: ramp[2][1], label: '40–60%' },
      { color: ramp[1][1], label: '20–40%' },
      { color: ramp[0][1], label: '0–20%' },
    ];
  }

  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'flex items-center gap-2 text-xs';
    div.innerHTML = `
      <div class="w-4 h-4 rounded" style="background-color: ${item.color}"></div>
      <span>${item.label}</span>
    `;
    legendEl.appendChild(div);
  });
}

/* ============ ZOOM <-> NUTS LEVEL ============ */

function visibleMaxLevel(zoom) {
  if (zoom < 4) return 0;   // Countries
  if (zoom < 5) return 1;   // + NUTS1
  if (zoom < 7) return 2;   // + NUTS2
  return 3;                 // + NUTS3
}

/* ============ MAP INITIALIZATION ============ */

function initMap() {
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', protocol.tile);

  const colors = getThemeColors();

  map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8,
      sources: {
        coverage: { type: 'vector', url: `pmtiles://${PMTILES_URL}` },
      },
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: { 'background-color': colors.background },
        },
        {
          id: 'coverage-fill',
          type: 'fill',
          source: 'coverage',
          'source-layer': 'stats',
          paint: {
            'fill-color': getChoroplethExpression(currentMetric),
            'fill-opacity': 0.75,
          },
          filter: ['<=', ['get', 'nuts_level'], 0],
        },
        {
          id: 'coverage-outline',
          type: 'line',
          source: 'coverage',
          'source-layer': 'stats',
          paint: {
            'line-color': colors.outline,
            'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.3, 6, 0.5, 10, 0.8],
            'line-opacity': 0.5,
          },
          filter: ['<=', ['get', 'nuts_level'], 0],
        },
        {
          id: 'coverage-selected',
          type: 'line',
          source: 'coverage',
          'source-layer': 'stats',
          paint: { 'line-color': colors.selected, 'line-width': 3 },
          filter: ['==', ['get', 'nuts_id'], '__none__'],
        },
      ],
    },
    center: [10, 52],
    zoom: 3.7,
    minZoom: 3.5,
    maxZoom: 9.5,
  });

  map.addControl(new maplibregl.NavigationControl(), 'bottom-left');

  map.on('load', () => {
    updateVisibleLayers();
    generateLegend(currentMetric);
    addLabelLayer();
    restoreSelectionFromUrl();
  });

  // A region from a shared link may live in tiles that finish loading after the
  // initial render; retry the restore until its feature is available.
  map.on('idle', restoreSelectionFromUrl);

  map.on('zoom', () => {
    updateVisibleLayers();
    updateZoomIndicator();
  });

  map.on('click', 'coverage-fill', handleRegionClick);
  map.on('mouseenter', 'coverage-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'coverage-fill', () => { map.getCanvas().style.cursor = ''; });

  updateZoomIndicator();

  watchThemeChanges(() => {
    if (!map) return;
    const c = getThemeColors();
    map.setPaintProperty('background', 'background-color', c.background);
    map.setPaintProperty('coverage-outline', 'line-color', c.outline);
    map.setPaintProperty('coverage-selected', 'line-color', c.selected);
    refreshLabelLayer();
    updateChartThemes();
  });
}

/* ============ BASEMAP LABEL OVERLAY ============ */

function addLabelLayer() {
  if (!map || map.getLayer('basemap-labels')) return;
  map.addSource('basemap-labels', {
    type: 'raster',
    tiles: [isDarkTheme() ? LABEL_TILES.dark : LABEL_TILES.light],
    tileSize: 256,
    attribution: LABEL_ATTRIBUTION,
  });
  // Added last → sits on top of the choropleth so names stay readable.
  map.addLayer({
    id: 'basemap-labels',
    type: 'raster',
    source: 'basemap-labels',
    paint: { 'raster-opacity': 0.9 },
  });
}

function refreshLabelLayer() {
  if (!map) return;
  if (map.getLayer('basemap-labels')) map.removeLayer('basemap-labels');
  if (map.getSource('basemap-labels')) map.removeSource('basemap-labels');
  addLabelLayer();
}

let currentVisibleLevel = 0;

function applySelectedFilter() {
  if (!map || !map.getLayer('coverage-selected')) return;
  if (!selectedRegion) {
    map.setFilter('coverage-selected', ['==', ['get', 'nuts_id'], '__none__']);
    return;
  }
  map.setFilter('coverage-selected', [
    'all',
    ['==', ['get', 'nuts_id'], selectedRegion.nuts_id],
    ['==', ['get', 'nuts_level'], selectedRegion.nuts_level],
  ]);
}

function updateVisibleLayers() {
  if (!map) return;
  const maxLevel = visibleMaxLevel(map.getZoom());
  currentVisibleLevel = maxLevel;

  map.setFilter('coverage-fill', ['<=', ['get', 'nuts_level'], maxLevel]);
  map.setFilter('coverage-outline', ['<=', ['get', 'nuts_level'], maxLevel]);
  // Selection persists across zoom; its boundary simply hides when zoomed out
  // past its level (it is filtered out of the fill/outline layers too).
  applySelectedFilter();
}

function updateZoomIndicator() {
  if (!map) return;
  const zoom = map.getZoom();
  const zoomEl = document.getElementById('zoomLevel');
  const labelEl = document.getElementById('nutsLevelLabel');
  if (zoomEl) zoomEl.textContent = zoom.toFixed(1);
  if (labelEl) {
    const labels = ['Countries (NUTS0)', 'NUTS1 Regions', 'NUTS2 Regions', 'NUTS3 Regions'];
    labelEl.textContent = labels[visibleMaxLevel(zoom)];
  }
}

/* ============ METRIC SELECTION ============ */

const isMobile = () => window.matchMedia('(max-width: 1023px)').matches;

function updateCurrentMetricLabel() {
  const select = document.getElementById('metricSelect');
  const labelEl = document.getElementById('currentMetricLabel');
  if (select && labelEl) {
    const opt = select.options[select.selectedIndex];
    labelEl.textContent = opt ? opt.text : '';
  }
}

function onMetricChange(metric) {
  currentMetric = metric;
  if (map && map.getLayer('coverage-fill')) {
    map.setPaintProperty('coverage-fill', 'fill-color', getChoroplethExpression(metric));
    generateLegend(metric);
  }
  updateCurrentMetricLabel();
  updateUrl();
  // On small screens, collapse the panel after a pick to free the map.
  const panel = document.getElementById('controlPanel');
  if (panel && isMobile()) panel.open = false;
}

/* ============ REGION SELECTION (single, toggleable) ============ */

function handleRegionClick(e) {
  if (!e.features || e.features.length === 0) return;
  const maxLevel = visibleMaxLevel(map.getZoom());

  // Among stacked features, pick the most detailed one currently displayed.
  const candidates = e.features.filter(f => f.properties.nuts_level <= maxLevel);
  if (candidates.length === 0) return;
  const feature = candidates.reduce((prev, cur) =>
    cur.properties.nuts_level > prev.properties.nuts_level ? cur : prev
  );
  const props = feature.properties;

  // Clicking the already-selected region clears it (back to Europe-wide).
  if (selectedRegion &&
      selectedRegion.nuts_id === props.nuts_id &&
      selectedRegion.nuts_level === props.nuts_level) {
    clearSelection();
    return;
  }
  selectRegion(props);
}

function selectRegion(props) {
  selectedRegion = props;
  updateRegionHeader(props, false);
  updateCharts(props);
  applySelectedFilter();
  updateUrl();
}

function clearSelection() {
  selectedRegion = null;
  applySelectedFilter();
  renderEuropeDefault();
  updateUrl();
}

function renderEuropeDefault() {
  const summary = europeSummary || {};
  updateRegionHeader({ ...summary, name: summary.name || 'Europe' }, true);
  updateCharts(summary);
}

const NUTS_LEVEL_LABELS = ['NUTS 0', 'NUTS 1', 'NUTS 2', 'NUTS 3'];

function badge(text, cls = 'badge-ghost') {
  return `<span class="badge badge-sm ${cls}">${text}</span>`;
}

function regionMetaBadges(props) {
  const level = Number(props.nuts_level);
  const code = props.nuts_id || '';
  const country = COUNTRY_NAMES[code.slice(0, 2)] || '';
  const parts = [badge(NUTS_LEVEL_LABELS[level] || 'Region', 'badge-primary badge-outline')];
  if (code) parts.push(badge(code));
  // Country name is redundant with the title at NUTS0, so only add it deeper.
  if (country && level > 0) parts.push(badge(country));
  return parts.join('');
}

function kpiTile(label, value) {
  return `<div class="bg-base-200 rounded-lg p-2">
    <div class="text-[7px] uppercase tracking-wide text-base-content/50 truncate">${label}</div>
    <div class="text-sm font-semibold">${value}</div>
  </div>`;
}

function renderKpis(props) {
  const count = val(props, 'building_count');
  if (!count) return kpiTile('Buildings', 'No data');
  return [
    kpiTile('Buildings', formatCount(count)),
    kpiTile('Density', `${val(props, 'density').toFixed(0)} /km²`),
    kpiTile('Floor area', formatArea(val(props, 'floor_area_m2'))),
    kpiTile('Residential', `${val(props, 'type_residential_pct').toFixed(0)}%`),
  ].join('');
}

function updateRegionHeader(props, isEurope) {
  const nameEl = document.getElementById('regionName');
  const metaEl = document.getElementById('regionMeta');
  const kpisEl = document.getElementById('regionKpis');
  const hintEl = document.getElementById('mapHint');
  const clearBtn = document.getElementById('clearSelection');

  if (nameEl) nameEl.textContent = isEurope ? (props.name || 'Europe') : regionDisplayName(props);
  if (metaEl) metaEl.innerHTML = isEurope ? badge('Europe-wide', 'badge-primary badge-outline') : regionMetaBadges(props);
  if (kpisEl) kpisEl.innerHTML = renderKpis(props);
  // The "click a region" hint lives on the map; hide it once a region is picked.
  if (hintEl) hintEl.classList.toggle('hidden', !isEurope);
  if (clearBtn) clearBtn.classList.toggle('hidden', isEurope);
}

/* ============ CHART INITIALIZATION ============ */

function baseDoughnutOptions(colors) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { color: colors.chartText, font: { size: 10 }, boxWidth: 12 } },
      tooltip: {
        callbacks: {
          label: (ctx) => `${ctx.label || ''}: ${(ctx.parsed || 0).toFixed(1)}%`,
        },
      },
    },
  };
}

function baseBarOptions(colors) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: { ticks: { color: colors.chartText }, grid: { display: false } },
      y: {
        ticks: { callback: (v) => v + '%', color: colors.chartText },
        grid: { color: colors.chartGrid },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.y.toFixed(1)}%` } },
    },
  };
}

function initCharts() {
  const colors = getThemeColors();

  // Source distribution (doughnut)
  const sourceCtx = document.getElementById('sourceChart');
  if (sourceCtx) {
    charts.source = new Chart(sourceCtx, {
      type: 'doughnut',
      data: {
        labels: ['Government', 'OSM', 'Microsoft'],
        datasets: [{ data: [0, 0, 0], backgroundColor: ['#7c9ed9', '#7ec8a3', '#fcd7a1'], borderWidth: 0 }],
      },
      options: baseDoughnutOptions(colors),
    });
  }

  // Attribute provenance (stacked horizontal bar): gt / merged / estimated / none
  const coverageCtx = document.getElementById('coverageChart');
  if (coverageCtx) {
    charts.coverage = new Chart(coverageCtx, {
      type: 'bar',
      data: {
        labels: COVERAGE_ATTR_LABELS,
        datasets: [
          { label: 'Ground truth', data: [], backgroundColor: PROVENANCE.gt, stack: 's' },
          { label: 'Merged', data: [], backgroundColor: PROVENANCE.merged, stack: 's' },
          { label: 'ML-estimated', data: [], backgroundColor: PROVENANCE.est, stack: 's' },
        ],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            max: 100,
            ticks: { callback: (v) => v + '%', color: colors.chartText },
            grid: { color: colors.chartGrid },
          },
          y: { stacked: true, ticks: { color: colors.chartText }, grid: { display: false } },
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: colors.chartText, font: { size: 10 }, boxWidth: 12 } },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.x.toFixed(1)}%` } },
        },
      },
    });
  }

  // Building type (binary) pie
  const typeCtx = document.getElementById('typeChart');
  if (typeCtx) {
    charts.type = new Chart(typeCtx, {
      type: 'pie',
      data: {
        labels: ['Residential', 'Non-residential'],
        datasets: [{ data: [0, 0], backgroundColor: TYPE_COLORS, borderWidth: 0 }],
      },
      options: baseDoughnutOptions(colors),
    });
  }

  // Building subtype pie
  const subtypeCtx = document.getElementById('subtypeChart');
  if (subtypeCtx) {
    charts.subtype = new Chart(subtypeCtx, {
      type: 'pie',
      data: {
        labels: SUBTYPE_LABELS,
        datasets: [{ data: SUBTYPE_KEYS.map(() => 0), backgroundColor: SUBTYPE_COLORS, borderWidth: 0 }],
      },
      options: baseDoughnutOptions(colors),
    });
  }

  // Height distribution (bar)
  const heightCtx = document.getElementById('heightChart');
  if (heightCtx) {
    charts.height = new Chart(heightCtx, {
      type: 'bar',
      data: {
        labels: ['<5m', '5–<10m', '10–<20m', '20–<50m', '≥50'],
        datasets: [{ label: 'Buildings %', data: [0, 0, 0, 0, 0], backgroundColor: '#7ec8a3', borderRadius: 4 }],
      },
      options: baseBarOptions(colors),
    });
  }

  // Floor distribution (bar)
  const floorCtx = document.getElementById('floorChart');
  if (floorCtx) {
    charts.floor = new Chart(floorCtx, {
      type: 'bar',
      data: {
        labels: ['<2 floors', '2-<4 floors', '4-<7 floors', '≥7 floors'],
        datasets: [{ label: 'Buildings %', data: [0, 0, 0, 0], backgroundColor: '#9370b0', borderRadius: 4 }],
      },
      options: baseBarOptions(colors),
    });
  }

  // Floor area: residential vs non-residential share of total floor area
  const floorAreaCtx = document.getElementById('floorAreaChart');
  if (floorAreaCtx) {
    charts.floorArea = new Chart(floorAreaCtx, {
      type: 'doughnut',
      data: {
        labels: ['Residential', 'Non-residential'],
        datasets: [{ data: [0, 0], backgroundColor: TYPE_COLORS, borderWidth: 0 }],
      },
      options: baseDoughnutOptions(colors),
    });
  }

  // Floor area: distribution across the four residential subtypes only
  const floorAreaResCtx = document.getElementById('floorAreaResChart');
  if (floorAreaResCtx) {
    charts.floorAreaRes = new Chart(floorAreaResCtx, {
      type: 'doughnut',
      data: {
        labels: ['Detached', 'Semi-detached', 'Terraced', 'Apartment'],
        datasets: [{
          data: [0, 0, 0, 0],
          backgroundColor: RES_COLORS,
          borderWidth: 0,
        }],
      },
      options: baseDoughnutOptions(colors),
    });
  }
}

/* ============ CHART UPDATES ============ */

function updateCharts(props) {
  props = props || {};

  if (charts.source) {
    charts.source.data.datasets[0].data = [
      val(props, 'source_gov_pct'), val(props, 'source_osm_pct'), val(props, 'source_msft_pct'),
    ];
    charts.source.update();
  }

  if (charts.coverage) {
    // Bars deliberately need not reach 100%: the gap to the right is the
    // (unshown) "missing" share, e.g. buildings with no construction year.
    charts.coverage.data.datasets[0].data = COVERAGE_ATTRS.map(a => val(props, `${a}_gt_pct`));
    charts.coverage.data.datasets[1].data = COVERAGE_ATTRS.map(a => val(props, `${a}_merged_pct`));
    charts.coverage.data.datasets[2].data = COVERAGE_ATTRS.map(a => val(props, `${a}_est_pct`));
    charts.coverage.update();
  }

  if (charts.type) {
    charts.type.data.datasets[0].data = [
      val(props, 'type_residential_pct'), val(props, 'type_nonresidential_pct'),
    ];
    charts.type.update();
  }

  if (charts.subtype) {
    charts.subtype.data.datasets[0].data = SUBTYPE_KEYS.map(k => val(props, `subtype_${k}_pct`));
    charts.subtype.update();
  }

  if (charts.height) {
    charts.height.data.datasets[0].data = [
      val(props, 'height_0_5_pct'), val(props, 'height_5_10_pct'),
      val(props, 'height_10_20_pct'), val(props, 'height_20_50_pct'), val(props, 'height_50_inf_pct'),
    ];
    charts.height.update();
  }

  if (charts.floor) {
    charts.floor.data.datasets[0].data = [
      val(props, 'floors_0_2_pct'), val(props, 'floors_2_4_pct'), val(props, 'floors_4_7_pct'), val(props, 'floors_7_inf_pct'),
    ];
    charts.floor.update();
  }

  if (charts.floorArea) {
    const faNon = val(props, 'fa_non_residential_pct');
    // Fall back to the complement if the residential share isn't published yet.
    let faRes = val(props, 'fa_residential_pct');
    if (!faRes && faNon) faRes = Math.max(0, +(100 - faNon).toFixed(2));
    charts.floorArea.data.datasets[0].data = [faRes, faNon];
    charts.floorArea.update();
  }

  if (charts.floorAreaRes) {
    // Share among the four residential subtypes only (re-normalised to 100%).
    const res = [
      val(props, 'fa_detached_pct'), val(props, 'fa_semi_detached_pct'),
      val(props, 'fa_terraced_pct'), val(props, 'fa_apartment_pct'),
    ];
    const sum = res.reduce((a, b) => a + b, 0);
    charts.floorAreaRes.data.datasets[0].data =
      sum > 0 ? res.map(v => +(v / sum * 100).toFixed(2)) : res;
    charts.floorAreaRes.update();
  }
}

function updateChartThemes() {
  const colors = getThemeColors();
  Object.values(charts).forEach(chart => {
    if (!chart) return;
    if (chart.options.plugins?.legend?.labels) {
      chart.options.plugins.legend.labels.color = colors.chartText;
    }
    if (chart.options.scales) {
      Object.values(chart.options.scales).forEach(scale => {
        if (scale.ticks) scale.ticks.color = colors.chartText;
        if (scale.grid) scale.grid.color = colors.chartGrid;
      });
    }
    chart.update();
  });
}

/* ============ SHAREABLE URL STATE ============ */

// The selected region (nuts_id + level) and the active metric are mirrored to
// the query string so a link reproduces the view. State is written on every
// metric/region change and read back once on load.

function validMetric(metric) {
  const select = document.getElementById('metricSelect');
  if (!select || !metric) return false;
  return [...select.options].some(o => o.value === metric);
}

// NUTS level is implicit in the code length (country = 2 chars, then +1 per
// level), so only the region id needs to live in the URL.
function nutsLevelFromId(nuts_id) {
  return (nuts_id || '').length - 2;
}

function readUrlState() {
  const p = new URLSearchParams(location.search);
  const metric = p.get('metric');
  const region = p.get('region');
  return {
    metric: validMetric(metric) ? metric : null,
    region: region || null,
  };
}

function updateUrl() {
  const p = new URLSearchParams();
  p.set('metric', currentMetric);
  if (selectedRegion) p.set('region', selectedRegion.nuts_id);
  history.replaceState(null, '', `${location.pathname}?${p.toString()}`);
}

// Bounding box of a (possibly Multi)Polygon GeoJSON geometry → LngLatBounds.
function featureBounds(geometry) {
  const bounds = new maplibregl.LngLatBounds();
  const walk = (coords) => {
    if (typeof coords[0] === 'number') bounds.extend(coords);
    else coords.forEach(walk);
  };
  if (geometry && geometry.coordinates) walk(geometry.coordinates);
  return bounds;
}

// Once the tiles are loaded, find the shared region's feature (tiles carry all
// NUTS levels at every zoom) and select + frame it. No-op until the feature is
// available, so it can be retried on map idle.
function restoreSelectionFromUrl() {
  if (!pendingRegion || !map) return;
  const { nuts_id, nuts_level } = pendingRegion;
  const feats = map.querySourceFeatures('coverage', {
    sourceLayer: 'stats',
    filter: ['all', ['==', 'nuts_id', nuts_id], ['==', 'nuts_level', nuts_level]],
  });
  if (!feats.length) return;
  pendingRegion = null;
  selectRegion(feats[0].properties);
  try {
    const b = featureBounds(feats[0].geometry);
    // Keep a fair bit of context around the region rather than filling the map.
    if (!b.isEmpty()) map.fitBounds(b, { padding: 80, maxZoom: 6, duration: 0 });
  } catch (e) { /* framing is best-effort */ }
}

function setupShareButton() {
  const btn = document.getElementById('shareLink');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    updateUrl();
    const url = location.href;
    try {
      await navigator.clipboard.writeText(url);
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (_) { /* clipboard unavailable */ }
      document.body.removeChild(ta);
    }
    const original = btn.innerHTML;
    btn.innerHTML = '✓ Copied';
    setTimeout(() => { btn.innerHTML = original; }, 1500);
  });
}

/* ============ INITIALIZATION ============ */

async function init() {
  await Promise.all([loadNutsNames(), loadEuropeSummary()]);

  // Restore shared state from the URL: the metric must be applied before the
  // map builds its choropleth; the region is applied once its tiles load.
  const urlState = readUrlState();
  if (urlState.metric) currentMetric = urlState.metric;
  if (urlState.region) {
    pendingRegion = { nuts_id: urlState.region, nuts_level: nutsLevelFromId(urlState.region) };
  }

  initMap();
  initCharts();

  // Default panel: Europe-wide stats until a region is clicked.
  renderEuropeDefault();

  const metricSelect = document.getElementById('metricSelect');
  if (metricSelect) {
    metricSelect.value = currentMetric;
    metricSelect.addEventListener('change', (e) => onMetricChange(e.target.value));
  }
  updateCurrentMetricLabel();

  // Control panel: expanded on desktop, collapsed by default on mobile so it
  // doesn't cover the map. The user can still tap the header to open it.
  const panel = document.getElementById('controlPanel');
  if (panel) panel.open = !isMobile();

  const clearBtn = document.getElementById('clearSelection');
  if (clearBtn) clearBtn.addEventListener('click', clearSelection);

  setupShareButton();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
