import asyncio
import concurrent.futures
import logging
import threading
from typing import Optional

import duckdb
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from eubucco.data.minio_client import settings_from_django

logger = logging.getLogger(__name__)
router = APIRouter()

# DuckDB's built-in 'EPSG:3035' lookup is broken (missing false-origin params).
# Use the explicit PROJ4 string instead.
_LAEA = "+proj=laea +lat_0=52 +lon_0=10 +x_0=4321000 +y_0=3210000 +ellps=GRS80 +units=m +no_defs"

# Dedicated thread pool: caps concurrent DuckDB queries to prevent CPU starvation.
# Browser zoom-in fires 10-20 tile requests; without this limit the event loop freezes.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="duck")
_thread_local = threading.local()

# In-memory tile cache: subsequent pan/zoom hits are instant instead of 4-5 s.
_tile_cache: dict = {}
_CACHE_MAX = 500


def _get_connection() -> duckdb.DuckDBPyConnection:
    """Return a per-executor-thread DuckDB connection, initializing it on first use."""
    if getattr(_thread_local, "con", None) is not None:
        return _thread_local.con

    from eubucco.data.minio_client import _normalize_endpoint
    s = settings_from_django()
    endpoint, secure = _normalize_endpoint(s.endpoint, s.secure)

    def esc(v: str) -> str:
        return v.replace("'", "''")

    con = duckdb.connect()
    con.execute("LOAD spatial")
    con.execute("LOAD httpfs")
    con.execute(f"SET s3_endpoint='{esc(endpoint)}'")
    con.execute(f"SET s3_access_key_id='{esc(s.access_key)}'")
    con.execute(f"SET s3_secret_access_key='{esc(s.secret_key)}'")
    con.execute("SET s3_url_style='path'")
    con.execute(f"SET s3_use_ssl={str(secure).lower()}")
    con.execute(f"SET s3_region='{esc(s.region)}'")
    # Limit internal DuckDB parallelism so two concurrent connections
    # don't compete for all CPU cores and starve each other.
    con.execute("SET threads TO 2")
    _thread_local.con = con
    logger.info("DuckDB connection ready (thread=%s)", threading.current_thread().name)
    return con


def _run_query(
    bucket: str, version: str, z: int, x: int, y: int, attr_select: str
) -> Optional[bytes]:
    """Build and execute the MVT tile query. Called from executor thread."""
    con = _get_connection()
    s3_path = f"s3://{bucket}/{version}/buildings/parquet/**/*.parquet"

    # DuckDB 1.4.4 quirks:
    # - ST_TileEnvelope returns GEOMETRY; wrap with ST_Extent() for BOX_2D arg to ST_AsMVTGeom
    # - BOX_2D in a CTE gets silently up-cast to GEOMETRY, so pass ST_TileEnvelope inline
    # - DECIMAL columns must be cast to DOUBLE/INTEGER for MVT encoding
    query = f"""
    WITH env AS (
        SELECT ST_Transform(ST_TileEnvelope({z},{x},{y}), 'EPSG:3857', '{_LAEA}') AS env_laea
    ),
    filtered AS (
        SELECT geometry, {attr_select}
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
            {attr_select}
        FROM filtered
    )
    SELECT ST_AsMVT(rd, 'buildings')
    FROM (SELECT * FROM raw_data WHERE geom IS NOT NULL) rd
    """

    row = con.execute(query).fetchone()
    if not row or not row[0]:
        return None
    return bytes(row[0])


@router.get("/{version}/{z}/{x}/{y}.pbf")
async def get_tile(
    version: str,
    z: int,
    x: int,
    y: int,
    include_attributes: str = Query(
        "id,type,subtype,height,floors,construction_year,geometry_source,type_source,height_source"
    ),
):
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Invalid zoom level")
    max_xy = 2 ** z
    if x < 0 or x >= max_xy or y < 0 or y >= max_xy:
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")

    allowed = {
        "id", "type", "subtype", "height", "floors", "construction_year",
        "geometry_source", "type_source", "height_source",
        "construction_year_source", "floors_source",
    }
    _casts = {
        "height": "CAST(height AS DOUBLE) AS height",
        "floors": "CAST(floors AS DOUBLE) AS floors",
        "construction_year": "CAST(construction_year AS INTEGER) AS construction_year",
    }
    attrs = tuple(a.strip() for a in include_attributes.split(",") if a.strip() in allowed)
    attr_select = ", ".join(_casts.get(a, a) for a in attrs) or "id"

    cache_key = (version, z, x, y, attrs)
    cached = _tile_cache.get(cache_key)
    if cached is not None:
        return Response(content=cached, media_type="application/x-protobuf",
                        headers={"Cache-Control": "public, max-age=86400"})
    # Distinguish "cached empty" (sentinel) from "not cached yet"
    if cache_key in _tile_cache:
        return Response(status_code=204)

    s = settings_from_django()
    loop = asyncio.get_event_loop()
    try:
        tile = await loop.run_in_executor(
            _executor, _run_query, s.bucket, version, z, x, y, attr_select
        )
    except Exception as e:
        logger.error("Tile %s/%s/%s/%s: %s", version, z, x, y, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Evict oldest entry when cache is full (simple FIFO)
    if len(_tile_cache) >= _CACHE_MAX:
        _tile_cache.pop(next(iter(_tile_cache)))
    _tile_cache[cache_key] = tile  # None = empty tile sentinel

    if tile is None:
        return Response(status_code=204)
    return Response(
        content=tile,
        media_type="application/x-protobuf",
        headers={"Cache-Control": "public, max-age=86400"},
    )
