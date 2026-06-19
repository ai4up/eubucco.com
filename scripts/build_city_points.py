#!/usr/bin/env python3
"""Build a compact city-points dataset for the continental map on the Getting Started page.

Reprojects city-stats.parquet centroids (EPSG:3035 -> EPSG:4326) and emits a small JSON array
[[lon, lat, n, src], ...] where src is the dominant geometry source (0=gov, 1=msft, 2=osm).
Coordinates are rounded to 3 decimals (~110 m) to keep the payload small; MapLibre builds the
circle layer from it client-side. Run inside the Docker stack:

    docker compose -f local.yml run --rm -v "$PWD:/app" django python scripts/build_city_points.py

Accepts an optional source (local path or s3:// URL via DuckDB httpfs).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

OUT = Path(__file__).resolve().parent.parent / "eubucco/static/notebooks/getting-started/city-points.json"
DEFAULT_SRC = "/app/city-stats.parquet"
MIN_BUILDINGS = 100  # drop the long tail of tiny hamlets; keeps ~97% of cities, ~100% of buildings


def main(src: str) -> None:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    if src.startswith("s3://") or src.startswith("http"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("SET s3_endpoint='s3.eubucco.com'; SET s3_url_style='path'; SET s3_region='eu';")

    rows = con.execute(
        f"""
        SELECT
          round(ST_X(c), 3) AS lon,
          round(ST_Y(c), 3) AS lat,
          n,
          CASE WHEN n_gov >= n_msft AND n_gov >= n_osm THEN 0
               WHEN n_msft >= n_osm THEN 1 ELSE 2 END AS src
        FROM (
          SELECT ST_Transform(ST_Centroid(geometry), 'EPSG:3035', 'EPSG:4326', always_xy := true) AS c,
                 n, n_gov, n_msft, n_osm
          FROM '{src}'
          WHERE n >= {MIN_BUILDINGS}
        )
        WHERE lon BETWEEN -30 AND 45 AND lat BETWEEN 33 AND 72
        ORDER BY n DESC
        """
    ).fetchall()

    pts = [[lon, lat, int(n), int(srcid)] for lon, lat, n, srcid in rows]
    payload = {
        "count": len(pts),
        "total_buildings": sum(p[2] for p in pts),
        "src_legend": {"0": "Government", "1": "Microsoft", "2": "OpenStreetMap"},
        "pts": pts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB) — {len(pts):,} cities")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
