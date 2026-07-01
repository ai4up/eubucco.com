"""Building-data ingestion: upload raw parquet to MinIO and convert to
GeoPackage / Shapefile. Orchestrated by :func:`ingest_all_by_version` as a
Celery chain of chords (upload phase -> conversion phase -> notify).

Triggered via ``manage.py ingest_buildings`` (see management/commands).
"""

import logging
import tempfile
from pathlib import Path

from celery import chain, chord, group

from config import celery_app

from . import storage
from .converters import GeoPackageConverter, ShapefileConverter

SPATIAL_FORMATS = {
    "gpkg": (GeoPackageConverter(), ".gpkg"),
    "shp": (ShapefileConverter(), ".zip"),
}


# --- PHASE 1: PARQUET UPLOADS ---
@celery_app.task(soft_time_limit=600, queue="io_tasks")
def upload_parquet_task(version_tag: str, file_path: str, reupload: bool = False):
    """Upload a single raw parquet file to MinIO."""
    source = Path(file_path)
    nuts_id = source.stem
    storage.upload_if_missing(
        source,
        storage.parquet_key(version_tag, nuts_id, source.name),
        reupload=reupload,
    )
    return f"Uploaded {nuts_id}"


# --- PHASE 2: CONVERSIONS ---
@celery_app.task(soft_time_limit=3000, acks_late=True, queue="heavy_tasks")
def convert_spatial_task(version_tag: str, file_path: str, reupload: bool = False):
    """Convert a parquet to GeoPackage + Shapefile and upload. Isolated on the
    single-concurrency ``heavy_tasks`` worker for OOM protection."""
    source = Path(file_path)
    nuts_id = source.stem

    gdf = None
    for fmt_name, (converter, ext) in SPATIAL_FORMATS.items():
        object_key = storage.spatial_key(version_tag, fmt_name, nuts_id, ext)
        if not reupload and storage.object_exists(object_key):
            logging.info("Skipping existing %s for %s", fmt_name, nuts_id)
            continue

        try:
            if gdf is None:
                # Local import to prevent memory bloat on non-conversion workers.
                import geopandas as gpd

                logging.info("Loading %s for conversion...", nuts_id)
                gdf = gpd.read_parquet(source)

            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = Path(tmp_dir) / f"{nuts_id}{ext}"
                converter.convert(gdf, output_path, nuts_id)
                # Shapefile output is zipped to a sibling .zip.
                final_path = (
                    output_path
                    if output_path.exists()
                    else output_path.with_suffix(".zip")
                )
                storage.upload(object_key, final_path)
        except Exception as e:
            logging.error("Conversion failed for %s to %s: %s", nuts_id, fmt_name, e)

    return f"Converted {nuts_id}"


# --- ORCHESTRATION ---
@celery_app.task
def ingest_all_by_version(
    version_tag: str = "v0.2",
    reupload: bool = False,
    run_upload: bool = True,
    run_conversion: bool = True,
):
    """Chain the upload and conversion phases for every parquet under
    ``data/{version_tag}/buildings/``."""
    base_path = storage.local_source_dir(version_tag, "buildings")
    parquet_files = [str(p) for p in base_path.rglob("*.parquet")]
    if not parquet_files:
        return "No files found."

    pipeline = []
    if run_upload:
        upload_tasks = group(
            upload_parquet_task.s(version_tag, f, reupload) for f in parquet_files
        )
        # .si() prevents passing the group's results into the next chain link.
        pipeline.append(chord(upload_tasks, notify_phase_complete.si(None, "Upload")))
    if run_conversion:
        conversion_tasks = group(
            convert_spatial_task.s(version_tag, f, reupload) for f in parquet_files
        )
        pipeline.append(
            chord(conversion_tasks, notify_phase_complete.si(None, "Conversion"))
        )
    pipeline.append(notify_all_complete.si(None, version_tag))

    chain(*pipeline).apply_async(link_error=on_pipeline_failure.s())
    logging.info("Data ingestion pipeline sequenced for %s", version_tag)
    return f"Ingestion sequenced for {version_tag} ({len(parquet_files)} files)"


@celery_app.task
def notify_phase_complete(results, phase_name: str):
    count = len(results) if results else "unknown"
    logging.info(
        "--- PHASE SUCCESS: %s phase finished with %s items ---", phase_name, count
    )
    return f"{phase_name} complete"


@celery_app.task
def notify_all_complete(results, version_tag: str):
    logging.info("Full data ingestion pipeline completed for %s.", version_tag)


@celery_app.task
def on_pipeline_failure(request, exc, traceback):
    logging.error("Data ingestion pipeline failed: %s", exc)
