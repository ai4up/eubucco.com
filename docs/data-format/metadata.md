# Metadata Files

EUBUCCO includes comprehensive metadata files to support data exploration, validation, analysis, and reproducibility. These files are organized into four main categories:

| Category | Files | Description |
|----------|-------|---------|
| **Data Files** | `eubucco_lat_lon.parquet` | Lightweight building dataset |
| **Boundaries** | `LAU-cities-2016.parquet`, `NUTS-regions-2016.parquet` | Administrative boundaries used |
| **Statistics** | `city-stats.parquet`, `region-stats.parquet`, `prediction-eval-metrics.parquet` | Aggregated statistics and evaluation metrics |
| **Reference Tables** | `building-type-harmonization.csv`, `input-datasets-metadata.xlsx` | Source dataset information and type mappings |

---

## Data Files

### `eubucco_lat_lon.parquet`

A lightweight version of the EUBUCCO v0.2 dataset containing only building centroids (latitude/longitude coordinates) and footprint area, without full footprint geometries.

---

## Boundary Files

### `LAU-cities-2016.parquet`

City ([LAU](https://ec.europa.eu/eurostat/web/nuts/local-administrative-units)) administrative boundaries used in EUBUCCO v0.2, based on 2016 boundaries.

**Contents**: `city_id`, `region_id` and `geometry` for each city.

---

### `NUTS-regions-2016.parquet`

Regional ([NUTS 0-3](https://ec.europa.eu/eurostat/web/nuts/maps)) administrative boundaries used in EUBUCCO v0.2, based on [2016 boundaries](https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/).

**Contents**: `region_id`, `region_name`, and `geometry` for each NUTS region at all levels (0-3).

!!! warning "NUTS Code Discrepancies"
    EUBUCCO uses modified [NUTS 2016 boundaries](https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/) with two regional merges (DEB33 → DEB3H, UKD73 → UKD47) and one reconstructed region: UKN1 was missing from the official download but reconstructed from its NUTS 3 components.

---

## Statistics Files

### `city-stats.parquet`

Comprehensive building stock statistics aggregated at the **city ([LAU](https://ec.europa.eu/eurostat/web/nuts/local-administrative-units)) level**. This *GeoDataFrame* includes city geometry and provides detailed metrics for each city.

#### Administrative Information
- `city_id`, `region_id` (NUTS 3), `country`
- City geometry (CRS: EPSG:3035)

#### Building Counts by Source
- `n_gov`, `n_osm`, `n_msft` — Total counts by geometry source

#### Data Quality Indicators
- Ground truth counts: Buildings with attributes from the same source as geometry
  - `n_gt_type`, `n_gt_subtype`, `n_gt_height`, `n_gt_floors`, `n_gt_construction_year`
- Merged attribute counts: Buildings with attributes merged from different sources
  - `n_merged_type`, `n_merged_subtype`, `n_merged_height`, `n_merged_floors`, `n_merged_construction_year`
- Estimated attribute counts: Buildings with estimated attributes
  - `n_estimated_type`, `n_estimated_subtype`, `n_estimated_height`, `n_estimated_floors`

#### Building Type Distributions
- Main types: Residential, non-residential (counts and areas)
- Subtypes: Commercial, industrial, agricultural, public, others, detached, semi-detached, terraced, apartment (counts and areas)

#### Attribute Distributions
- Height bins: 0-5m, 5-10m, 10-20m, >20m
- Floor bins: 0-3, 4-6, >6 floors
- Construction year bins: ≤1900, 1901-1970, 1971-2000, >2000
- Footprint area bins: 0-25m², 25-100m², 100-500m², >500m²

#### Area Metrics
- Total footprint area and floor area
- Breakdowns by source (gov, osm, msft), type, and subtype

---

### `region-stats.parquet`

Building stock statistics aggregated at the **regional ([NUTS 3](https://ec.europa.eu/eurostat/web/nuts/maps)) level**. Contains the same metrics as city-level statistics but aggregated to NUTS 3 regions, including regional geometry.

---

### `prediction-eval-metrics.parquet`

Regional ([NUTS 2](https://ec.europa.eu/eurostat/web/nuts/maps)) evaluation metrics for building attribute estimation models. This *GeoDataFrame* provides comprehensive performance metrics for predicted building attributes.

#### Administrative Information
- `region_id` (NUTS 2), `country`
- Regional geometry (CRS: EPSG:3035)

#### Sample Sizes
- `n` — Total number of buildings
- `n_gt_binary_type`, `n_gt_type`, `n_gt_residential_type`, `n_gt_height`, `n_gt_floors` — Ground truth counts per attribute

#### Categorical Variable Metrics
For binary_type, type, and residential_type:

- Overall classification metrics: F1 score (macro and micro), Cohen's kappa
- Per-class F1 scores: Individual F1 scores for each building type/subtype

#### Continuous Variable Metrics
For height and floors:

- Overall metrics: MAE, RMSE, R² score
- Binned metrics: MAE and RMSE by value ranges
  - Height: 0-5m, 5-10m, 10-20m, >20m
  - Floors: 0-3, 3-6, >6

#### External Validation
For height:

- Microsoft height comparison: Metrics comparing predicted height with heights from Microsoft's [GlobalMLBuildingFootprints](https://github.com/microsoft/GlobalMLBuildingFootprints) dataset


---

## Reference Tables

### `building-type-harmonization.csv`

Mapping table showing how building types from various source datasets are harmonized to the standardized EUBUCCO building type classification.


---

### `input-datasets-metadata.xlsx`

Comprehensive metadata table providing detailed information about all source datasets used in EUBUCCO v0.2.

#### Contents

- Dataset identification: Name, country, geographic coverage
- Access information: Data owner, license, access date, download links or procedures
- Technical details: File format, data structure, attribute availability
- Integration information: Processing workflow and integration approach
