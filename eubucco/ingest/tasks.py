import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from collections.abc import Iterable

import geopandas as gpd
import pandas as pd

from config import celery_app
from eubucco.datalake.constants import DATASET_PREFIX
from eubucco.datalake.minio_client import (
    MinioSettings,
    build_client,
    ensure_bucket,
    public_s3_uri,
    upload_file,
)
from eubucco.ingest.util import (
    match_building_type,
    match_gadm_info,
    match_type_source,
    sanitize_building_age,
)
from eubucco.utils import version_enum

CSV_PATH = Path("csvs/buildings")
ADMIN_CODE_MATCHES_NO_VERSION = Path("csvs/util/admin-codes-matches_no_version.csv")
PARQUET_CACHE = Path(".cache/parquet-buildings")
NUTS_LOOKUP_PATH = Path("csvs/util/nuts_lookup.csv")

PARQUET_CACHE.mkdir(parents=True, exist_ok=True)


def _load_admin_code_matches() -> pd.DataFrame:
    if not ADMIN_CODE_MATCHES_NO_VERSION.exists():
        raise FileNotFoundError(
            f"Missing admin code matches at {ADMIN_CODE_MATCHES_NO_VERSION}"
        )
    return pd.read_csv(ADMIN_CODE_MATCHES_NO_VERSION)


def _load_nuts_lookup() -> Optional[pd.DataFrame]:
    if NUTS_LOOKUP_PATH.exists():
        lookup = pd.read_csv(NUTS_LOOKUP_PATH)
        expected = {"country", "region", "city", "nuts_id", "nuts_level"}
        missing_columns = expected.difference(set(lookup.columns))
        if missing_columns:
            raise ValueError(
                f"NUTS lookup {NUTS_LOOKUP_PATH} is missing columns: {missing_columns}"
            )
        return lookup
    logging.warning(
        "NUTS lookup file not found. Falling back to region names for partitioning."
    )
    return None


def _extract_gpkg(zipped_gpkg_path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="eubucco-gpkg-"))
    with zipfile.ZipFile(zipped_gpkg_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)
    for nested in temp_dir.rglob("*.zip"):
        if nested.name.startswith("."):
            continue
        with zipfile.ZipFile(nested, "r") as zip_ref:
            zip_ref.extractall(temp_dir)
    return temp_dir


def _iter_chunks(gpkg_path: Path, chunk_size: int) -> Iterable[gpd.GeoDataFrame]:
    for start in range(0, 10**10, chunk_size):
        gdf = gpd.read_file(gpkg_path, rows=slice(start, start + chunk_size))
        if len(gdf) == 0:
            break
        yield gdf


def _derive_nuts(df: pd.DataFrame, nuts_lookup: Optional[pd.DataFrame]) -> pd.DataFrame:
    if nuts_lookup is not None:
        merged = df.merge(
            nuts_lookup,
            on=["country", "region", "city"],
            how="left",
            suffixes=("", "_lkp"),
        )
        df["nuts_id"] = merged["nuts_id"]
        df["nuts_level"] = merged["nuts_level"]
    else:
        df["nuts_id"] = df["region"]
        df["nuts_level"] = "unspecified"

    df["nuts_id"] = df["nuts_id"].fillna(df["region"])
    df["nuts_level"] = df["nuts_level"].fillna("unspecified")
    df["nuts_id"] = df["nuts_id"].astype(str).str.replace(" ", "_")
    return df


def _prepare_chunk(
    df_raw: gpd.GeoDataFrame,
    df_code_matches: pd.DataFrame,
    version_value: int,
    nuts_lookup: Optional[pd.DataFrame],
) -> pd.DataFrame:
    df = match_gadm_info(df_raw, df_code_matches)
    df.rename(columns={"id_x": "id"}, inplace=True)
    df = _derive_nuts(df, nuts_lookup)
    df["geometry_wkb"] = df["geometry"].to_wkb()
    df["version"] = version_value

    df["type"] = [match_building_type(val).value for val in df["type"]]
    df["age"] = [sanitize_building_age(val) for val in df["age"]]
    df["type_source"] = [match_type_source(val) for val in df["type_source"]]

    df = df.drop(columns=["geometry", "id_temp"], errors="ignore")
    ordered_columns = [
        "id",
        "id_source",
        "country",
        "region",
        "city",
        "nuts_id",
        "nuts_level",
        "height",
        "age",
        "type",
        "type_source",
        "geometry_wkb",
        "version",
    ]
    return df[ordered_columns]


