import json
import logging
import os
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import redis
from celery import chain, chord, group
from pottery import Redlock

from config import celery_app

from .constants import DATASET_PREFIX
from .converters import GeoPackageConverter, ShapefileConverter
from .minio_client import (
    build_client,
    ensure_bucket,
    extract_partitions_from_key,
    file_exists,
    upload_file,
)

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
@celery_app.task(soft_time_limit=600, queue="io_tasks")
def upload_parquet_task(version_tag: str, file_path: str, reupload: bool = False):
    """Stage 1: Individual task to upload a single Parquet file."""
    source = Path(file_path)
    nuts_id = source.stem
    client, settings = build_client()
    parquet_key = (
        f"{version_tag}/{DATASET_PREFIX}/parquet/nuts_id={nuts_id}/{source.name}"
    )

    if reupload or not file_exists(client, settings, parquet_key):
        logging.info(f"Uploading: {parquet_key}")
        upload_file(client, settings, parquet_key, str(source))
    else:
        logging.info(f"Skipping existing parquet: {parquet_key}")

    return f"Uploaded {nuts_id}"


# --- PHASE 2: CONVERSIONS ---
@celery_app.task(soft_time_limit=3000, acks_late=True, queue="heavy_tasks")
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
                final_path = (
                    output_path
                    if output_path.exists()
                    else output_path.with_suffix(".zip")
                )
                upload_file(client, settings, object_key, str(final_path))

        except Exception as e:
            logging.error(f"Conversion failed for {nuts_id} to {fmt_name}: {e}")

    return f"Converted {nuts_id}"


@celery_app.task
def ingest_all_by_version(
    version_tag: str = "v0.2",
    reupload: bool = False,
    run_upload: bool = True,
    run_conversion: bool = True,
):
    base_path = Path(RAW_FILES_DIR) / version_tag
    parquet_files = [str(p) for p in base_path.rglob("*.parquet")]

    if not parquet_files:
        return "No files found."

    pipeline = []

    # PHASE 1: Uploads
    if run_upload:
        upload_tasks = group(
            upload_parquet_task.s(version_tag, f, reupload) for f in parquet_files
        )
        # Use .si() for the callback to prevent passing strings into the next chain link
        pipeline.append(chord(upload_tasks, notify_phase_complete.si(None, "Upload")))

    # PHASE 2: Conversions
    if run_conversion:
        conversion_tasks = group(
            convert_spatial_task.s(version_tag, f, reupload) for f in parquet_files
        )
        pipeline.append(
            chord(conversion_tasks, notify_phase_complete.si(None, "Conversion"))
        )

    # Final Step: Notification
    pipeline.append(notify_all_complete.si(None, version_tag))

    # Construct the sequential chain
    chain(*pipeline).apply_async(link_error=on_pipeline_failure.s())

    logging.info(f"Data ingestion pipeline sequenced for {version_tag}")


@celery_app.task
def notify_phase_complete(results, phase_name: str):
    count = len(results) if results else "unknown"
    logging.info(
        f"--- PHASE SUCCESS: {phase_name} phase finished with {count} items ---"
    )
    return f"{phase_name} complete"


@celery_app.task
def notify_all_complete(results, version_tag: str):
    logging.info(f"Full data ingestion pipeline completed for {version_tag}.")


