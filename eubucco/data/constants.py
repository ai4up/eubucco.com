# Top-level "dataset" prefixes inside the MinIO bucket, under a {version}/ prefix.
# Object keys look like: {version}/{DATASET_PREFIX}/parquet/nuts_id={id}/{file}.parquet
DATASET_PREFIX = "buildings"
ADDITIONAL_PREFIX = "additional"

# Filename (under {version}/{ADDITIONAL_PREFIX}/) holding human-readable
# descriptions for the additional-files download table.
ADDITIONAL_METADATA_NAME = "metadata.json"
