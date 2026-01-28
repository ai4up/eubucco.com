import tempfile
import zipfile
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from eubucco.datalake.constants import DATASET_PREFIX
from eubucco.datalake.minio_client import (
    MinioSettings,
    build_client,
    ensure_bucket,
    extract_partitions_from_key,
    list_objects,
    presign_get_url,
    public_s3_uri,
)

router = APIRouter()


class DatalakeObject(BaseModel):
    key: str
    size_bytes: int
    s3_uri: str
    presigned_url: str


class NutsPartitionResponse(BaseModel):
    nuts_id: str
    version: str
    object_count: int
    total_size_bytes: int
    files: List[DatalakeObject]


class FileListResponse(BaseModel):
    version: str
    path: str
    object_count: int
    total_size_bytes: int
    files: List[DatalakeObject]


class DownloadFormat(str, Enum):
    parquet = "parquet"
    gpkg = "gpkg"
    shp = "shp"


PartitionKey = Tuple[str, str]  # (version, nuts_id)


def _group_by_partition(objects: Iterable, dataset_prefix: str) -> Dict[PartitionKey, List]:
    """
    Group MinIO objects into (version, nuts_id) partitions.

    Expected key layout:
      {DATASET_PREFIX}/{version}/.../nuts_id={NUTS_CODE}/...
    """
    grouped: Dict[PartitionKey, List] = {}
    for obj in objects:
        parts = obj.object_name.split("/")
        if len(parts) < 2 or parts[0] != dataset_prefix:
            # Not part of the dataset prefix -> ignore
            continue

        version = parts[1]
        partitions = extract_partitions_from_key(obj.object_name)
        nuts_id = partitions.get("nuts_id", "unspecified")

        grouped.setdefault((version, nuts_id), []).append(obj)
    return grouped


def _to_partition_response(
    client, settings: MinioSettings, partition_key: PartitionKey, objects: List
) -> NutsPartitionResponse:
    version, nuts_id = partition_key
    files: List[DatalakeObject] = [
        DatalakeObject(
            key=obj.object_name,
            size_bytes=obj.size,
            s3_uri=public_s3_uri(settings, obj.object_name),
            presigned_url=presign_get_url(client, settings, obj.object_name),
        )
        for obj in objects
    ]
    return NutsPartitionResponse(
        nuts_id=nuts_id,
        version=version,
        object_count=len(files),
        total_size_bytes=sum(file.size_bytes for file in files),
        files=files,
    )


