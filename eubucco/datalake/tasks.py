import logging
from pathlib import Path

from config import celery_app
from eubucco.datalake.constants import DATASET_PREFIX
from eubucco.datalake.minio_client import (
    build_client,
    ensure_bucket,
    public_s3_uri,
    upload_file,
)

RAW_FILES_DIR = Path("data/buildings")


@celery_app.task(soft_time_limit=60 * 60, hard_time_limit=(60 * 60) + 5)
def stage_existing_parquet(version_tag: str = "v0.1", source_dir: str = RAW_FILES_DIR):
    """
    Upload per-NUTS parquet files to MinIO with partitioned keys:
    s3://<bucket>/buildings/<version>/nuts_id=<NUTS>/file.parquet
    Expects files under data/buildings/<version>/.
    """
    base = Path(source_dir) / version_tag
    if not base.exists():
        raise FileNotFoundError(f"Parquet source dir not found: {base}")

    client, settings = build_client()
    ensure_bucket(client, settings)

    uploaded = 0
    for parquet_path in base.rglob("*.parquet"):
        nuts_id = parquet_path.stem
        object_key = f"{DATASET_PREFIX}/{version_tag}/nuts_id={nuts_id}/{parquet_path.name}"
        logging.info("Uploading %s -> %s", parquet_path, public_s3_uri(settings, object_key))
        upload_file(client, settings, object_key, str(parquet_path))
        uploaded += 1

    if uploaded == 0:
        logging.warning("No parquet files found under %s", base)
    else:
        logging.info("Uploaded %s parquet files for version %s", uploaded, version_tag)