@celery_app.task
def on_pipeline_failure(request, exc, traceback):
    logging.error(f"Data ingestion pipeline failed: {exc}")


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
    a Celery worker. Reprojects EPSG:3035 -> EPSG:4326.

    Resumable: a finished ``region.pmtiles`` is reused as-is (whole region
    skipped); a finished ``region.fgb`` is reused to skip the DuckDB COPY. Both
    artifacts are written atomically (temp file + rename) so an interrupted run
    never leaves a half-written file that the skip-logic would wrongly trust.
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
    # NB: temp files MUST keep the real extension — tippecanoe (and GDAL) pick the
    # output format from it, so e.g. a ".tmp" suffix would silently emit MBTiles.
    if force or not fgb_path.exists():
        fgb_tmp = fgb_path.with_name(fgb_path.stem + ".tmp" + fgb_path.suffix)
        fgb_tmp.unlink(missing_ok=True)
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
            ) TO '{fgb_tmp}' (FORMAT GDAL, DRIVER 'FlatGeobuf');
            """
        )
        con.close()
        os.replace(fgb_tmp, fgb_path)  # atomic publish of a complete FGB
    else:
        log.info("Region %s: reusing existing FGB, skipping COPY", region_id)

    # --- Stage 2: FlatGeobuf -> PMTiles ---
    log.info("Region %s: tippecanoe -> %s", region_id, pmtiles_path.name)
    pmtiles_tmp = pmtiles_path.with_name(pmtiles_path.stem + ".tmp" + pmtiles_path.suffix)
    pmtiles_tmp.unlink(missing_ok=True)
    cmd = [
        "tippecanoe",
        "-o", str(pmtiles_tmp),
        "-l", "buildings",
        "-Z", str(min_zoom),
        "-z", str(max_zoom),
        "--drop-densest-as-needed",
        # NB: NO --extend-zooms-if-still-dropping. On dense regions it pushes the
        # tileset past max_zoom (e.g. to z15) but only where features were still
        # dropping, leaving a partially-populated top level. Because the merged
        # archive's maxzoom is then 15, MapLibre requests (mostly missing) z15
        # tiles at zoom>=15 instead of overzooming z14, so buildings vanish past
        # z15. Keeping a hard max_zoom yields a uniform top level that overzooms
        # cleanly (buildings stay visible when zoomed in).
        "--read-parallel",
        "--force",
        # NB: deliberately NO --generate-ids — independent per-region runs would
        # assign colliding feature ids that tile-join cannot reconcile. The
        # explorer keys off the `id` attribute, not the MVT feature id.
        *_TIPPECANOE_ATTR_TYPES,
        str(fgb_path),
    ]
    subprocess.run(cmd, check=True)
    os.replace(pmtiles_tmp, pmtiles_path)  # atomic publish of a complete tileset
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
            "-n", "EUBUCCO Buildings",
            "-N", f"EUBUCCO building stock characteristics {version}",
            "-A", "EUBUCCO",
            "-o", str(out_path),
            *valid,
        ],
        check=True,
    )

    size_mb = out_path.stat().st_size / 1024 / 1024
    object_key = f"{version}/{DATASET_PREFIX}/tiles/buildings.pmtiles"
    client, settings = build_client()
    log.info("Uploading %.1f MB -> %s/%s", size_mb, settings.bucket, object_key)
    # A PMTiles archive is a binary container read via HTTP range requests (its
    # inner tiles are already gzipped) — serve it as octet-stream so proxies/CDNs
    # don't try to re-compress it.
    upload_file(
        client, settings, object_key, str(out_path),
        content_type="application/octet-stream",
    )

    # Clean up intermediates to protect disk space.
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

    Prefers local files (``{local_data_root}/{version}/*.parquet``, one per
    region, no network). Falls back to MinIO Hive-partitioned parquet via DuckDB
    httpfs. Returns ``(sources, s3_cfg)`` where ``sources`` is a list of
    ``(region_id, source_path_or_glob, s3_cfg_or_None)``.
    """
    local_root = Path(local_data_root) / version
    local_files = sorted(local_root.glob("*.parquet"))
    if local_files:
        return [(p.stem, str(p), None) for p in local_files], None

    from .minio_client import _normalize_endpoint, settings_from_django

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
        (
            rid,
            f"s3://{s.bucket}/{prefix}nuts_id={rid}/*.parquet",
            s3_cfg,
        )
        for rid in sorted(region_ids)
    ]
    return sources, s3_cfg


# --- PHASE 3: VECTOR TILES (per-region tippecanoe + tile-join) ---
@celery_app.task(acks_late=True, soft_time_limit=7200, queue="tiling")
def tile_region_task(
    region_id, source, fgb_path, pmtiles_path, min_zoom, max_zoom, s3_cfg=None, force=False
):
    """Celery wrapper around :func:`_tile_one_region` (one task per NUTS region)."""
    return _tile_one_region(
        region_id, source, fgb_path, pmtiles_path, min_zoom, max_zoom, s3_cfg, force
    )


@celery_app.task(soft_time_limit=7200, queue="tiling")
def tile_join_and_upload(pmtiles_paths, version, out_path):
    """Chord callback: merge all region PMTiles and upload the archive."""
    return _run_tile_join_and_upload(version, pmtiles_paths, out_path)


