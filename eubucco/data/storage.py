"""Shared MinIO storage helpers: object-key builders, public URL construction,
and idempotent upload / atomic-write utilities.

This is the single place that knows the bucket layout. Views build public
download / PMTiles URLs through here; the ingestion, tiling and coverage
pipelines build keys and upload through here. See ``constants.py`` for the
prefix definitions and ``minio_client.py`` for the low-level client.
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from .constants import (
    ADDITIONAL_METADATA_NAME,
    ADDITIONAL_PREFIX,
    DATASET_PREFIX,
    EXAMPLES_PREFIX,
)
from .minio_client import build_client
from .minio_client import ensure_bucket as _ensure_bucket
from .minio_client import file_exists, list_objects, settings_from_django, upload_file

logger = logging.getLogger(__name__)


def default_version() -> str:
    """The dataset version the public site defaults to (BUILDINGS_VERSION)."""
    return os.getenv("BUILDINGS_VERSION", "v0.2")


# --------------------------------------------------------------------------- #
# Object-key builders ({version}/{prefix}/...)
# --------------------------------------------------------------------------- #
def parquet_key(version: str, nuts_id: str, filename: str) -> str:
    return f"{version}/{DATASET_PREFIX}/parquet/nuts_id={nuts_id}/{filename}"


def spatial_key(version: str, fmt: str, nuts_id: str, ext: str) -> str:
    """Converted GeoPackage / Shapefile key, e.g. .../gpkg/nuts_id=DE1/DE1.gpkg."""
    return f"{version}/{DATASET_PREFIX}/{fmt}/nuts_id={nuts_id}/{nuts_id}{ext}"


def legacy_buildings_key(version: str, fmt: str, filename: str) -> str:
    """Country-level (non-NUTS-partitioned) buildings, e.g. v0.1/buildings/gpkg/AUT.gpkg.zip."""
    return f"{version}/{DATASET_PREFIX}/{fmt}/{filename}"


def building_tiles_key(version: str) -> str:
    return f"{version}/{DATASET_PREFIX}/tiles/buildings.pmtiles"


def coverage_key(version: str) -> str:
    return f"{version}/coverage/coverage-stats.pmtiles"


def coverage_summary_key(version: str) -> str:
    return f"{version}/coverage/coverage-summary.json"


def examples_prefix(version: str) -> str:
    return f"{version}/{EXAMPLES_PREFIX}/"


def examples_key(version: str, filename: str) -> str:
    return f"{version}/{EXAMPLES_PREFIX}/{filename}"


def additional_prefix(version: str) -> str:
    return f"{version}/{ADDITIONAL_PREFIX}/"


def additional_key(version: str, filename: str) -> str:
    return f"{version}/{ADDITIONAL_PREFIX}/{filename}"


def additional_metadata_key(version: str) -> str:
    return f"{version}/{ADDITIONAL_PREFIX}/{ADDITIONAL_METADATA_NAME}"


# --------------------------------------------------------------------------- #
# Public URLs (anonymous read; the data bucket is public-read + list)
# --------------------------------------------------------------------------- #
def public_object_url(object_key: str) -> str:
    """Direct, browser-usable URL for a public object: {public_endpoint}/{bucket}/{key}."""
    settings = settings_from_django()
    endpoint = settings.public_endpoint.rstrip("/")
    return f"{endpoint}/{settings.bucket}/{object_key}"


def pmtiles_url(kind: str, version: Optional[str] = None) -> str:
    """Public URL for a PMTiles archive. ``kind`` is "buildings" or "coverage"."""
    version = version or default_version()
    key = {
        "buildings": building_tiles_key(version),
        "coverage": coverage_key(version),
    }[kind]
    return public_object_url(key)


def coverage_summary_url(version: Optional[str] = None) -> str:
    version = version or default_version()
    return public_object_url(coverage_summary_key(version))


# --------------------------------------------------------------------------- #
# Upload / list helpers
# --------------------------------------------------------------------------- #
def ensure_bucket() -> None:
    client, settings = build_client()
    _ensure_bucket(client, settings)


def upload(object_key: str, local_path, content_type: Optional[str] = None) -> None:
    client, settings = build_client()
    upload_file(
        client, settings, object_key, str(local_path), content_type=content_type
    )


def upload_if_missing(
    local_path,
    object_key: str,
    reupload: bool = False,
    content_type: Optional[str] = None,
) -> bool:
    """Upload ``local_path`` to ``object_key`` unless it already exists.

    Returns True if an upload happened, False if skipped. Makes the ingestion
    and extras-upload jobs idempotent / resumable.
    """
    client, settings = build_client()
    if not reupload and file_exists(client, settings, object_key):
        logger.info("Skipping existing object: %s", object_key)
        return False
    logger.info("Uploading %s -> %s", local_path, object_key)
    upload_file(
        client, settings, object_key, str(local_path), content_type=content_type
    )
    return True


def object_exists(object_key: str) -> bool:
    client, settings = build_client()
    return file_exists(client, settings, object_key)


def read_text(object_key: str) -> Optional[str]:
    """Return a small text object's contents, or None if it doesn't exist."""
    from minio.error import S3Error

    client, settings = build_client()
    try:
        resp = client.get_object(settings.bucket, object_key)
    except S3Error:
        return None
    try:
        return resp.read().decode("utf-8")
    finally:
        resp.close()
        resp.release_conn()


def list_prefix(prefix: str):
    """Yield objects under ``prefix`` (recursive)."""
    client, settings = build_client()
    return list_objects(client, settings, prefix=prefix)


# --------------------------------------------------------------------------- #
# Atomic local writes (used by the tile pipelines)
# --------------------------------------------------------------------------- #
def atomic_write(path, write_fn: Callable[[Path], None]) -> Path:
    """Write to a sibling ``*.tmp.<ext>`` file then atomically rename into place.

    ``write_fn`` receives the temp path and must produce the file there. The temp
    name keeps the real extension so format-sniffing tools (GDAL/tippecanoe) work.
    An interrupted run never leaves a half-written file at the final path.
    """
    path = Path(path)
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    tmp.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_fn(tmp)
    os.replace(tmp, path)
    return path
