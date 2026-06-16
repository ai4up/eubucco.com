import io
import logging
import math
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

@celery_app.task(soft_time_limit=600, queue="io_tasks")
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


_LAEA = "+proj=laea +lat_0=52 +lon_0=10 +x_0=4321000 +y_0=3210000 +ellps=GRS80 +units=m +no_defs"

_TILE_ATTR_SELECT = (
    "id, type, subtype,"
    " CAST(height AS DOUBLE) AS height,"
    " CAST(floors AS DOUBLE) AS floors,"
    " CAST(construction_year AS INTEGER) AS construction_year,"
    " geometry_source, type_source, height_source"
)


def _lon_lat_to_tile(lon: float, lat: float, z: int) -> tuple:
    lat_r = math.radians(lat)
    n = 2 ** z
    x = max(0, min(n - 1, int((lon + 180) / 360 * n)))
    y = max(0, min(n - 1, int((1 - math.asinh(math.tan(lat_r)) / math.pi) / 2 * n)))
    return x, y


def _make_mvt(con, s3_path: str, z: int, x: int, y: int):
    query = f"""
    WITH env AS (
        SELECT ST_Transform(ST_TileEnvelope({z},{x},{y}), 'EPSG:3857', '{_LAEA}') AS env_laea
    ),
    filtered AS (
        SELECT geometry, {_TILE_ATTR_SELECT}
        FROM read_parquet('{s3_path}', hive_partitioning=true), env
        WHERE
            bbox.xmin <= ST_XMax(env_laea) AND bbox.xmax >= ST_XMin(env_laea)
            AND bbox.ymin <= ST_YMax(env_laea) AND bbox.ymax >= ST_YMin(env_laea)
            AND ST_Intersects(geometry, env_laea)
    ),
    raw_data AS (
        SELECT
            ST_AsMVTGeom(
                ST_Transform(geometry, '{_LAEA}', 'EPSG:3857'),
                ST_Extent(ST_TileEnvelope({z},{x},{y})),
                4096, 64, true
            ) AS geom,
            {_TILE_ATTR_SELECT}
        FROM filtered
    )
    SELECT ST_AsMVT(rd, 'buildings')
    FROM (SELECT * FROM raw_data WHERE geom IS NOT NULL) rd
    """
    row = con.execute(query).fetchone()
    if not row or not row[0]:
        return None
    return bytes(row[0])


