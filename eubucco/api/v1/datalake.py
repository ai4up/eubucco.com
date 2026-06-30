import os
import tempfile
import zipfile
from collections.abc import Iterable
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from eubucco.data.constants import DATASET_PREFIX
from eubucco.data.minio_client import (
    MinioSettings,
    build_client,
    ensure_bucket,
    extract_partitions_from_key,
    list_objects,
    public_s3_uri,
)


def _download_url(settings: MinioSettings, object_name: str) -> str:
    """Direct, browser-usable public URL (the data bucket is public-read)."""
    return f"{settings.public_endpoint.rstrip('/')}/{settings.bucket}/{object_name}"


router = APIRouter()


class DatalakeObject(BaseModel):
    key: str
    size_bytes: int
    s3_uri: str
    download_url: str


class NutsPartitionResponse(BaseModel):
    nuts_id: str
    version: str
    object_count: int
    total_size_bytes: int
    files: list[DatalakeObject]


class FileListResponse(BaseModel):
    version: str
    path: str
    object_count: int
    total_size_bytes: int
    files: list[DatalakeObject]


class DownloadFormat(str, Enum):
    parquet = "parquet"
    gpkg = "gpkg"
    shp = "shp"


PartitionKey = tuple[str, str]  # (version, nuts_id)


def _group_by_partition(
    objects: Iterable, dataset_prefix: str
) -> dict[PartitionKey, list]:
    """
    Group MinIO objects into (version, nuts_id) partitions.

    Expected key layout:
      {version}/{DATASET_PREFIX}/.../nuts_id={NUTS_CODE}/...
    """
    grouped: dict[PartitionKey, list] = {}
    for obj in objects:
        parts = obj.object_name.split("/")
        if len(parts) < 2 or parts[1] != dataset_prefix:
            continue

        version = parts[0]
        partitions = extract_partitions_from_key(obj.object_name)
        nuts_id = partitions.get("nuts_id", "unspecified")

        grouped.setdefault((version, nuts_id), []).append(obj)
    return grouped


def _to_partition_response(
    client, settings: MinioSettings, partition_key: PartitionKey, objects: list
) -> NutsPartitionResponse:
    version, nuts_id = partition_key
    files: list[DatalakeObject] = [
        DatalakeObject(
            key=obj.object_name,
            size_bytes=obj.size,
            s3_uri=public_s3_uri(settings, obj.object_name),
            download_url=_download_url(settings, obj.object_name),
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


@router.get("/nuts/{version}", response_model=list[NutsPartitionResponse])
async def list_nuts_partitions(
    version: str, format: DownloadFormat = Query(default=None)
):
    """
    List all NUTS partitions for a specific version and, optionally, a specific format.
    """
    client, settings = build_client()
    ensure_bucket(client, settings)

    prefix = f"{version}/{DATASET_PREFIX}/"
    objects = list(list_objects(client, settings, prefix=prefix))
    grouped = _group_by_partition(objects, dataset_prefix=DATASET_PREFIX)

    if format:
        for key in grouped:
            grouped[key] = [
                obj for obj in grouped[key] if f"/{format.value}/" in obj.object_name
            ]

    responses = [
        _to_partition_response(client, settings, partition_key=key, objects=value)
        for key, value in grouped.items()
    ]

    return sorted(responses, key=lambda entry: (entry.version, entry.nuts_id))


@router.get("/nuts/{version}/{nuts_id}", response_model=NutsPartitionResponse)
async def get_partition(version: str, nuts_id: str):
    """
    Return all objects belonging to a specific (version, nuts_id) partition.
    """
    client, settings = build_client()
    ensure_bucket(client, settings)

    prefix = f"{version}/{DATASET_PREFIX}/"
    objects = list(list_objects(client, settings, prefix=prefix))
    grouped = _group_by_partition(objects, dataset_prefix=DATASET_PREFIX)

    key: PartitionKey = (version, nuts_id)
    if key not in grouped:
        raise HTTPException(
            status_code=404, detail="Partition not found in object storage"
        )

    return _to_partition_response(
        client, settings, partition_key=key, objects=grouped[key]
    )


@router.get("/nuts/{version}/{nuts_prefix}/bundle", response_class=FileResponse)
async def download_bundle(
    version: str,
    nuts_prefix: str,
    format: DownloadFormat = Query(default=DownloadFormat.parquet),
):
    client, settings = build_client()
    ensure_bucket(client, settings)

    prefix = f"{version}/{DATASET_PREFIX}/"
    objects = list(list_objects(client, settings, prefix=prefix))
    grouped = _group_by_partition(objects, dataset_prefix=DATASET_PREFIX)

    matching_objects = []
    for (obj_version, nuts_id), objs in grouped.items():
        if obj_version == version and nuts_id.startswith(nuts_prefix):
            for obj in objs:
                if f"/{format.value}/" in obj.object_name:
                    matching_objects.append(obj)

    if not matching_objects:
        raise HTTPException(
            status_code=404,
            detail=f"No {format.value} files found for NUTS prefix {nuts_prefix}",
        )

    zip_path = _build_zip_for_objects(client, settings, matching_objects)
    filename = f"eubucco_{version}_{nuts_prefix}_{format.value}.zip"

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(os.unlink, zip_path),
    )


@router.get("/files/{version}", response_model=FileListResponse)
async def list_files_for_version(
    version: str,
    path: str = Query(
        default="", description="Optional subdirectory inside the dataset folder"
    ),
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

    prefix = f"{version}/{DATASET_PREFIX}/"
    if path:
        cleaned = path.lstrip("/")
        prefix = prefix + cleaned
        if not prefix.endswith("/"):
            prefix += "/"

    objects = list(list_objects(client, settings, prefix=prefix))

    files = [
        DatalakeObject(
            key=obj.object_name,
            size_bytes=obj.size,
            s3_uri=public_s3_uri(settings, obj.object_name),
            download_url=_download_url(settings, obj.object_name),
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
