# 🦆 DuckDB (SQL)

DuckDB offers the most powerful way to query EUBUCCO. It treats the S3 bucket like a database, letting you filter by geography before any data is actually downloaded.

### 1. Using SQL

#### Configuration
Install spatial extension:
```SQL
INSTALL httpfs; LOAD httpfs;
INSTALL spatial; LOAD spatial
```

Configure EUBUCCO's MinIO endpoint:
```SQL
SET s3_endpoint='dev-s3.eubucco.com';
SET s3_url_style='path';
```

#### Data access

=== "Download single region"
    ```SQL
    SELECT * FROM 's3://eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet' 
    LIMIT 10
    ```

=== "Download larger chunks"
    By using hive_partitioning, DuckDB understands the folder structure (e.g., `nuts_id=...`) and can filter hundreds of files instantly.

    ```SQL
    -- Example: Query all of France (FR) for buildings higher than 50 meters
    SELECT id, height, ST_AsText(geometry) 
    FROM read_parquet(
        's3://eubucco/v0.2/buildings/parquet/**/*.parquet',
        hive_partitioning = true
    )
    WHERE nuts_id LIKE 'FR%' 
    AND height > 50;
    ```

### 2. Using DuckDB's Python library
```bash
pip install duckdb
```

```Python
import duckdb

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("INSTALL spatial; LOAD spatial;")

con.execute("SET s3_endpoint='dev-s3.eubucco.com';") 
con.execute("SET s3_url_style='path';")
```


```Python
query = """
SELECT * EXCLUDE geometry, ST_AsWKB(geometry) AS geometry FROM 's3://eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet' 
LIMIT 10
"""
# Fetch data with WKB-encoded geometries
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