def _build_zip_for_objects(client, settings: MinioSettings, objects: Iterable) -> Path:
    """
    Stream a list of objects from MinIO into a temporary ZIP file.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)

    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
        for obj in objects:
            resp = client.get_object(settings.bucket, obj.object_name)
            try:
                filename = Path(obj.object_name).name
                zf.writestr(filename, resp.read())
            finally:
                resp.close()
                resp.release_conn()

    tmp.close()
    return tmp_path


@router.get("/nuts", response_model=List[NutsPartitionResponse])
async def list_nuts_partitions(version: str = Query(default=None), format: DownloadFormat = Query(default=None)):
    """
    List all NUTS partitions. If `version` or `format` are provided, only partitions for that
    dataset version and format are returned.
    """
    client, settings = build_client()
    ensure_bucket(client, settings)

    # List all dataset objects (optionally within a version prefix)
    prefix = f"{DATASET_PREFIX}/"
    if version:
        prefix = f"{DATASET_PREFIX}/{version}/"

    objects = list(list_objects(client, settings, prefix=prefix))
    grouped = _group_by_partition(objects, dataset_prefix=DATASET_PREFIX)

    # Optionally filter partitions by version (extra guard)
    if version:
        grouped = {k: v for k, v in grouped.items() if k[0] == version}

    # Optionally filter files within each partition by format
    if format:
        for key in grouped:
            grouped[key] = [
                obj for obj in grouped[key] if f"/{format.value}/" in obj.object_name
            ]

    responses = [
        _to_partition_response(client, settings, partition_key=key, objects=value)
        for key, value in grouped.items()
    ]
    # Sort for stable / predictable output
    return sorted(responses, key=lambda entry: (entry.version, entry.nuts_id))


@router.get("/nuts/{version}/{nuts_id}", response_model=NutsPartitionResponse)
async def get_partition(version: str, nuts_id: str):
    """
    Return all objects belonging to a specific (version, nuts_id) partition.
    """
    client, settings = build_client()
    ensure_bucket(client, settings)

    prefix = f"{DATASET_PREFIX}/{version}/"
    objects = list(list_objects(client, settings, prefix=prefix))
    grouped = _group_by_partition(objects, dataset_prefix=DATASET_PREFIX)

    key: PartitionKey = (version, nuts_id)
    if key not in grouped:
        raise HTTPException(status_code=404, detail="Partition not found in object storage")

    return _to_partition_response(client, settings, partition_key=key, objects=grouped[key])


@router.get("/nuts/{version}/{nuts_prefix}/bundle", response_class=FileResponse)
async def download_bundle(
    version: str,
    nuts_prefix: str,
    format: DownloadFormat = Query(default=DownloadFormat.parquet)
):
    client, settings = build_client()
    ensure_bucket(client, settings)

    prefix = f"{DATASET_PREFIX}/{version}/"
    objects = list(list_objects(client, settings, prefix=prefix))
    grouped = _group_by_partition(objects, dataset_prefix=DATASET_PREFIX)

    matching_objects = []
    for (obj_version, nuts_id), objs in grouped.items():
        if obj_version == version and nuts_id.startswith(nuts_prefix):
            for obj in objs:
                key = obj.object_name
                if f"/{format.value}/" in key:
                    matching_objects.append(obj)

    if not matching_objects:
        raise HTTPException(
            status_code=404,
            detail=f"No {format.value} files found for NUTS prefix {nuts_prefix}"
        )

    zip_path = _build_zip_for_objects(client, settings, matching_objects)
    filename = f"eubucco_{version}_{nuts_prefix}_{format.value}.zip"

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=None
    )


def _build_zip_for_objects(client, settings: MinioSettings, objects: Iterable) -> Path:
    """
    Stream objects from MinIO into a temporary ZIP bundle.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)

    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for obj in objects:
            resp = client.get_object(settings.bucket, obj.object_name)
            try:
                filename = Path(obj.object_name).name
                zf.writestr(filename, resp.read())
            finally:
                resp.close()
                resp.release_conn()

    tmp.close()
    return tmp_path


@router.get("/files/{version}", response_model=FileListResponse)
async def list_files_for_version(
    version: str,
    path: str = Query(default="", description="Optional subdirectory or file prefix inside the version folder"),
):
    """
    List all files stored under a dataset version (and optional sub-path).

    Examples:
        GET /files/v0.1
        GET /files/v0.1?path=metadata
        GET /files/v0.2?path=nuts_id=DE1
    """
    client, settings = build_client()
    ensure_bucket(client, settings)

    # Prefix like: buildings/v0.1/ or buildings/v0.1/LU
    prefix = f"{DATASET_PREFIX}/{version}/"
    if path:
        # Normalize input such that "LU" → buildings/v0.1/LU
        cleaned = path.lstrip("/")
        prefix = prefix + cleaned

        # Ensure MinIO lists recursively
        if not prefix.endswith("/"):
            prefix += "/"

    objects = list(list_objects(client, settings, prefix=prefix))

    files = [
        DatalakeObject(
            key=obj.object_name,
            size_bytes=obj.size,
            s3_uri=public_s3_uri(settings, obj.object_name),
            presigned_url=presign_get_url(client, settings, obj.object_name),
        )
        for obj in objects
    ]

    return FileListResponse(
        version=version,
        path=path or "",
        object_count=len(files),
        total_size_bytes=sum(f.size_bytes for f in files),
        files=files,
    )