def _ensure_spatial_extension():
    """Install + load the DuckDB spatial extension once, up front.

    Each worker process calls INSTALL/LOAD; when several start at once they race
    on the shared extension dir (~/.duckdb/extensions), which surfaces as
    'cannot open shared object file' / 'Extension "spatial" not found'. Installing
    once in the parent before the pool fans out makes the workers' INSTALL a no-op.
    """
    import duckdb

    con = duckdb.connect()
    try:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
    finally:
        con.close()


def run_tile_pipeline(
    version: str = "v0.2",
    min_zoom: int = 12,
    max_zoom: int = 14,
    executor: str = "local",
    local_data_root: str = "data/s3",
    tmp_dir: str = "data/tile_tmp",
    workers: int = None,
    force: bool = False,
):
    """Generate ``buildings.pmtiles`` by tiling each NUTS region in parallel,
    then merging with tile-join.

    ``executor="local"`` runs a ``ProcessPoolExecutor`` in-process (no broker —
    ideal for the one-off ``tile-generator`` container and local validation).
    ``executor="celery"`` dispatches a ``group`` -> ``chord`` onto the ``tiling``
    queue (requires workers that share the ``tmp_dir`` filesystem).
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
        len(sources), version, min_zoom, max_zoom, executor,
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
    # Prefer fork so children inherit the initialised Django/module state instead
    # of re-importing it (spawn re-runs module-level redis/Celery setup).
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
                    rid, src, fgb, pmt, min_zoom, max_zoom, s3_cfg, force,
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
                # Don't abort the batch — let the other regions finish and cache
                # their PMTiles so a rerun resumes instead of starting over.
                failures[rid] = repr(exc)
                log.error("Region %s FAILED (%d/%d): %r", rid, done, len(sources), exc)

    if failures:
        # Successful regions are cached on disk; rerunning the command skips them
        # and only retries the failed ones, then proceeds to tile-join.
        raise RuntimeError(
            f"{len(failures)}/{len(sources)} region(s) failed: "
            f"{', '.join(sorted(failures))}. Completed regions are cached — "
            f"fix the cause and rerun to resume (no --force)."
        )

    return _run_tile_join_and_upload(version, pmtiles, str(out_path))


# --- PHASE 4: COVERAGE STATS PMTILES (regional choropleth for /data/coverage) ---
#
# Input: a GeoParquet of NUTS3-level building statistics (e.g. region-stats.parquet)
# in EPSG:3035 with a 5-char `region_id` NUTS3 code, `region_name`, the raw count
# columns (n, n_gov, n_gt_height, n_merged_height, n_estimated_height, ...) and a
# building footprint `area`. We sum the raw counts up the NUTS hierarchy
# (3 -> 2 -> 1 -> 0), dissolve geometries, derive every percentage the front-end
# charts need, and emit a single PMTiles layer ("stats") plus a small Europe-wide
# summary JSON used for the default (nothing-selected) panel.

_COVERAGE_NUTS_NAMES_PATH = "eubucco/static/metadata/nuts_names.json"


def coverage_object_key(version: str) -> str:
    """MinIO key for the versioned coverage choropleth PMTiles."""
    return f"{version}/coverage/coverage-stats.pmtiles"


def coverage_summary_key(version: str) -> str:
    """MinIO key for the versioned Europe-wide coverage summary JSON."""
    return f"{version}/coverage/coverage-summary.json"

# Attributes that carry a ground-truth / merged / ML-estimated provenance split.
# construction_year has NO ML estimation (no n_estimated_construction_year column),
# so its estimated share is 0 and gt+merged can legitimately fall short of 100%.
_COVERAGE_ATTRS = ("height", "floors", "type", "subtype", "construction_year")
_COVERAGE_SUBTYPES = (
    "commercial", "industrial", "agricultural", "public", "others",
    "detached", "semi_detached", "terraced", "apartment",
)
# Per-NUTS-level geometry simplification tolerance (meters, EPSG:3035).
_COVERAGE_SIMPLIFY = {3: 100, 2: 250, 1: 500, 0: 1000}


def _coverage_count_columns(gdf) -> list:
    """Numeric stat columns summed when rolling NUTS3 up to NUTS2/1/0."""
    import numpy as np

    skip = {"region_id", "country", "region_name", "geometry",
            "nuts_id", "nuts_level", "name", "density", "building_count"}
    return [
        c for c in gdf.columns
        if c not in skip and np.issubdtype(gdf[c].dtype, np.number)
    ]


def _derive_coverage_metrics(df):
    """Add every percentage property the choropleth + charts consume.

    Operates on a frame of summed raw counts; divide-by-zero yields 0.
    """
    import numpy as np

    df = df.copy()
    n = df["n"].replace(0, np.nan)
    fa = df.get("floor_area")
    fa = fa.replace(0, np.nan) if fa is not None else None

    def pct(col):
        series = df[col] if col in df.columns else 0
        return (series / n * 100).round(2).fillna(0)

    # Source mix (% of buildings)
    df["source_gov_pct"] = pct("n_gov")
    df["source_osm_pct"] = pct("n_osm")
    df["source_msft_pct"] = pct("n_msft")

    # Attribute provenance split: ground-truth / merged / ML-estimated, all as a
    # share of the total building count `n`. The map "coverage" metric uses the
    # ground-truth share — the *total* coverage is ~always 100% (every building
    # gets at least an estimate) so it is uninformative.
    for attr in _COVERAGE_ATTRS:
        df[f"{attr}_gt_pct"] = pct(f"n_gt_{attr}")
        df[f"{attr}_merged_pct"] = pct(f"n_merged_{attr}")
        df[f"{attr}_est_pct"] = pct(f"n_estimated_{attr}")

    # Fix construction_year provenance. The source sets
    # n_merged_construction_year = n - n_gt_construction_year (i.e. it labels
    # *every* non-ground-truth building "merged"), which wrongly implies 100%
    # coverage. Construction year is never ML-estimated, so the real count of
    # buildings carrying a year is the sum of the year-distribution bins; the
    # honest "merged" share is (binned - ground truth) and the remainder
    # (100 - gt - merged) shows up as "no value".
    cy_bins = [c for c in (
        "n_construction_year_0_1900", "n_construction_year_1900_1970",
        "n_construction_year_1970_2000", "n_construction_year_2000_inf",
    ) if c in df.columns]
    if cy_bins:
        cy_known = df[cy_bins].sum(axis=1)
        gt_cy = df["n_gt_construction_year"] if "n_gt_construction_year" in df.columns else 0
        cy_merged = (cy_known - gt_cy).clip(lower=0)
        df["construction_year_merged_pct"] = (cy_merged / n * 100).round(2).fillna(0)

    # Building type (binary) + subtype distribution
    df["type_residential_pct"] = pct("n_type_residential")
    df["type_nonresidential_pct"] = pct("n_type_non_residential")
    for st in _COVERAGE_SUBTYPES:
        df[f"subtype_{st}_pct"] = pct(f"n_subtype_{st}")

    # Height / floor bins
    for col in ("n_height_0_5", "n_height_5_10", "n_height_10_20", "n_height_20_50", "n_height_50_inf"):
        df[col.replace("n_height", "height") + "_pct"] = pct(col)
    for col in ("n_floors_0_2", "n_floors_2_4", "n_floors_4_7", "n_floors_7_inf"):
        df[col.replace("n_floors", "floors") + "_pct"] = pct(col)

    # Construction-year bins. Coverage is partial (no ML estimation), so the
    # explorer re-normalises these to 100% to show the era distribution among
    # buildings that carry a year.
    for col in (
        "n_construction_year_0_1900", "n_construction_year_1900_1970",
        "n_construction_year_1970_2000", "n_construction_year_2000_inf",
    ):
        df[col.replace("n_construction_year", "construction_year") + "_pct"] = pct(col)

    # Floor-area composition (share of total floor area)
    if fa is not None:
        def fapct(col):
            series = df[col] if col in df.columns else 0
            return (series / fa * 100).round(2).fillna(0)

        df["fa_residential_pct"] = fapct("floor_area_type_residential")
        df["fa_non_residential_pct"] = fapct("floor_area_type_non_residential")
        for st in ("detached", "semi_detached", "terraced", "apartment"):
            df[f"fa_{st}_pct"] = fapct(f"floor_area_subtype_{st}")
        residential_share = df[
            ["fa_detached_pct", "fa_semi_detached_pct", "fa_terraced_pct", "fa_apartment_pct"]
        ].sum(axis=1)
        # Remainder = residential floor area not split into a known subtype.
        df["fa_other_pct"] = (
            (100 - df["fa_non_residential_pct"] - residential_share).clip(lower=0).round(2)
        )

    return df


def _coverage_level_frame(nuts3_gdf, level: int, names: dict, count_cols: list):
    """Build one NUTS level (0/1/2/3) with summed counts + dissolved geometry."""
    import geopandas as gpd

    if level == 3:
        df = nuts3_gdf.copy()
        df["nuts_id"] = df["region_id"]
        df["name"] = df["region_name"].fillna(df["nuts_id"]) \
            if "region_name" in df.columns else df["nuts_id"]
        df["nuts_level"] = 3
        return df[["nuts_id", "nuts_level", "name", "geometry"] + count_cols]

    prefix_len = 2 + level  # NUTS0 -> 2, NUTS1 -> 3, NUTS2 -> 4
    tmp = nuts3_gdf.copy()
    tmp["nuts_id"] = tmp["region_id"].str[:prefix_len]
    agg = tmp.groupby("nuts_id")[count_cols].sum().reset_index()
    geom = tmp.dissolve(by="nuts_id", as_index=False)[["nuts_id", "geometry"]]
    out = gpd.GeoDataFrame(
        agg.merge(geom, on="nuts_id"), geometry="geometry", crs=nuts3_gdf.crs
    )
    out["nuts_level"] = level
    out["name"] = out["nuts_id"].map(lambda x: names.get(x, x))
    return out[["nuts_id", "nuts_level", "name", "geometry"] + count_cols]


def _load_nuts_names() -> dict:
    import json

    candidates = [
        _COVERAGE_NUTS_NAMES_PATH,
        os.path.join("eubucco", "static", "metadata", "nuts_names.json"),
        os.path.join(os.path.dirname(__file__), "..", "static", "metadata", "nuts_names.json"),
    ]
    for path in candidates:
        try:
            with open(path) as fh:
                return json.load(fh)
        except (FileNotFoundError, OSError):
            continue
    logging.warning("Coverage: nuts_names.json not found; falling back to NUTS codes")
    return {}


def _europe_coverage_summary(nuts3_gdf, count_cols: list) -> dict:
    """Europe-wide rollup shown in the panel when no region is selected."""
    import pandas as pd

    totals = nuts3_gdf[count_cols].sum().to_frame().T
    totals = _derive_coverage_metrics(totals)
    building_count = int(nuts3_gdf["n"].sum())
    area_km2 = nuts3_gdf.geometry.area.sum() / 1_000_000
    summary = {
        "name": "Europe",
        "nuts_level": -1,
        "building_count": building_count,
        "density": round(building_count / area_km2, 1) if area_km2 else 0,
        "floor_area_m2": int(nuts3_gdf["floor_area"].sum()) if "floor_area" in nuts3_gdf.columns else 0,
        "footprint_m2": int(nuts3_gdf["area"].sum()) if "area" in nuts3_gdf.columns else 0,
    }
    row = totals.iloc[0]
    for col in totals.columns:
        if col.endswith("_pct"):
            summary[col] = float(row[col])
    return summary


def _coverage_tippecanoe(geojson_path: str, pmtiles_path, min_zoom: int, max_zoom: int):
    log = logging.getLogger(__name__)
    log.info("Coverage: tippecanoe -> %s", Path(pmtiles_path).name)
    subprocess.run(
        [
            "tippecanoe",
            "-o", str(pmtiles_path),
            "-l", "stats",
            "-Z", str(min_zoom),
            "-z", str(max_zoom),
            "--no-feature-limit",
            "--no-tile-size-limit",
            "--drop-densest-as-needed",
            "--force",
            geojson_path,
        ],
        check=True,
    )


def run_coverage_pipeline(
    input_path: str,
    version: str = "v0.2",
    tmp_dir: str = "data/tile_tmp",
    min_zoom: int = 3,
    max_zoom: int = 10,
    upload: bool = True,
):
    """Build ``coverage-stats.pmtiles`` (+ summary JSON) from NUTS3 stats and
    upload to MinIO. Lightweight (~1.4k NUTS3 rows) so it runs in-process."""
    import geopandas as gpd
    import pandas as pd

    log = logging.getLogger(__name__)
    if not Path(input_path).exists():
        raise FileNotFoundError(f"Coverage stats parquet not found: {input_path}")

    log.info("Coverage: loading NUTS3 stats from %s", input_path)
    nuts3 = gpd.read_parquet(input_path)
    log.info("Coverage: %d NUTS3 regions loaded (CRS=%s)", len(nuts3), nuts3.crs)

    names = _load_nuts_names()
    count_cols = _coverage_count_columns(nuts3)

    # Build NUTS3 + aggregated 2/1/0 levels, then derive metrics on the union.
    levels = [_coverage_level_frame(nuts3, lvl, names, count_cols) for lvl in (3, 2, 1, 0)]
    combined = gpd.GeoDataFrame(
        pd.concat(levels, ignore_index=True), geometry="geometry", crs=nuts3.crs
    )
    combined["building_count"] = combined["n"].fillna(0).astype("int64")
    # True geographic density (buildings per km² of region land area), computed
    # from the projected geometry — NOT from the building-footprint `area` column.
    combined["density"] = (
        combined["building_count"] / (combined.geometry.area / 1_000_000)
    ).round(1)
    # Absolute totals surfaced as panel KPIs (m²).
    combined["floor_area_m2"] = combined.get("floor_area", 0).fillna(0).astype("int64")
    combined["footprint_m2"] = combined.get("area", 0).fillna(0).astype("int64")
    combined = _derive_coverage_metrics(combined)

    # Simplify per level (meters; still in EPSG:3035).
    for level, tol in _COVERAGE_SIMPLIFY.items():
        mask = combined["nuts_level"] == level
        if mask.any():
            combined.loc[mask, "geometry"] = combined.loc[mask, "geometry"].simplify(tol)

    pct_cols = sorted(c for c in combined.columns if c.endswith("_pct"))
    keep = (
        ["nuts_id", "nuts_level", "name", "building_count", "density",
         "floor_area_m2", "footprint_m2"]
        + pct_cols + ["geometry"]
    )
    combined = combined[keep].to_crs(4326)

    base = Path(tmp_dir)
    base.mkdir(parents=True, exist_ok=True)
    geojson_path = base / "coverage-stats.geojson"
    pmtiles_path = base / "coverage-stats.pmtiles"
    summary_path = base / "coverage-summary.json"

    log.info("Coverage: writing %d features to GeoJSON", len(combined))
    geojson_path.unlink(missing_ok=True)
    combined.to_file(geojson_path, driver="GeoJSON")
    _coverage_tippecanoe(str(geojson_path), pmtiles_path, min_zoom, max_zoom)

    summary = _europe_coverage_summary(nuts3, count_cols)
    summary_path.write_text(json.dumps(summary))

    result = {
        "features": len(combined),
        "europe_buildings": summary["building_count"],
        "pmtiles": str(pmtiles_path),
        "summary": str(summary_path),
    }

    if upload:
        object_key = coverage_object_key(version)
        summary_key = coverage_summary_key(version)
        client, settings = build_client()
        ensure_bucket(client, settings)
        size_mb = pmtiles_path.stat().st_size / 1024 / 1024
        log.info("Coverage: uploading %.1f MB -> %s/%s", size_mb, settings.bucket, object_key)
        upload_file(client, settings, object_key, str(pmtiles_path))
        upload_file(client, settings, summary_key, str(summary_path))
        result["object_key"] = object_key
        result["summary_key"] = summary_key
        result["size_mb"] = round(size_mb, 2)

    geojson_path.unlink(missing_ok=True)
    return result


@celery_app.task(soft_time_limit=3600, queue="tiling")
def generate_coverage_tiles_task(input_path: str, version: str = "v0.2"):
    """Celery wrapper for :func:`run_coverage_pipeline` (light enough to run as
    a single task; dispatch via Flower or the management command)."""
    return run_coverage_pipeline(input_path=input_path, version=version)


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
