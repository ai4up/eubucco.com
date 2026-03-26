# 💻 Command Line Interface (CLI)

EUBUCCO data is hosted on an S3-compatible object store and can be accessed using standard command-line tools. Below are several options depending on your setup and preferences.

### 1. Using AWS CLI
The standard AWS CLI can be used to access EUBUCCO data by specifying the custom endpoint and using the `--no-sign-request` flag for anonymous access.

=== "Download single region"

    ```bash
    # Example: Download Liguria (ITC3)
    aws s3 cp s3://eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet . \
        --endpoint-url https://dev-s3.eubucco.com \
        --no-sign-request
    ```

=== "Download entire dataset"

    ```bash
    # Example: Download the entire v0.2 dataset
    aws s3 cp s3://eubucco/v0.2/buildings/parquet/ ./eubucco-data/ \
        --endpoint-url https://dev-s3.eubucco.com \
        --no-sign-request \
        --recursive
    ```

### 2. Using MinIO Client
The MinIO CLI `mc` is another convenient option for interacting with S3-compatible storage services.

Setup:
```bash
mc alias set eubucco https://dev-s3.eubucco.com "" ""
```

=== "Download single region"
    ```bash
    mc cp eubucco/eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet .
    ```

=== "Download entire dataset"
    ```bash
    mc cp --recursive eubucco/eubucco/v0.2/buildings/parquet/ .
    ```

### 3. Using Standard Network Utilities

For users on systems without S3 clients, standard network utilities provide a lightweight alternative for direct file retrieval.

=== "wget"
    ```bash
    wget -c --show-progress https://dev-s3.eubucco.com/eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet
    ```

=== "cURL"
    ```bash
    curl -OC - --retry 5 https://dev-s3.eubucco.com/eubucco/v0.2/buildings/parquet/nuts_id=ITC3/ITC3.parquet
    ```