@celery_app.task(
    bind=True,
    soft_time_limit=14400,
    time_limit=15000,
    queue="heavy_tasks",
)
def generate_building_tiles(
    self,
    version: str = "v0.2",
    min_zoom: int = 14,
    max_zoom: int = 15,
):
    """
    Pre-generate vector tiles from Parquet building data and store as a PMTiles
    archive in MinIO. Runs on the heavy_tasks queue; expect 30–90 min per run
    depending on dataset size and zoom range.

    After running, the explorer will serve tiles in <10 ms from MinIO instead of
    computing them on-the-fly with DuckDB.
    """
    import duckdb
    from pyproj import Transformer
    from pmtiles.writer import Writer
    from pmtiles.tile import TileType, Compression, zxy_to_tileid

    from .minio_client import build_client, settings_from_django, _normalize_endpoint

    log = logging.getLogger(__name__)
    log.info("generate_building_tiles start: version=%s z%d–%d", version, min_zoom, max_zoom)

    s = settings_from_django()
    client, _ = build_client(s)
    endpoint, secure = _normalize_endpoint(s.endpoint, s.secure)
    s3_path = f"s3://{s.bucket}/{version}/{DATASET_PREFIX}/parquet/**/*.parquet"

    def esc(v: str) -> str:
        return v.replace("'", "''")

    # Single connection reused across all tiles so DuckDB's buffer pool caches
    # MinIO-fetched Parquet row groups between tile queries.
    con = duckdb.connect()
    con.execute("INSTALL spatial"); con.execute("LOAD spatial")
    con.execute("INSTALL httpfs");  con.execute("LOAD httpfs")
    con.execute(f"SET s3_endpoint='{esc(endpoint)}'")
    con.execute(f"SET s3_access_key_id='{esc(s.access_key)}'")
    con.execute(f"SET s3_secret_access_key='{esc(s.secret_key)}'")
    con.execute("SET s3_url_style='path'")
    con.execute(f"SET s3_use_ssl={str(secure).lower()}")
    con.execute(f"SET s3_region='{esc(s.region)}'")
    con.execute("SET threads TO 4")

    # --- Bounding box of all available data, in LAEA then WGS84 ---
    xmin_l, ymin_l, xmax_l, ymax_l = con.execute(f"""
        SELECT MIN(bbox.xmin), MIN(bbox.ymin), MAX(bbox.xmax), MAX(bbox.ymax)
        FROM read_parquet('{s3_path}', hive_partitioning=true)
    """).fetchone()
    log.info("LAEA extent: xmin=%f ymin=%f xmax=%f ymax=%f", xmin_l, ymin_l, xmax_l, ymax_l)

    proj = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    west, south = proj.transform(xmin_l, ymin_l)
    east, north = proj.transform(xmax_l, ymax_l)
    log.info("WGS84 extent: W=%.3f S=%.3f E=%.3f N=%.3f", west, south, east, north)

    # --- Enumerate all tile coordinates within the bounding box ---
    tile_coords = []
    for z in range(min_zoom, max_zoom + 1):
        x0, y1 = _lon_lat_to_tile(west, south, z)   # south → larger y
        x1, y0 = _lon_lat_to_tile(east, north, z)   # north → smaller y
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                tile_coords.append((z, x, y))
    total = len(tile_coords)
    log.info("Tile coordinates to process: %d", total)

    # --- Generate tiles ---
    tiles: dict = {}
    for i, (z, x, y) in enumerate(tile_coords):
        data = _make_mvt(con, s3_path, z, x, y)
        if data:
            tiles[(z, x, y)] = data
        if i % 50 == 0:
            pct = round(100 * i / total)
            self.update_state(
                state="PROGRESS",
                meta={"done": i + 1, "total": total, "non_empty": len(tiles), "pct": pct},
            )
            log.info("Progress %d/%d (%d%%) — %d non-empty tiles", i + 1, total, pct, len(tiles))

    log.info("Generation complete: %d/%d tiles non-empty", len(tiles), total)

    # --- Write PMTiles archive ---
    buf = io.BytesIO()
    writer = Writer(buf)
    for (z, x, y), data in sorted(tiles.items(), key=lambda t: zxy_to_tileid(*t[0])):
        writer.write_tile(zxy_to_tileid(z, x, y), data)
    writer.finalize(
        {
            "tile_type": TileType.MVT,
            "tile_compression": Compression.NONE,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
            "min_lon_e7": int(west * 1e7),
            "min_lat_e7": int(south * 1e7),
            "max_lon_e7": int(east * 1e7),
            "max_lat_e7": int(north * 1e7),
            "center_zoom": (min_zoom + max_zoom) // 2,
            "center_lon_e7": int(((west + east) / 2) * 1e7),
            "center_lat_e7": int(((south + north) / 2) * 1e7),
        },
        {
            "name": "EUBUCCO Buildings",
            "description": f"EUBUCCO building stock characteristics {version}",
            "format": "pbf",
            "type": "overlay",
            "version": version,
            "vector_layers": [
                {
                    "id": "buildings",
                    "minzoom": min_zoom,
                    "maxzoom": max_zoom,
                    "fields": {
                        "id": "String",
                        "type": "String",
                        "subtype": "String",
                        "height": "Number",
                        "floors": "Number",
                        "construction_year": "Number",
                        "geometry_source": "String",
                        "type_source": "String",
                        "height_source": "String",
                    },
                }
            ],
        },
    )

    pmtiles_data = buf.getvalue()
    size_mb = len(pmtiles_data) / 1024 / 1024
    log.info("PMTiles archive: %.1f MB", size_mb)

    # --- Upload to MinIO ---
    object_key = f"{version}/{DATASET_PREFIX}/tiles/buildings.pmtiles"
    client.put_object(
        s.bucket,
        object_key,
        io.BytesIO(pmtiles_data),
        len(pmtiles_data),
        content_type="application/x-protobuf",
    )
    log.info("Uploaded to %s/%s", s.bucket, object_key)

    return {
        "version": version,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "non_empty_tiles": len(tiles),
        "total_coords": total,
        "size_mb": round(size_mb, 2),
        "object_key": object_key,
    }


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