# Accessing the Data

This guide outlines various methods to access and download the EUBUCCO dataset, which is hosted on S3-compatible storage (MinIO).
<!-- The data is partitioned by region (`nuts_id`) and stored in Apache Parquet format. -->

---

## Overview of Data Access Methods

| Method | Best For | Description |
| :--- | :--- | :--- |
| **[Website](../../data-access/website)** | Less technical users | Download individual region files via a map-based interface. |
| **[CLI](../../data-access/cli)** | Bulk downloads | Sync entire countries or the full dataset to your local storage. |
| **[Python](../../data-access/python)** | Quick data exploration | Stream specific regions into memory (GeoPandas) or filter chunks (PyArrow). |
| **[SQL (DuckDB)](../../data-access/sql)** | Advanced Filtering | Query the cloud data directly to download only specific subsets (e.g., buildings > 50m). |
| **[Zenodo](../../data-access/zenodo)** | Research & Citations | Access stable, versioned snapshots for scientific reproducibility. |