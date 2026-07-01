"""Building vector-tile pipeline: per-region parquet -> FlatGeobuf (DuckDB) ->
PMTiles (tippecanoe), merged with tile-join into one ``buildings.pmtiles`` and
uploaded to MinIO.

Runs either in-process (``executor="local"`` ProcessPoolExecutor — used by the
one-off ``tile-generator`` container) or on the Celery ``tiling`` queue. Both
paths reproject EPSG:3035 -> EPSG:4326 and are resumable (finished region
artifacts are reused). Triggered via ``manage.py generate_building_tiles``.
"""

import logging
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from celery import chord, group

from config import celery_app

from . import storage
from .constants import DATASET_PREFIX
from .minio_client import extract_partitions_from_key

# Building geometries are stored in EPSG:3035 (ETRS89-LAEA Europe); tiles need WGS84.
_SOURCE_CRS = "EPSG:3035"

_TILE_ATTR_SELECT = (
    "id, type, subtype,"
    " CAST(height AS DOUBLE) AS height,"
    " CAST(floors AS DOUBLE) AS floors,"
    " CAST(construction_year AS INTEGER) AS construction_year,"
    " subtype_raw, geometry_source, type_source, subtype_source,"
    " height_source, floors_source, construction_year_source,"
    " CAST(type_confidence AS DOUBLE) AS type_confidence,"
    " CAST(subtype_confidence AS DOUBLE) AS subtype_confidence,"
    " CAST(height_confidence_lower AS DOUBLE) AS height_confidence_lower,"
    " CAST(height_confidence_upper AS DOUBLE) AS height_confidence_upper,"
    " CAST(floors_confidence_lower AS DOUBLE) AS floors_confidence_lower,"
    " CAST(floors_confidence_upper AS DOUBLE) AS floors_confidence_upper,"
    " CAST(construction_year_confidence_lower AS INTEGER) AS construction_year_confidence_lower,"
    " CAST(construction_year_confidence_upper AS INTEGER) AS construction_year_confidence_upper"
)

# Numeric attribute types passed to tippecanoe. FlatGeobuf is already typed, so
# these are mostly belt-and-suspenders, but they guarantee the explorer popup
# receives numbers (not strings) for every measured/confidence field.
_TIPPECANOE_ATTR_TYPES = [
    "--attribute-type=height:float",
    "--attribute-type=floors:float",
    "--attribute-type=construction_year:int",
    "--attribute-type=type_confidence:float",
    "--attribute-type=subtype_confidence:float",
    "--attribute-type=height_confidence_lower:float",
    "--attribute-type=height_confidence_upper:float",
    "--attribute-type=floors_confidence_lower:float",
    "--attribute-type=floors_confidence_upper:float",
    "--attribute-type=construction_year_confidence_lower:int",
    "--attribute-type=construction_year_confidence_upper:int",
]


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _tile_one_region(
    region_id: str,
    source: str,
    fgb_path: str,
    pmtiles_path: str,
    min_zoom: int,
    max_zoom: int,
    s3_cfg: dict = None,
    force: bool = False,
):
    """Tile a single NUTS region: parquet -> FlatGeobuf (DuckDB) -> PMTiles (tippecanoe).

    Self-contained and picklable so it can run inside a ProcessPoolExecutor *or*
    a Celery worker. Resumable: a finished region PMTiles is reused as-is; a
    finished FGB skips the DuckDB COPY. Both are written atomically.
    """
    import duckdb

    log = logging.getLogger(__name__)
    pmtiles_path = Path(pmtiles_path)
    fgb_path = Path(fgb_path)
    fgb_path.parent.mkdir(parents=True, exist_ok=True)

    if pmtiles_path.exists() and not force:
        log.info("Region %s already tiled, skipping", region_id)
        return str(pmtiles_path)

    # --- Stage 1: parquet -> FlatGeobuf (reuse if a complete FGB is present) ---
    if force or not fgb_path.exists():

        def _write_fgb(tmp: Path):
            con = duckdb.connect()
            con.execute("INSTALL spatial")
            con.execute("LOAD spatial")
            if s3_cfg:
                con.execute("INSTALL httpfs")
                con.execute("LOAD httpfs")
                con.execute(f"SET s3_endpoint='{_esc(s3_cfg['endpoint'])}'")
                con.execute(f"SET s3_access_key_id='{_esc(s3_cfg['access_key'])}'")
                con.execute(f"SET s3_secret_access_key='{_esc(s3_cfg['secret_key'])}'")
                con.execute("SET s3_url_style='path'")
                con.execute(f"SET s3_use_ssl={str(s3_cfg['secure']).lower()}")
                con.execute(f"SET s3_region='{_esc(s3_cfg['region'])}'")
            log.info("Region %s: DuckDB COPY parquet -> %s", region_id, fgb_path.name)
            con.execute(
                f"""
                COPY (
                    SELECT
                        ST_Transform(geometry, '{_SOURCE_CRS}', 'EPSG:4326', always_xy := true) AS geometry,
                        {_TILE_ATTR_SELECT}
                    FROM read_parquet('{_esc(source)}', hive_partitioning=true)
                ) TO '{tmp}' (FORMAT GDAL, DRIVER 'FlatGeobuf');
                """
            )
            con.close()

        storage.atomic_write(fgb_path, _write_fgb)
    else:
        log.info("Region %s: reusing existing FGB, skipping COPY", region_id)

    # --- Stage 2: FlatGeobuf -> PMTiles ---
    log.info("Region %s: tippecanoe -> %s", region_id, pmtiles_path.name)

    def _write_pmtiles(tmp: Path):
        cmd = [
            "tippecanoe",
            "-o",
            str(tmp),
            "-l",
            "buildings",
            "-Z",
            str(min_zoom),
            "-z",
            str(max_zoom),
            "--drop-densest-as-needed",
            # NB: NO --extend-zooms-if-still-dropping. On dense regions it pushes the
            # tileset past max_zoom, leaving a partially-populated top level so
            # buildings vanish past that zoom. A hard max_zoom overzooms cleanly.
            "--read-parallel",
            "--force",
            # NB: deliberately NO --generate-ids — independent per-region runs would
            # assign colliding feature ids that tile-join cannot reconcile. The
            # explorer keys off the `id` attribute, not the MVT feature id.
            *_TIPPECANOE_ATTR_TYPES,
            str(fgb_path),
        ]
        subprocess.run(cmd, check=True)

    storage.atomic_write(pmtiles_path, _write_pmtiles)
    fgb_path.unlink(missing_ok=True)  # FGB no longer needed once the region is done
    return str(pmtiles_path)


