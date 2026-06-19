#!/usr/bin/env python3
"""Aggregate per-city stats into a small per-country JSON for the Getting Started dashboards.

Reads city-stats.parquet (the same higher-resolution stats table used elsewhere) and writes a
compact JSON the tutorial page renders with Chart.js. Run inside the Docker stack so DuckDB and the
parquet are available:

    docker compose -f local.yml run --rm -v "$PWD:/app" django python scripts/build_country_stats.py

Source can be a local path or an S3 URL (DuckDB httpfs), e.g. to compute it live against the
public data lake:

    ... build_country_stats.py s3://eubucco/v0.2/.../city-stats.parquet
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

OUT = Path(__file__).resolve().parent.parent / "eubucco/static/notebooks/getting-started/country-stats.json"
DEFAULT_SRC = "/app/city-stats.parquet"

SUMS = {
    "n": "n", "gov": "n_gov", "osm": "n_osm", "msft": "n_msft",
    "h0_5": "n_height_0_5", "h5_10": "n_height_5_10",
    "h10_20": "n_height_10_20", "h20_inf": "n_height_20_inf",
    "residential": "n_type_residential", "non_residential": "n_type_non_residential",
    "gt_height": "n_gt_height", "gt_type": "n_gt_type",
    "gt_floors": "n_gt_floors", "gt_year": "n_gt_construction_year",
}


def main(src: str) -> None:
    con = duckdb.connect()
    if src.startswith("s3://") or src.startswith("http"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("SET s3_endpoint='s3.eubucco.com'; SET s3_url_style='path'; SET s3_region='eu';")

    agg = ", ".join(f"sum({col}) AS {alias}" for alias, col in SUMS.items())
    rows = con.execute(
        f"SELECT country, {agg} FROM '{src}' GROUP BY country ORDER BY n DESC"
    ).fetchall()
    keys = ["country", *SUMS.keys()]

    countries = []
    eu = {k: 0 for k in SUMS}
    for r in rows:
        d = dict(zip(keys, r))
        for k in SUMS:
            eu[k] += int(d[k] or 0)
        n = int(d["n"]) or 1
        countries.append({
            "code": d["country"],
            "n": int(d["n"]),
            "gov": int(d["gov"]), "osm": int(d["osm"]), "msft": int(d["msft"]),
            "height": {"0_5": int(d["h0_5"]), "5_10": int(d["h5_10"]),
                       "10_20": int(d["h10_20"]), "20_inf": int(d["h20_inf"])},
            "type": {"residential": int(d["residential"]),
                     "non_residential": int(d["non_residential"])},
            "coverage": {
                "height": round(int(d["gt_height"]) / n, 4),
                "type": round(int(d["gt_type"]) / n, 4),
                "floors": round(int(d["gt_floors"]) / n, 4),
                "year": round(int(d["gt_year"]) / n, 4),
            },
        })

    n_eu = eu["n"] or 1
    payload = {
        "source": src,
        "total_buildings": eu["n"],
        "n_countries": len(countries),
        "eu": {
            "source": {"gov": eu["gov"], "osm": eu["osm"], "msft": eu["msft"]},
            "height": {"0_5": eu["h0_5"], "5_10": eu["h5_10"],
                       "10_20": eu["h10_20"], "20_inf": eu["h20_inf"]},
            "type": {"residential": eu["residential"], "non_residential": eu["non_residential"]},
            "coverage": {
                "height": round(eu["gt_height"] / n_eu, 4),
                "type": round(eu["gt_type"] / n_eu, 4),
                "floors": round(eu["gt_floors"] / n_eu, 4),
                "year": round(eu["gt_year"] / n_eu, 4),
            },
        },
        "countries": countries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB) — {len(countries)} countries, "
          f"{eu['n']:,} buildings")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
