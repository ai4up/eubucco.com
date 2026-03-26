# Data File Format

The EUBUCCO dataset is natively **optimized for Parquet**. While we provide other formats for broad compatibility and convenience, the Parquet distribution is the primary format designed to handle continental-scale analysis with high performance.

|  | Parquet | GeoPackage | Shapefile |
| :--- | :--- | :--- | :--- |
| **Support Level** | **Recommended** | Experimental | Experimental |
| **Performance** | Excellent | Good | Fair |
| **Compression** | High | Medium | Low |
| **Querying** | Columnar (Best) | SQL/Indexed (Good) | Flat-file (Poor) |
| **Selective Reads** | Yes (Columns & Rows) | Yes (via SQL) | No (Full file load) |

---

### Parquet (`.parquet`)
An open-source, columnar storage format optimized for efficient data storage and retrieval.

* **Best for:** Large-scale analysis using Python (Pandas/GeoPandas), R, or Big Data tools.
* **Pros:** Smallest file size, fastest to read, and supports selective reads and predicate pushdown filtering.
* **Cons:** Limited native support in older GIS desktop software without plugins.

!!! tip "Recommended"
    Native format of the dataset.

---

### GeoPackage (`.gpkg`)
An open, non-proprietary, SQLite-based container for geospatial data.

* **Best for:** General GIS work in QGIS, ArcGIS Pro, or mobile mapping apps.
* **Pros:** Single-file convenience, widely compatible, and supports large datasets better than Shapefiles.
* **Cons:** Increased file size and slower read speeds compared to Parquet.

!!! warning "Experimental"
    Provided as a convenience for desktop GIS users. Minor typing discrepancies may occur during the automated conversion from the native Parquet source.

---

### Shapefile (`.shp`)
The legacy industry standard for geospatial vector data.

* **Best for:** Compatibility with older legacy software.
* **Pros:** Universal support across almost every GIS tool ever made.
* **Cons:** Large files, slow reading, and limited to 2GB per file. No querying possible; all data must be read into memory.

!!! warning "Experimental"
    Provided for legacy GIS software compatibility but generally not recommended. Automated conversion from Parquet may cause minor typing discrepancies. Crucially, some EUBUCCO regions exceed the 2GB limit. Column names differ from Parquet and GeoPackage files due to 10 character limit. Some values have been truncated to 264 characters.

---
