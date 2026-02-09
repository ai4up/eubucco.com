import logging
import os
import tempfile
import time
from pathlib import Path

import redis
from celery import chord, chain, group
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
def ingest_all_by_version(
    version_tag: str = "v0.2",
    reupload: bool = False,
    run_upload: bool = True,
    run_conversion: bool = True
):
    base_path = Path(RAW_FILES_DIR) / version_tag
    parquet_files = [str(p) for p in base_path.rglob("*.parquet")]

    if not parquet_files:
        return "No files found."

    pipeline = []

    # PHASE 1: Uploads
    if run_upload:
        upload_tasks = group(upload_parquet_task.s(version_tag, f, reupload) for f in parquet_files)
        # Use .si() for the callback to prevent passing strings into the next chain link
        pipeline.append(chord(upload_tasks, notify_phase_complete.si(None, "Upload")))

    # PHASE 2: Conversions
    if run_conversion:
        conversion_tasks = group(convert_spatial_task.s(version_tag, f, reupload) for f in parquet_files)
        pipeline.append(chord(conversion_tasks, notify_phase_complete.si(None, "Conversion")))

    # Final Step: Notification
    pipeline.append(notify_all_complete.si(None, version_tag))

    # Construct the sequential chain
    chain(*pipeline).apply_async(link_error=on_pipeline_failure.s())

    logging.info(f"Data ingestion pipeline sequenced for {version_tag}")


@celery_app.task
def notify_phase_complete(results, phase_name: str):
    count = len(results) if results else "unknown"
    logging.info(f"--- PHASE SUCCESS: {phase_name} phase finished with {count} items ---")
    return f"{phase_name} complete"


@celery_app.task
def notify_all_complete(results, version_tag: str):
    logging.info(f"Full data ingestion pipeline completed for {version_tag}.")


@celery_app.task
def on_pipeline_failure(request, exc, traceback):
    logging.error(f"Data ingestion pipeline failed: {exc}")


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