# 🖱️ File Downloads via Website

The [EUBUCCO Data Portal](https://eubucco.com/files/) is the most user-friendly way to browse and download data.

- **Formats:** Available as `.parquet`, `.gpkg`, and `.shp` files
- **Partitioning:** The dataset is split into multiple files, each containing all buildings within a single [NUTS2 region](https://ec.europa.eu/eurostat/web/nuts/maps).
- **Batch download:** Larger regions (e.g. federal states or entire countries) can be downloaded as ZIP archives containing all regional NUTS2 files.
- **Metadata:** Additional files include information on source datasets, type matching, regional statistics, and more.


### Reading downloaded Parquet files

=== "Read single file (GeoPandas)"
    ```Python
    import geopandas as gpd

    path = "/path/to/downloaded/file.parquet"
    gdf = gpd.read_parquet(path)
    ```

=== "Read multiple files (GeoPandas)"
    ```Python
    import geopandas as gpd

    path = "/path/to/downloaded/unzipped/directory"
    gdf = gpd.read_parquet(path)
    ```

=== "Read multiple files (DuckDB)"
    ```Python
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    ```


    ```Python
    # Read data with WKB-encoded geometries
    query = """
    SELECT
        * EXCLUDE geometry,
        ST_AsWKB(geometry) AS geometry
    FROM read_parquet('/path/to/your/folder/*.parquet')
    """
    df = con.execute(query).arrow().to_pandas()
    ```

    ```Python
    # Optionally convert to GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.GeoSeries.from_wkb(df["geometry"]),
        crs="EPSG:3035",
    )
    ```
