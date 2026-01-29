# Data Format

## [Data Schema](../../data-format/schema)
The core dataset structure is organized into five functional groups:

* **Identifiers**: Unique building `id` and geographic identifies: `region_id` ([NUTS3](https://ec.europa.eu/eurostat/web/nuts/maps)) and `city_id` ([LAU](https://ec.europa.eu/eurostat/web/nuts/local-administrative-units)).
* **Attributes**: Building characteristics (`type`, `subtype`, `height`, `floors`, `year`).
* **Confidence**: Uncertainty of ML-based estimation and cross-source merging of attributes.
* **Sources**: Provenance tracking for every attribute (i.e. `osm`, `msft`, `gov-*`, `estimated`).
* **Geometry**: `ETRS89` footprints stored in Well-Known Binary (WKB) format.

## [File Format](../../data-format/format)
The EUBUCCO dataset is distributed in multiple file formats:

* Parquet (`.parquet`)
* GeoPackage (`.gpkg`)
* Shapefile (`.shp`)

## [Metadata Files](../../data-format/metadata)
In addition to the core building data, metadata information with respect to the source datasets, data retrieval dates, and attribute harmonization (e.g. building type mapping and aggregation) are provided as additional files.

## [Uncertainty](../../data-format/uncertainty)
For attributes that were estimated using machine learning techniques or merged from OpenStreetMap data, we provide an uncertainty quantification.