def _write_partition(
    df: pd.DataFrame, dataset_root: Path, counters: dict[str, int]
) -> None:
    grouped = df.groupby("nuts_id")
    for nuts_id, df_partition in grouped:
        dest_dir = dataset_root / f"nuts_id={nuts_id}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_index = counters.get(nuts_id, 0)
        dest_path = dest_dir / f"part-{file_index}.parquet"
        df_partition.to_parquet(dest_path, index=False)
        counters[nuts_id] = file_index + 1


def _upload_dataset(
    dataset_root: Path, dataset_prefix: str, settings: MinioSettings
) -> None:
    client, settings = build_client(settings=settings)
    ensure_bucket(client, settings)
    for parquet_file in dataset_root.rglob("*.parquet"):
        relative_key = parquet_file.relative_to(dataset_root).as_posix()
        object_key = f"{dataset_prefix}/{relative_key}"
        logging.info(
            "Uploading %s to %s", parquet_file, public_s3_uri(settings, object_key)
        )
        upload_file(client, settings, object_key, str(parquet_file))


def _build_chunk_iterator(
    gpkg_path: Path,
    df_code_matches: pd.DataFrame,
    version_value: int,
    nuts_lookup: Optional[pd.DataFrame],
    chunk_size: int,
) -> Iterable[pd.DataFrame]:
    for chunk in _iter_chunks(gpkg_path, chunk_size=chunk_size):
        yield _prepare_chunk(
            df_raw=chunk,
            df_code_matches=df_code_matches,
            version_value=version_value,
            nuts_lookup=nuts_lookup,
        )


@celery_app.task(
    soft_time_limit=60 * 60 * 24 * 3,
    hard_time_limit=(60 * 60 * 24 * 3) + 10,
)
def publish_parquet_partitions(
    version_override: Optional[str] = None, chunk_size: int = 50_000
):
    """
    Convert source GPKG building data into Parquet, partitioned by NUTS, and upload to MinIO.
    """
    df_code_matches = _load_admin_code_matches()
    nuts_lookup = _load_nuts_lookup()
    settings = MinioSettings()

    for zipped_gpkg_path in CSV_PATH.rglob("*.gpkg.zip"):
        version_tag = version_override or str(zipped_gpkg_path.name).split("-")[0]
        try:
            resolved_version = version_enum.version_from_path(
                f"{version_tag}-placeholder"
            )
            version_value = int(resolved_version)
        except Exception:
            logging.warning("Unknown version tag %s, persisting as-is", version_tag)
            version_value = version_tag
        dataset_prefix = f"{DATASET_PREFIX}/{version_tag}"
        parquet_root = PARQUET_CACHE / version_tag
        shutil.rmtree(parquet_root, ignore_errors=True)
        partition_counters: dict[str, int] = {}

        logging.info(
            "Building parquet dataset for %s (version %s)",
            zipped_gpkg_path,
            version_tag,
        )
        extraction_dir = _extract_gpkg(zipped_gpkg_path)
        try:
            gpkg_files = list(Path(extraction_dir).rglob("*.gpkg"))
            if not gpkg_files:
                logging.warning("No gpkg files found in %s", extraction_dir)
                continue
            for gpkg_path in gpkg_files:
                for df in _build_chunk_iterator(
                    gpkg_path=gpkg_path,
                    df_code_matches=df_code_matches,
                    version_value=version_value,
                    nuts_lookup=nuts_lookup,
                    chunk_size=chunk_size,
                ):
                    _write_partition(df, parquet_root, partition_counters)
            _upload_dataset(parquet_root, dataset_prefix, settings=settings)
        finally:
            shutil.rmtree(extraction_dir, ignore_errors=True)
            shutil.rmtree(parquet_root, ignore_errors=True)


@celery_app.task(soft_time_limit=60 * 5, hard_time_limit=(60 * 5) + 5)
def republish_latest_dataset():
    publish_parquet_partitions.delay()
