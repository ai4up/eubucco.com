# Accessing the Data

This guide outlines various methods to access and download the EUBUCCO dataset, which is hosted on S3-compatible storage (MinIO).
<!-- The data is partitioned by region (`nuts_id`) and stored in Apache Parquet format. -->

---

## Overview of Data Access Methods

| Method | Best For | Description |
| :--- | :--- | :--- |
| **[Website](website.md)** | Less technical users | Download individual region files via a map-based interface. |
| **[CLI](cli.md)** | Bulk downloads | Sync entire countries or the full dataset to your local storage. |
| **[Python](python.md)** | Quick data exploration | Stream specific regions into memory (GeoPandas) or filter chunks (PyArrow). |
| **[SQL (DuckDB)](sql.md)** | Advanced Filtering | Query the cloud data directly to download only specific subsets (e.g., buildings > 50m). |
| **[Zenodo](zenodo.md)** | Research & Citations | Access stable, versioned snapshots for scientific reproducibility. |