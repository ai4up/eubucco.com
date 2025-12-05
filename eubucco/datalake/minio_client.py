import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


@dataclass
class MinioSettings:
    endpoint: str = os.environ.get("MINIO_ENDPOINT", "http://127.0.0.1:9000")
    public_endpoint: str = os.environ.get("MINIO_PUBLIC_ENDPOINT") or endpoint
    bucket: str = os.environ.get("MINIO_BUCKET", "eubucco")
    access_key: str = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key: str = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    secure: bool = _as_bool(os.environ.get("MINIO_USE_SSL"), default=False)
    region: str = os.environ.get("MINIO_REGION", "eu")


def settings_from_django() -> MinioSettings:
    try:
        from django.conf import settings as django_settings

        return MinioSettings(
            endpoint=getattr(django_settings, "MINIO_ENDPOINT", None)
            or MinioSettings.endpoint,
            public_endpoint=getattr(django_settings, "MINIO_PUBLIC_ENDPOINT", None)
            or getattr(django_settings, "MINIO_ENDPOINT", None)
            or MinioSettings.endpoint,
            bucket=getattr(django_settings, "MINIO_BUCKET", None) or MinioSettings.bucket,
            access_key=getattr(django_settings, "MINIO_ACCESS_KEY", None)
            or MinioSettings.access_key,
            secret_key=getattr(django_settings, "MINIO_SECRET_KEY", None)
            or MinioSettings.secret_key,
            secure=getattr(django_settings, "MINIO_USE_SSL", None)
            if hasattr(django_settings, "MINIO_USE_SSL")
            else MinioSettings.secure,
            region=getattr(django_settings, "MINIO_REGION", None)
            or MinioSettings.region,
        )
    except Exception:
        return MinioSettings()


def _normalize_endpoint(endpoint: str, secure: bool) -> Tuple[str, bool]:
    """
    MinIO python client expects a host:port without the schema. Allow both formats.
    """
    if "://" not in endpoint:
        return endpoint, secure
    parsed = urlparse(endpoint)
    return parsed.netloc or parsed.path, secure if secure is not None else parsed.scheme == "https"


def build_client(settings: Optional[MinioSettings] = None) -> Tuple[Minio, MinioSettings]:
    settings = settings or settings_from_django()
    endpoint, secure = _normalize_endpoint(settings.endpoint, settings.secure)
    client = Minio(
        endpoint,
        access_key=settings.access_key,
        secret_key=settings.secret_key,
        secure=secure,
        region=settings.region,
    )
    return client, settings


def build_presign_client(settings: MinioSettings) -> Minio:
    """
    Use the public endpoint (if set) for presigning so the host in the signature
    matches the URL the browser will hit.
    """
    endpoint, secure = _normalize_endpoint(
        settings.public_endpoint or settings.endpoint, settings.secure
    )
    return Minio(
        endpoint,
        access_key=settings.access_key,
        secret_key=settings.secret_key,
        secure=secure,
        region=settings.region,
    )


def ensure_bucket(client: Minio, settings: MinioSettings) -> None:
    if client.bucket_exists(settings.bucket):
        return
    try:
        client.make_bucket(settings.bucket, location=settings.region)
    except S3Error as exc:  # pragma: no cover - defensive guardrail
        if exc.code != "BucketAlreadyOwnedByYou":
            raise


def upload_file(client: Minio, settings: MinioSettings, object_name: str, file_path: str) -> None:
    client.fput_object(settings.bucket, object_name, file_path)


def presign_get_url(
    client: Minio,
    settings: MinioSettings,
    object_name: str,
    expiry: timedelta = timedelta(hours=1),
) -> str:
    public_client = build_presign_client(settings)
    return public_client.presigned_get_object(settings.bucket, object_name, expires=expiry)


def list_objects(client: Minio, settings: MinioSettings, prefix: str = ""):
    return client.list_objects(settings.bucket, prefix=prefix, recursive=True)


def extract_partitions_from_key(object_name: str) -> dict:
    """
    Parse a parquet object key to figure out partition values encoded as `key=value`.
    """
    parts = {}
    for token in object_name.split("/"):
        if "=" in token:
            key, value = token.split("=", 1)
            parts[key] = value
    return parts


def public_s3_uri(settings: MinioSettings, object_name: str) -> str:
    return f"s3://{settings.bucket}/{object_name}"
