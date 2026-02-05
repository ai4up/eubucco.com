import abc
import json
import shutil
import tempfile
from pathlib import Path
import geopandas as gpd

class SpatialConverter(abc.ABC):
    """Base class for converting EUBUCCO parquet data to other formats."""
    @abc.abstractmethod
    def convert(self, gdf: gpd.GeoDataFrame, output_path: Path, nuts_id: str):
        pass

class GeoPackageConverter(SpatialConverter):
    def convert(self, gdf: gpd.GeoDataFrame, output_path: Path, nuts_id: str):
        # Ensure numeric columns are properly typed
        float_cols = [
            "height", "floors", "type_confidence", "subtype_confidence",
            "height_confidence_lower", "height_confidence_upper",
            "floors_confidence_lower", "floors_confidence_upper"
        ]
        for col in float_cols:
            gdf[col] = gdf[col].astype(float)

        int_cols = [
            "construction_year",
            "construction_year_confidence_lower",
            "construction_year_confidence_upper"
        ]
        for col in int_cols:
            gdf[col] = gdf[col].astype('Int64')

        # Convert categorical -> string
        for col in gdf.select_dtypes(include=['category']).columns:
            gdf[col] = gdf[col].astype(str)

        # Convert lists -> JSON strings
        list_cols = ['type_source_ids', 'subtype_source_ids', 'height_source_ids',
                    'floors_source_ids', 'construction_year_source_ids']
        for col in list_cols:
            gdf[col] = gdf[col].apply(lambda x: json.dumps(list(x)) if x is not None else None)

        gdf.to_file(output_path, driver="GPKG", layer=nuts_id)

class ShapefileConverter(SpatialConverter):
    def convert(self, gdf: gpd.GeoDataFrame, output_path: Path, nuts_id: str):

        shp_gdf = gdf.copy()

        # Ensure numeric columns are properly typed
        float_cols = [
            "height", "floors", "type_confidence", "subtype_confidence",
            "height_confidence_lower", "height_confidence_upper",
            "floors_confidence_lower", "floors_confidence_upper"
        ]
        int_cols = [
            "construction_year",
            "construction_year_confidence_lower",
            "construction_year_confidence_upper"
        ]
        for col in int_cols + float_cols:
            shp_gdf[col] = shp_gdf[col].astype(float)

        # Convert categorical -> string
        for col in shp_gdf.select_dtypes(include=['category']).columns:
            shp_gdf[col] = shp_gdf[col].astype(str)

        # Convert lists -> JSON strings
        list_cols = ['type_source_ids', 'subtype_source_ids', 'height_source_ids',
                    'floors_source_ids', 'construction_year_source_ids']
        for col in list_cols:
            shp_gdf[col] = shp_gdf[col].apply(lambda x: json.dumps(list(x)) if x is not None else None)

        # Shapefile column names must be <= 10 chars.
        rename_dict = {
            "construction_year": "const_yr",
            "type_confidence": "t_conf",
            "subtype_confidence": "s_conf",
            "height_confidence_lower": "h_conf_lo",
            "height_confidence_upper": "h_conf_hi",
            "floors_confidence_lower": "f_conf_lo",
            "floors_confidence_upper": "f_conf_hi",
            "construction_year_confidence_lower": "c_conf_lo",
            "construction_year_confidence_upper": "c_conf_hi",
            "geometry_source": "geom_src",
            "type_source": "t_src",
            "subtype_source": "s_src",
            "height_source": "h_src",
            "floors_source": "f_src",
            "construction_year_source": "c_src",
            "geometry_source_id": "geom_sid",
            "type_source_ids": "t_sids",
            "subtype_source_ids": "s_sids",
            "height_source_ids": "h_sids",
            "floors_source_ids": "f_sids",
            "construction_year_source_ids": "c_sids",
            "subtype_raw": "s_raw"
        }
        shp_gdf = shp_gdf.rename(columns=rename_dict)

        with tempfile.TemporaryDirectory() as tmp_dir:
            shp_path = Path(tmp_dir) / f"{nuts_id}.shp"
            shp_gdf.to_file(shp_path, driver="ESRI Shapefile")
            # Zip the sidecar files (.dbf, .prj, .shx) into the final output
            shutil.make_archive(str(output_path.with_suffix('')), 'zip', tmp_dir)