def _run_tile_join_and_upload(version: str, pmtiles_paths: list, out_path: str):
    """Merge per-region PMTiles with tile-join and upload to MinIO."""
    log = logging.getLogger(__name__)
    valid = [str(p) for p in pmtiles_paths if p and Path(p).exists()]
    if not valid:
        raise RuntimeError("No region PMTiles available to join.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("tile-join: merging %d region PMTiles -> %s", len(valid), out_path.name)
    subprocess.run(
        [
            "tile-join",
            "-f",
            "-pk",
            "-n",
            "EUBUCCO Buildings",
            "-N",
            f"EUBUCCO building stock characteristics {version}",
            "-A",
            "EUBUCCO",
            "-o",
            str(out_path),
            *valid,
        ],
        check=True,
    )

    size_mb = out_path.stat().st_size / 1024 / 1024
    object_key = storage.building_tiles_key(version)
    log.info("Uploading %.1f MB -> %s", size_mb, object_key)
    # A PMTiles archive is a binary container read via HTTP range requests (its
    # inner tiles are already gzipped) — serve it as octet-stream so proxies/CDNs
    # don't try to re-compress it.
    storage.upload(object_key, out_path, content_type="application/octet-stream")

    for p in valid:
        Path(p).unlink(missing_ok=True)
    out_path.unlink(missing_ok=True)

    return {
        "version": version,
        "regions": len(valid),
        "size_mb": round(size_mb, 2),
        "object_key": object_key,
    }


def _resolve_region_sources(version: str, local_data_root: str):
    """Resolve per-region parquet sources.

    Prefers local files (``{local_data_root}/{version}/buildings/*.parquet``). Falls
    back to MinIO Hive-partitioned parquet via DuckDB httpfs. Returns ``(sources,
    s3_cfg)`` where ``sources`` is ``(region_id, source_path_or_glob, s3_cfg_or_None)``.
    """
    local_root = Path(local_data_root) / version / "buildings"
    local_files = sorted(local_root.glob("*.parquet"))
    if local_files:
        return [(p.stem, str(p), None) for p in local_files], None

    from .minio_client import _normalize_endpoint, build_client, settings_from_django

    s = settings_from_django()
    endpoint, secure = _normalize_endpoint(s.endpoint, s.secure)
    s3_cfg = {
        "endpoint": endpoint,
        "access_key": s.access_key,
        "secret_key": s.secret_key,
        "secure": secure,
        "region": s.region,
    }
    client, _ = build_client(s)
    prefix = f"{version}/{DATASET_PREFIX}/parquet/"
    region_ids = set()
    for obj in client.list_objects(s.bucket, prefix=prefix, recursive=True):
        if obj.object_name.endswith(".parquet"):
            parts = extract_partitions_from_key(obj.object_name)
            region_ids.add(parts.get("nuts_id") or Path(obj.object_name).stem)

    sources = [
        (rid, f"s3://{s.bucket}/{prefix}nuts_id={rid}/*.parquet", s3_cfg)
        for rid in sorted(region_ids)
    ]
    return sources, s3_cfg


def _ensure_spatial_extension():
    """Install + load the DuckDB spatial extension once, up front, so the pool
    workers' concurrent INSTALL becomes a no-op (avoids a races on the shared
    extension dir)."""
    import duckdb

    con = duckdb.connect()
    try:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
    finally:
        con.close()


# --- Celery wrappers (queue="tiling") ---
@celery_app.task(acks_late=True, soft_time_limit=7200, queue="tiling")
def tile_region_task(
    region_id,
    source,
    fgb_path,
    pmtiles_path,
    min_zoom,
    max_zoom,
    s3_cfg=None,
    force=False,
):
    """Celery wrapper around :func:`_tile_one_region` (one task per NUTS region)."""
    return _tile_one_region(
        region_id, source, fgb_path, pmtiles_path, min_zoom, max_zoom, s3_cfg, force
    )


@celery_app.task(soft_time_limit=7200, queue="tiling")
def tile_join_and_upload(pmtiles_paths, version, out_path):
    """Chord callback: merge all region PMTiles and upload the archive."""
    return _run_tile_join_and_upload(version, pmtiles_paths, out_path)


def run_tile_pipeline(
    version: str = "v0.2",
    min_zoom: int = 12,
    max_zoom: int = 14,
    executor: str = "local",
    local_data_root: str = "data",
    tmp_dir: str = "data/tile_tmp",
    workers: int = None,
    force: bool = False,
):
    """Generate ``buildings.pmtiles`` by tiling each NUTS region in parallel, then
    merging with tile-join.

    ``executor="local"`` runs a ProcessPoolExecutor in-process (no broker).
    ``executor="celery"`` dispatches a group -> chord onto the ``tiling`` queue
    (requires workers sharing the ``tmp_dir`` filesystem).
    """
    log = logging.getLogger(__name__)
    sources, _ = _resolve_region_sources(version, local_data_root)
    if not sources:
        raise RuntimeError(f"No parquet regions found for {version}.")

    base = Path(tmp_dir) / version
    region_dir = base / "regions"
    region_dir.mkdir(parents=True, exist_ok=True)
    out_path = base / "buildings.pmtiles"
    log.info(
        "Tiling %d regions for %s z%d-%d via %s executor",
        len(sources),
        version,
        min_zoom,
        max_zoom,
        executor,
    )

    def _paths(rid):
        return str(region_dir / f"{rid}.fgb"), str(region_dir / f"{rid}.pmtiles")

    if executor == "celery":
        header = group(
            tile_region_task.s(
                rid, src, *_paths(rid), min_zoom, max_zoom, s3_cfg, force
            )
            for rid, src, s3_cfg in sources
        )
        result = chord(header, tile_join_and_upload.s(version, str(out_path)))()
        return result.get()

    # Install the spatial extension once before fanning out so the workers don't
    # race on a concurrent INSTALL.
    _ensure_spatial_extension()

    # Each region's tippecanoe is itself multi-threaded, so default to half the
    # cores to avoid heavy oversubscription/thrash (override with workers=).
    workers = workers or max(1, (os.cpu_count() or 4) // 2)
    pmtiles = []
    # Prefer fork so children inherit the initialised Django/module state.
    import multiprocessing

    try:
        mp_ctx = multiprocessing.get_context("fork")
    except ValueError:  # platform without fork
        mp_ctx = None
    failures = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as pool:
        futures = {}
        for rid, src, s3_cfg in sources:
            fgb, pmt = _paths(rid)
            futures[
                pool.submit(
                    _tile_one_region,
                    rid,
                    src,
                    fgb,
                    pmt,
                    min_zoom,
                    max_zoom,
                    s3_cfg,
                    force,
                )
            ] = rid
        done = 0
        for fut in as_completed(futures):
            rid = futures[fut]
            done += 1
            try:
                pmtiles.append(fut.result())
                log.info("Region %s done (%d/%d)", rid, done, len(sources))
            except Exception as exc:
                # Don't abort — let other regions finish and cache their PMTiles so
                # a rerun resumes instead of starting over.
                failures[rid] = repr(exc)
                log.error("Region %s FAILED (%d/%d): %r", rid, done, len(sources), exc)

    if failures:
        raise RuntimeError(
            f"{len(failures)}/{len(sources)} region(s) failed: "
            f"{', '.join(sorted(failures))}. Completed regions are cached — "
            f"fix the cause and rerun to resume (no --force)."
        )

    return _run_tile_join_and_upload(version, pmtiles, str(out_path))
