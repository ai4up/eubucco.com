import logging
import os
import tempfile
import time
from pathlib import Path

import redis
from celery import chord
from pottery import Redlock

from config import celery_app
from .converters import GeoPackageConverter, ShapefileConverter
from .minio_client import build_client, file_exists, upload_file
from .constants import DATASET_PREFIX

RAW_FILES_DIR = Path("data/s3")
SPATIAL_FORMATS = {
    "gpkg": (GeoPackageConverter(), ".gpkg"),
    "shp": (ShapefileConverter(), ".zip"),
}

r = redis.Redis(
    host=os.environ["REDIS_URL"].split("//")[-1].split(":")[0],
    port=os.environ["REDIS_URL"].split(":")[-1].split("/")[0],
    db=os.environ["REDIS_URL"].split("/")[-1],
)

# --- PHASE 1: PARQUET UPLOADS ---

@celery_app.task(soft_time_limit=600)
def upload_parquet_task(version_tag: str, file_path: str, reupload: bool = False):
    """Stage 1: Individual task to upload a single Parquet file."""
    source = Path(file_path)
    nuts_id = source.stem
    client, settings = build_client()
    parquet_key = f"{version_tag}/{DATASET_PREFIX}/parquet/nuts_id={nuts_id}/{source.name}"

    if reupload or not file_exists(client, settings, parquet_key):
        logging.info(f"Uploading: {parquet_key}")
        upload_file(client, settings, parquet_key, str(source))
    else:
        logging.info(f"Skipping existing parquet: {parquet_key}")

    return f"Uploaded {nuts_id}"


@celery_app.task
def notify_uploads_complete(results, version_tag: str, file_list: list, reupload: bool):
    """
    Notification 1: Triggered when ALL Parquet uploads are finished.
    Then triggers the Conversion Phase.
    """
    logging.info(f"--- PHASE 1 SUCCESS: {len(results)} Parquet files uploaded for {version_tag} ---")

    # Prepare Phase 2 tasks
    conversion_tasks = [
        convert_spatial_task.s(version_tag, f_path, reupload)
        for f_path in file_list
    ]

    # Final Chord: [Conversions] -> [Final Notification]
    callback = notify_all_complete.s(version_tag)
    chord(conversion_tasks)(callback)

    return "Phase 1 Complete, Phase 2 Dispatched"


# --- PHASE 2: CONVERSIONS ---

@celery_app.task(soft_time_limit=3000, acks_late=True)
def convert_spatial_task(version_tag: str, file_path: str, reupload: bool = False):
    """Stage 2: Heavy-duty conversion task. Isolated for OOM protection."""
    source = Path(file_path)
    nuts_id = source.stem
    client, settings = build_client()

    gdf = None
    for fmt_name, (converter, ext) in SPATIAL_FORMATS.items():
        object_key = f"{version_tag}/{DATASET_PREFIX}/{fmt_name}/nuts_id={nuts_id}/{nuts_id}{ext}"

        if not reupload and file_exists(client, settings, object_key):
            logging.info(f"Skipping existing {fmt_name} for {nuts_id}")
            continue

        try:
            if gdf is None:
                # Local import to prevent memory bloat on non-conversion workers
                import geopandas as gpd
                logging.info(f"Loading {nuts_id} for conversion...")
                gdf = gpd.read_parquet(source)

            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = Path(tmp_dir) / f"{nuts_id}{ext}"
                converter.convert(gdf, output_path, nuts_id)

                # Check for zip output (common for shapefiles)
                final_path = output_path if output_path.exists() else output_path.with_suffix('.zip')
                upload_file(client, settings, object_key, str(final_path))

        except Exception as e:
            logging.error(f"Conversion failed for {nuts_id} to {fmt_name}: {e}")

    return f"Converted {nuts_id}"


@celery_app.task
def notify_all_complete(results, version_tag: str):
    """Notification 2: Final success message."""
    logging.info(f"--- PHASE 2 SUCCESS: All conversions finished for {version_tag} ---")
    return "Full Pipeline Complete"


@celery_app.task
def ingest_all_by_version(version_tag: str = "v0.2", source_dir: str = RAW_FILES_DIR, reupload: bool = False):
    """Entry point: Discovers files and creates the first Chord."""
    base_path = Path(source_dir) / version_tag
    if not base_path.exists():
        logging.error(f"Source dir not found: {base_path}")
        return

    parquet_files = [str(p) for p in base_path.rglob("*.parquet")]

    if not parquet_files:
        logging.warning("No files found.")
        return

    # Phase 1: Upload Group
    upload_group = [upload_parquet_task.s(version_tag, f, reupload) for f in parquet_files]

    # Callback: Notify Success Phase 1 + Trigger Phase 2
    callback = notify_uploads_complete.s(version_tag, parquet_files, reupload)

    chord(upload_group)(callback)
    logging.info(f"Pipeline started: {len(parquet_files)} uploads queued.")


def main():
    """Locking mechanism to prevent concurrent runs."""
    lock = Redlock(key="eubucco.data.lock", masters={r}, auto_release_time=60)
    if lock.acquire(blocking=False):
        # Trigger the first task after a short delay
        ingest_all_by_version.apply_async(countdown=5)
        time.sleep(5)
        lock.release()
    else:
        logging.debug("Ingestion already in progress.")


if __name__ == "__main__":
    main()