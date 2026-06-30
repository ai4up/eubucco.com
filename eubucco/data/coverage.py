"""Coverage choropleth pipeline for the ``explore/coverage`` page.

Input: a GeoParquet of NUTS3-level building statistics (e.g. region-stats.parquet)
in EPSG:3035 with a 5-char ``region_id`` NUTS3 code, ``region_name``, raw count
columns (n, n_gov, n_gt_height, ...) and a footprint ``area``. We sum the raw
counts up the NUTS hierarchy (3 -> 2 -> 1 -> 0), dissolve geometries, derive every
percentage the front-end charts need, and emit a single PMTiles layer ("stats")
plus a small Europe-wide summary JSON for the default (nothing-selected) panel.

Lightweight (~1.4k NUTS3 rows) so it runs in-process. Triggered via
``manage.py generate_coverage_tiles``.
"""

import json
import logging
import os
import subprocess
from pathlib import Path

from config import celery_app

from . import storage

_COVERAGE_NUTS_NAMES_PATH = "eubucco/static/metadata/nuts_names.json"

# Attributes carrying a ground-truth / merged / ML-estimated provenance split.
# construction_year has NO ML estimation, so its estimated share is 0 and gt+merged
# can legitimately fall short of 100%.
_COVERAGE_ATTRS = ("height", "floors", "type", "subtype", "construction_year")
_COVERAGE_SUBTYPES = (
    "commercial",
    "industrial",
    "agricultural",
    "public",
    "others",
    "detached",
    "semi_detached",
    "terraced",
    "apartment",
)
# Per-NUTS-level geometry simplification tolerance (meters, EPSG:3035).
_COVERAGE_SIMPLIFY = {3: 100, 2: 250, 1: 500, 0: 1000}


def _coverage_count_columns(gdf) -> list:
    """Numeric stat columns summed when rolling NUTS3 up to NUTS2/1/0."""
    import numpy as np

    skip = {
        "region_id",
        "country",
        "region_name",
        "geometry",
        "nuts_id",
        "nuts_level",
        "name",
        "density",
        "building_count",
    }
    return [
        c
        for c in gdf.columns
        if c not in skip and np.issubdtype(gdf[c].dtype, np.number)
    ]


def _derive_source_metrics(df, pct):
    df["source_gov_pct"] = pct("n_gov")
    df["source_osm_pct"] = pct("n_osm")
    df["source_msft_pct"] = pct("n_msft")


def _derive_provenance_metrics(df, pct, n):
    """Attribute provenance split (ground-truth / merged / ML-estimated), each as a
    share of total building count ``n``."""
    for attr in _COVERAGE_ATTRS:
        df[f"{attr}_gt_pct"] = pct(f"n_gt_{attr}")
        df[f"{attr}_merged_pct"] = pct(f"n_merged_{attr}")
        df[f"{attr}_est_pct"] = pct(f"n_estimated_{attr}")

    # Fix construction_year provenance: the source labels every non-ground-truth
    # building "merged" (implying 100% coverage). Construction year is never
    # ML-estimated, so the real count carrying a year is the sum of the year bins;
    # the honest "merged" share is (binned - ground truth).
    cy_bins = [
        c
        for c in (
            "n_construction_year_0_1900",
            "n_construction_year_1900_1970",
            "n_construction_year_1970_2000",
            "n_construction_year_2000_inf",
        )
        if c in df.columns
    ]
    if cy_bins:
        cy_known = df[cy_bins].sum(axis=1)
        gt_cy = (
            df["n_gt_construction_year"]
            if "n_gt_construction_year" in df.columns
            else 0
        )
        cy_merged = (cy_known - gt_cy).clip(lower=0)
        df["construction_year_merged_pct"] = (cy_merged / n * 100).round(2).fillna(0)


def _derive_type_metrics(df, pct):
    df["type_residential_pct"] = pct("n_type_residential")
    df["type_nonresidential_pct"] = pct("n_type_non_residential")
    for st in _COVERAGE_SUBTYPES:
        df[f"subtype_{st}_pct"] = pct(f"n_subtype_{st}")


def _derive_bin_metrics(df, pct):
    """Height / floor / construction-year distribution bins."""
    for col in (
        "n_height_0_5",
        "n_height_5_10",
        "n_height_10_20",
        "n_height_20_50",
        "n_height_50_inf",
    ):
        df[col.replace("n_height", "height") + "_pct"] = pct(col)
    for col in ("n_floors_0_2", "n_floors_2_4", "n_floors_4_7", "n_floors_7_inf"):
        df[col.replace("n_floors", "floors") + "_pct"] = pct(col)
    for col in (
        "n_construction_year_0_1900",
        "n_construction_year_1900_1970",
        "n_construction_year_1970_2000",
        "n_construction_year_2000_inf",
    ):
        df[col.replace("n_construction_year", "construction_year") + "_pct"] = pct(col)


