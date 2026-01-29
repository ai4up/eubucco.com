# 🐍 Python (GeoPandas / PyArrow)

Python is ideal for quickly streaming data directly into memory for exploration or small-scale analysis.

### 1. Using GeoPandas
GeoPandas uses `fsspec` under the hood to handle S3 paths. Use `storage_options` to point to the EUBUCCO endpoint.

=== "Download single region"
    ```Python
    import geopandas as gpd

    storage_opts = {
        "anon": True,
        "client_kwargs": {"endpoint_url": "https://dev-s3.eubucco.com"}
    }

    # Example: Download Liguria (ITC3)
    path = "s3://eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet"
    gdf = gpd.read_parquet(path, storage_options=storage_opts)
    ```


### 2. Using PyArrow
PyArrow is significantly more efficient for large data chunks because it only loads the specific partitions or rows you filter for (predicate pushdown).

=== "Download single region"
    ```Python
    import fsspec
    import pyarrow.dataset as ds

    fs = fsspec.filesystem(
        protocol="s3",
        anon=True,
        client_kwargs={"endpoint_url": "https://dev-s3.eubucco.com"}
    )

    # Example: Download Liguria (ITC3)
    dataset = ds.dataset(
        source="eubucco/v0.2/buildings/parquet/nuts_id=ITC3",
        filesystem=fs,
        format="parquet",
    )
    table = dataset.to_table()
    ```

=== "Download larger chunks"
    ```Python
    import fsspec
    import pyarrow.dataset as ds

    fs = fsspec.filesystem(
        protocol="s3",
        anon=True,
        client_kwargs={"endpoint_url": "https://dev-s3.eubucco.com"}
    )

    dataset = ds.dataset(
        source="eubucco/v0.2/buildings/parquet/",
        filesystem=fs,
        format="parquet"
    )

    # Example: Get all data for Italy (regions starting with "IT")
    table = dataset.to_table(filter=ds.field("nuts_id").starts_with("IT"))
    ```

```Python
# Optionally convert to DataFrame or GeoDataFrame
df = table.to_pandas()
gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.GeoSeries.from_wkb(df["geometry"]),
    crs="EPSG:3035",
)
```
