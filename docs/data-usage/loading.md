# Efficient Data Loading & Filtering

Filtering at the data-loading stage is the most efficient way to extract specific building subsets based on quality, source, or geography. By using predicate pushdown across partitioned files, you avoid reading unnecessary data into memory.

!!! info "Prerequisites"
    The following commands assume that you have downloaded the complete EUBUCCO dataset, e.g. using the [CLI](../data-access/cli.md):
    ```bash
    aws s3 cp s3://eubucco/v0.2/buildings/parquet/ ./eubucco-data/ \
        --endpoint-url https://dev-s3.eubucco.com \
        --no-sign-request \
        --recursive
    ```

---
## Spatial Filtering

#### Bounding Box Filtering
Limit the dataset to a specific geographic extent using helper columns. 

=== "GeoPandas"
    ```python
    import geopandas as gpd
    import glob
    
    # GeoPandas only reads the subsets of the data that intersect the bbox
    bbox = (5300000, 1880000, 5400000, 1920000)
    gdf = gpd.read_parquet("eubucco_data/", bbox=bbox)
    ```
=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    dataset = ds.dataset("eubucco_data/")
    
    table = dataset.to_table(filter=(
        (ds.field("bbox.xmin") >= 5300000) & (ds.field("bbox.xmax") <= 5400000) &
        (ds.field("bbox.ymin") >= 1880000) & (ds.field("bbox.ymax") <= 1920000)
    ))
    ```
=== "DuckDB"
    ```sql
    -- Use the glob pattern '**/*.parquet' to scan all regional files
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE bbox.xmin >= 5300000 AND bbox.xmax <= 5400000
      AND bbox.ymin >= 1880000 AND bbox.ymax <= 1920000;
    ```

#### Administrative Regions Filtering
Limit the dataset to specific cities, regions, or countries using the partition keys and `region_id` (NUTS 0/1/2) or `city_id` row group metadata.

=== "GeoPandas"
    ```python
    import geopandas as gpd

    # Filter for a specific city
    gdf = gpd.read_parquet("eubucco_data/", filters=[("city_id", "==", "EL22040104")])

    # Filter for all regions e.g. in Greece [EL]
    gdf = gpd.read_parquet("eubucco_data/", filters=[("region_id", ">=", "EL"), ("region_id", "<", "EM")])
    ```
=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    dataset = ds.dataset("eubucco_data/")
    
    # Filter for a specific city
    city_table = dataset.to_table(filter=ds.field("city_id") == "EL22040104")

    # Filter for all regions (e.g. in Greece [EL])
    country_table = dataset.to_table(filter=ds.field("region_id").starts_with("EL"))
    ``` 
=== "DuckDB"
    ```sql
    -- Querying a specific city
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE city_id = 'EL22040104';

    -- Querying all regions e.g. in Greek [EL]
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE region_id LIKE 'EL%';
    ```

---
## Source Filtering

#### Filtering by Footprint Source

Discard ML-derived footprints (i.e. Microsoft Footprints).
=== "GeoPandas"
    ```python
    import geopandas as gpd

    gdf = gpd.read_parquet("eubucco_data/", filters=[("geometry_source", "!=", "msft")])
    ```
=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    dataset = ds.dataset("eubucco_data/")
    table = dataset.to_table(filter=ds.field("geometry_source") != "msft")
    ```
=== "DuckDB"
    ```sql
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE geometry_source != 'msft';
    ```
Filter for governmental data / discard non-authoritative sources (i.e. OSM and Microsoft ML).
=== "GeoPandas"
    ```python
    import geopandas as gpd

    gdf = gpd.read_parquet("eubucco_data/", filters=[("geometry_source", "not in", ["msft", "osm"])])
    ```
=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    dataset = ds.dataset("eubucco_data/")
    table = dataset.to_table(filter=~ds.field("geometry_source").isin(["msft", "osm"]))
    ```
=== "DuckDB"
    ```sql
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE geometry_source NOT IN ('msft', 'osm');
    ```

#### Filtering by Attribute Source

Isolate records where the specific attribute was not estimated using ML.
=== "GeoPandas"
    ```python
    import geopandas as gpd

    gdf = gpd.read_parquet("eubucco_data/", filters=[("type_source", "!=", "estimated")])
    ```
=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    dataset = ds.dataset("eubucco_data/")
    table = dataset.to_table(filter=ds.field("type_source") != "estimated")
    ```
=== "DuckDB"
    ```sql
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE type_source != 'estimated';
    ```

Isolate records where the specific attribute comes from the same source as the footprint geometry (i.e. the attribute was neither merged nor estimated using ML).
=== "DuckDB"
    ```sql
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    WHERE geometry_source = type_source;
    ```

---
## Column Filtering

Select only the footprint geometry and the main building attributes, and discard the remaining metadata columns.

=== "GeoPandas"
    ```python
    import geopandas as gpd

    columns = [
        "id", "region_id", "city_id", 
        "type", "subtype", "height", "floors", 
        "construction_year", "geometry"
    ]

    gdf = gpd.read_parquet("eubucco_data/", columns=columns)
    ```

=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    columns = [
        "id", "region_id", "city_id", 
        "type", "subtype", "height", "floors",
        "construction_year", "geometry"
    ]
    
    dataset = ds.dataset("eubucco_data/")
    table = dataset.to_table(columns=columns)
    ```

=== "DuckDB"
    ```sql
    SELECT 
        id,
        region_id,
        city_id,
        type,
        subtype,
        height,
        floors,
        construction_year,
        ST_AsText(geometry) AS geometry
    FROM read_parquet('eubucco_data/**/*.parquet');
    ```

---
## Confidence Filtering
Discard buildings with merged or estimated attributes that carry high uncertainty. We treat authoritative data (where confidence is `NaN`) as 100% certain.


> **Performance:** Since data isn't partitioned or sorted by confidence, metadata-based skipping is unavailable. However, filtering while reading in small buffers keeps memory usage low.

=== "GeoPandas"
    ```python
    import geopandas as gpd

    gdf = gpd.read_parquet("eubucco_data/")
    
    # Categorical: Type confidence > 80%
    high_conf = gdf[gdf["type_confidence"].fillna(1.0) > 0.8]

    # Numerical: Precise height (uncertainty interval < 2m)
    precise_height = gdf[(gdf["height_confidence_upper"] - gdf["height_confidence_lower"]) < 2.0]    
    ```
=== "PyArrow"
    ```python
    import pyarrow.dataset as ds

    # Categorical: Type confidence > 80%
    precise_type = (ds.field("type_confidence") > 0.8) | ds.field("type_confidence").is_null()

    # Numerical: Precise height (uncertainty interval < 2m)
    height_spread = ds.field("height_confidence_upper") - ds.field("height_confidence_lower")
    precise_height = (height_spread < 2.0) | ds.field("height_confidence_upper").is_null()


    dataset = ds.dataset("eubucco_data/")
    table = dataset.to_table(filter=(precise_type & precise_height))
    ```
=== "DuckDB"
    ```sql
    SELECT * FROM read_parquet('eubucco_data/**/*.parquet') 
    -- Categorical confidence
    WHERE COALESCE(type_confidence, 1.0) > 0.8 
    -- Numerical confidence
    AND (height_confidence_upper - height_confidence_lower) < 2.0;
    ```
