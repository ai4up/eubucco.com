import logging
import os
import tempfile
import time
from pathlib import Path

import redis
import geopandas as gpd
from pottery import Redlock

from config import celery_app
from .converters import GeoPackageConverter, ShapefileConverter
from .minio_client import build_client, upload_file

RAW_FILES_DIR = Path("data/s3")
DATASET_NAME = "buildings"
SPATIAL_FORMATS = {
    "gpkg": (GeoPackageConverter(), ".gpkg"),
    # "shp": (ShapefileConverter(), ".zip"), # Currently not enough storage space for shapefiles
}

r = redis.Redis(
    host=os.environ["REDIS_URL"].split("//")[-1].split(":")[0],
    port=os.environ["REDIS_URL"].split(":")[-1].split("/")[0],
    db=os.environ["REDIS_URL"].split("/")[-1],
)


@celery_app.task(soft_time_limit=3600)
def ingest_all_by_version(version_tag: str = "v0.2", source_dir: str = RAW_FILES_DIR):
    """
    Triggers ingestion task for each NUTS region in the specified versioned source directory.
    """
    base_path = Path(source_dir) / version_tag
    if not base_path.exists():
        logging.error(f"Source dir not found: {base_path}")
        return

    found_files = 0
    for parquet_path in base_path.rglob("*.parquet"):
        # Fan out into individual tasks for horizontal scaling
        process_single_nuts.delay(version_tag, str(parquet_path))
        found_files += 1

    logging.info(f"Triggered processing for {found_files} NUTS files in {version_tag}")


@celery_app.task(soft_time_limit=3600)
def process_single_nuts(version_tag: str, file_path: str):
    """
    Handles one NUTS file:
    1. Direct binary upload to preserve Parquet schema.
    2. Conversion to GeoPackage, Shapefile, etc.
    """
    source = Path(file_path)
    nuts_id = source.stem
    client, settings = build_client()

    parquet_key = f"{DATASET_NAME}/{version_tag}/parquet/nuts_id={nuts_id}/{source.name}"
    logging.info(f"Uploading raw parquet: {parquet_key}")
    upload_file(client, settings, parquet_key, str(source))

    gdf = gpd.read_parquet(source)
    for fmt_name, (converter, ext) in SPATIAL_FORMATS.items():
        object_key = f"{DATASET_NAME}/{version_tag}/{fmt_name}/nuts_id={nuts_id}/{nuts_id}{ext}"

        with tempfile.TemporaryDirectory() as tmp_dir:
            base_output = Path(tmp_dir) / f"{nuts_id}{ext}"

            try:
                converter.convert(gdf, base_output, nuts_id)

                # Handle potential extension changes (e.g., .zip for shapefiles)
                upload_path = base_output if base_output.exists() else base_output.with_suffix('.zip')

                if upload_path.exists():
                    upload_file(client, settings, object_key, str(upload_path))
                    logging.info(f"Uploaded {fmt_name} for {nuts_id}")

            except Exception as e:
                logging.error(f"Failed conversion for {nuts_id} to {fmt_name}: {e}")


@celery_app.task(soft_time_limit=60, hard_time_limit=65)
def start_example_ingestion_tasks():
    """Wrapper to delay the start, ensuring infrastructure is ready."""
    time.sleep(5)
    ingest_all_by_version.delay()


def main():
    """Ensure ingestion runs only once across the cluster."""
    lock = Redlock(key="eubucco.minio.ingest.lock", masters={r}, auto_release_time=60)
    if lock.acquire(blocking=False):
        start_example_ingestion_tasks.delay()
        time.sleep(5)
        lock.release()
    else:
        logging.debug("Ingestion lock already held by another process.")

main()
