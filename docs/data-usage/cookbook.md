# Cookbook: Python & SQL

This reference provides essential snippets for cleaning, enriching, and transforming EUBUCCO data using GeoPandas or DuckDB.

---
## Identifiers 

#### Determining Block ID
EUBUCCO IDs are formatted as `{uuid}-{index}`. The prefix can be extracted to identify building blocks, i.e. clusters of adjacent buildings.

=== "GeoPandas"
    ```python
    gdf['block_id'] = gdf['id'].str.split('-').str[0]
    ```
=== "DuckDB"
    ```sql
    SELECT SPLIT_PART(id, '-', 1) AS block_id FROM buildings;
    ```

#### Determining NUTS 0, 1, or 2 Region

=== "GeoPandas"
    ```python
    gdf['NUTS_2'] = gdf['region_id'].str[:4]
    gdf['NUTS_1'] = gdf['region_id'].str[:3]
    gdf['country'] = gdf['region_id'].str[:2]  # EU VAT 2-digit country code
    ```
=== "DuckDB"
    ```sql
    SELECT LEFT(region_id, 2) AS country FROM buildings;
    ```

---
## Attribute Metadata

#### Handling Confidence Values
Authoritative data lacks explicit confidence scores. Fill these gaps with 1.0 to ensure they are not excluded during quality filters.

=== "GeoPandas"
    ```python
    gdf["type_confidence"] = gdf["type_confidence"].fillna(1.0)
    ```
=== "DuckDB"
    ```sql
    SELECT COALESCE(type_confidence, 1.0) as type_confidence FROM buildings;
    ```

#### Attribute Source Comparison
Determine if an attribute was merged from an external source or estimated using ML by identifying mismatches between geometry and attribute sources.

=== "GeoPandas"
    ```python
    gdf["is_inferred"] = gdf["geometry_source"] != gdf["type_source"]
    ```
=== "DuckDB"
    ```sql
    SELECT *, (geometry_source != type_source) AS is_inferred FROM buildings;
    ```

#### Custom Building Type Harmonization
Map raw subtypes from source datasets to custom building type classification.
=== "GeoPandas"
    ```python
    osm_map = {
        'apartments': 'high_density',
        'detached': 'low_density',
        'retail': 'economic'
    }
    gdf['urban_function'] = gdf['subtype_raw'].map(osm_map).fillna('unclassified')
    ```
=== "DuckDB"
    ```sql
    SELECT 
        subtype_raw,
        CASE 
            WHEN subtype_raw IN ('apartments', 'terrace') THEN 'high_density'
            WHEN subtype_raw IN ('detached', 'house') THEN 'low_density'
            WHEN subtype_raw IN ('retail', 'office') THEN 'economic'
            ELSE 'unclassified' 
        END AS urban_function
    FROM buildings;
    ```

---
## Geometry 

#### Decoding WKB and WKT
Geometries are stored as Well-Known Binary (WKB). Use these methods for manual decoding or to export human-readable Well-Known Text (WKT).


=== "Pandas (WKB Parsing)"
    ```python
    import pandas as pd
    import geopandas as gpd
    from shapely import wkb

    # Load raw parquet (geometry is binary)
    df = pd.read_parquet("data.parquet")

    # Fast decoding of WKB column to Shapely objects
    gdf = gpd.GeoDataFrame(
        df, 
        geometry=gpd.GeoSeries.from_wkt(df["geometry"]),
        # OR geometry=df["geometry"].apply(wkb.loads),
        crs="EPSG:3035"
    )
    ```
=== "DuckDB (WKB Export)"
    ```sql
    SELECT id, ST_AsWKB(geometry) AS geometry FROM buildings;
    ```
=== "DuckDB (WKT Export)"
    ```sql
    -- Convert binary to human-readable strings
    SELECT id, ST_AsText(geometry) AS geometry FROM buildings;
    ```

#### Coordinate Reference System (CRS) Transformation
Convert building geometries from the local projected CRS (`EPSG:3035`) to WGS84 (Lat/Lng).

=== "GeoPandas"
    ```python
    gdf = gdf.to_crs(epsg=4326)
    ```
=== "DuckDB"
    ```sql
    SELECT 
        * EXCLUDE geometry, 
        ST_Transform(geometry, 'EPSG:3035', 'EPSG:4326') AS geometry 
    FROM buildings;
    ```

#### Centroid Generation
Replace building footprints with centroids to reduce computational overhead for point-in-polygon operations or visualization.

=== "GeoPandas"
    ```python
    gdf["geometry"] = gdf.centroid
    ```
=== "DuckDB"
    ```sql
    SELECT * EXCLUDE geometry, ST_Centroid(geometry) AS geometry FROM buildings;
    ```

#### H3 Grid Aggregation

Map buildings to hexagonal grid ([H3](https://h3geo.org/)) for analysis.

=== "Python (h3pandas)"
    ```python
    import h3pandas
    # Automatically handles centroid extraction and CRS shift to WGS84
    # 'res=9' provides a spatial resolution of ~0.1km²
    h3_gdf = gdf.h3.geo_to_h3_aggregate(res=9, operation='count')
    ```
=== "Python (h3-py + GeoPandas)"
    ```python
    import h3
    # Manual approach: Transform -> Centroid -> Map
    gdf['h3_9'] = gdf.centroid.to_crs(epsg=4326).apply(
        lambda g: h3.latlng_to_cell(g.y, g.x, 9)
    )
    h3_stats = gdf.groupby('h3_9').size()
    ```
=== "DuckDB"
    ```sql
    -- Transform to EPSG:4326 within the H3 function call
    SELECT 
        h3_latlng_to_cell(
            ST_Y(ST_Transform(ST_Centroid(geometry), 'EPSG:3035', 'EPSG:4326')), 
            ST_X(ST_Transform(ST_Centroid(geometry), 'EPSG:3035', 'EPSG:4326')), 
            9
        ) AS cell,
        COUNT(*) AS count
    FROM buildings
    GROUP BY cell;
    ```