def _derive_floor_area_metrics(df, fa):
    """Floor-area composition (share of total floor area)."""
    if fa is None:
        return

    def fapct(col):
        series = df[col] if col in df.columns else 0
        return (series / fa * 100).round(2).fillna(0)

    df["fa_residential_pct"] = fapct("floor_area_type_residential")
    df["fa_non_residential_pct"] = fapct("floor_area_type_non_residential")
    for st in ("detached", "semi_detached", "terraced", "apartment"):
        df[f"fa_{st}_pct"] = fapct(f"floor_area_subtype_{st}")
    residential_share = df[
        [
            "fa_detached_pct",
            "fa_semi_detached_pct",
            "fa_terraced_pct",
            "fa_apartment_pct",
        ]
    ].sum(axis=1)
    # Remainder = residential floor area not split into a known subtype.
    df["fa_other_pct"] = (
        (100 - df["fa_non_residential_pct"] - residential_share).clip(lower=0).round(2)
    )


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

    _derive_source_metrics(df, pct)
    _derive_provenance_metrics(df, pct, n)
    _derive_type_metrics(df, pct)
    _derive_bin_metrics(df, pct)
    _derive_floor_area_metrics(df, fa)
    return df


def _coverage_level_frame(nuts3_gdf, level: int, names: dict, count_cols: list):
    """Build one NUTS level (0/1/2/3) with summed counts + dissolved geometry."""
    import geopandas as gpd

    if level == 3:
        df = nuts3_gdf.copy()
        df["nuts_id"] = df["region_id"]
        df["name"] = (
            df["region_name"].fillna(df["nuts_id"])
            if "region_name" in df.columns
            else df["nuts_id"]
        )
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
    candidates = [
        _COVERAGE_NUTS_NAMES_PATH,
        os.path.join("eubucco", "static", "metadata", "nuts_names.json"),
        os.path.join(
            os.path.dirname(__file__), "..", "static", "metadata", "nuts_names.json"
        ),
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
    totals = nuts3_gdf[count_cols].sum().to_frame().T
    totals = _derive_coverage_metrics(totals)
    building_count = int(nuts3_gdf["n"].sum())
    area_km2 = nuts3_gdf.geometry.area.sum() / 1_000_000
    summary = {
        "name": "Europe",
        "nuts_level": -1,
        "building_count": building_count,
        "density": round(building_count / area_km2, 1) if area_km2 else 0,
        "floor_area_m2": int(nuts3_gdf["floor_area"].sum())
        if "floor_area" in nuts3_gdf.columns
        else 0,
        "footprint_m2": int(nuts3_gdf["area"].sum())
        if "area" in nuts3_gdf.columns
        else 0,
    }
    row = totals.iloc[0]
    for col in totals.columns:
        if col.endswith("_pct"):
            summary[col] = float(row[col])
    return summary


def _coverage_tippecanoe(geojson_path: str, pmtiles_path, min_zoom: int, max_zoom: int):
    log = logging.getLogger(__name__)
    log.info("Coverage: tippecanoe -> %s", Path(pmtiles_path).name)
    Path(pmtiles_path).unlink(missing_ok=True)
    subprocess.run(
        [
            "tippecanoe",
            "-o",
            str(pmtiles_path),
            "-l",
            "stats",
            "-Z",
            str(min_zoom),
            "-z",
            str(max_zoom),
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
    upload to MinIO."""
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
    levels = [
        _coverage_level_frame(nuts3, lvl, names, count_cols) for lvl in (3, 2, 1, 0)
    ]
    combined = gpd.GeoDataFrame(
        pd.concat(levels, ignore_index=True), geometry="geometry", crs=nuts3.crs
    )
    combined["building_count"] = combined["n"].fillna(0).astype("int64")
    # True geographic density (buildings per km² of region land area), computed
    # from the projected geometry — NOT from the building-footprint `area` column.
    combined["density"] = (
        combined["building_count"] / (combined.geometry.area / 1_000_000)
    ).round(1)
    combined["floor_area_m2"] = combined.get("floor_area", 0).fillna(0).astype("int64")
    combined["footprint_m2"] = combined.get("area", 0).fillna(0).astype("int64")
    combined = _derive_coverage_metrics(combined)

    # Simplify per level (meters; still in EPSG:3035).
    for level, tol in _COVERAGE_SIMPLIFY.items():
        mask = combined["nuts_level"] == level
        if mask.any():
            combined.loc[mask, "geometry"] = combined.loc[mask, "geometry"].simplify(
                tol
            )

    pct_cols = sorted(c for c in combined.columns if c.endswith("_pct"))
    keep = (
        [
            "nuts_id",
            "nuts_level",
            "name",
            "building_count",
            "density",
            "floor_area_m2",
            "footprint_m2",
        ]
        + pct_cols
        + ["geometry"]
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
        object_key = storage.coverage_key(version)
        summary_key = storage.coverage_summary_key(version)
        storage.ensure_bucket()
        size_mb = pmtiles_path.stat().st_size / 1024 / 1024
        log.info("Coverage: uploading %.1f MB -> %s", size_mb, object_key)
        storage.upload(object_key, pmtiles_path)
        storage.upload(summary_key, summary_path)
        result["object_key"] = object_key
        result["summary_key"] = summary_key
        result["size_mb"] = round(size_mb, 2)

    geojson_path.unlink(missing_ok=True)
    return result


@celery_app.task(soft_time_limit=3600, queue="tiling")
def generate_coverage_tiles_task(input_path: str, version: str = "v0.2"):
    """Celery wrapper for :func:`run_coverage_pipeline`."""
    return run_coverage_pipeline(input_path=input_path, version=version)
