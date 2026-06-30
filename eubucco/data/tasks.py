"""Celery task registry for the ``data`` app.

The actual logic lives in focused modules — :mod:`eubucco.data.ingest`,
:mod:`eubucco.data.tiling`, :mod:`eubucco.data.coverage`. This module re-exports
their Celery tasks so ``celery_app.autodiscover_tasks()`` (which imports each
app's ``tasks`` module) registers them. Import the pipelines directly from their
modules in management commands; import tasks from here or from their module.
"""

from .coverage import generate_coverage_tiles_task
from .ingest import (
    convert_spatial_task,
    ingest_all_by_version,
    notify_all_complete,
    notify_phase_complete,
    on_pipeline_failure,
    upload_parquet_task,
)
from .tiling import tile_join_and_upload, tile_region_task

__all__ = [
    "upload_parquet_task",
    "convert_spatial_task",
    "ingest_all_by_version",
    "notify_phase_complete",
    "notify_all_complete",
    "on_pipeline_failure",
    "tile_region_task",
    "tile_join_and_upload",
    "generate_coverage_tiles_task",
]
