# Data Partitioning and Sorting

EUBUCCO Parquet files use a specific physical layout to optimize data access and minimize I/O overhead for large-scale geospatial analysis.

---

## Partitioning

The dataset uses **Hive-style partitioning** by **NUTS2** regions, where each region is stored in its own directory.

* **Format**: `eubucco/v0.2/buildings/parquet/nuts_id=<ID>/<ID>.parquet`

**Benefits:**

* **Partition Pruning**: Query engines can skip entire directories when filtering by region, dramatically reducing I/O
* **Selective Access**: Download or process only specific geographic regions

For examples of leveraging partitioning in queries, see [Efficient Data Loading & Filtering](../data-usage/loading.md).

!!! note "Partition Key vs. Data Column"
    The partition key `nuts_id` (NUTS2) corresponds to the parent region of the `region_id` (NUTS3) column in the dataset.

---

## Sorting

Within each partition file, rows are sorted using a multi-level hierarchy to optimize data locality:

1.  **Source Type**: Grouped by dataset origin (`gov`, `msft`, `osm`)
2.  **NUTS3 Region**: Sub-regional grouping via `region_id`
3.  **City ID (LAU)**: Local administrative unit via `city_id`

**Benefits:**

* **Spatial Locality**: Buildings in the same city are stored contiguously, improving cache efficiency
* **Predicate Pushdown**: Row group statistics enable efficient spatial filtering without reading entire files
* **Source Grouping**: Buildings from the same source are clustered together, facilitating source-based filtering

!!! tip "How Sorting Enables Efficient Filtering"
    By sorting down to the **City ID** level, the dataset achieves a high degree of spatial clustering. Parquet files are internally divided into **row groups**, each containing metadata with min/max statistics for columns. The spatial sorting ensures that buildings within the same geographic area (city) are stored in the same row groups, allowing query engines to examine row group metadata and skip entire row groups that fall outside query bounds without reading their data.
    
    In practice, this provides bounding box (BBOX) filtering performance nearly equivalent to more complex spatial indices (like Hilbert or Z-order curves) while maintaining a simpler, human-readable hierarchy.
