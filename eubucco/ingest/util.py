from math import isnan
from string import capwords
from typing import Any, Optional

from eubucco.data.models import BuildingType, City, Country, Region


def match_gadm_info(df_temp, df_overview):
    """function to match country, region and city info from overview table with building level data
    df_temp (dataframe):=   building level dataframe
    df_overview:=           overview table
    """
    # remove numbering at end of id str
    # this old version leads to memory leak
    # df_temp['id_temp'] = df_temp['id'].str.rsplit('-', 1).apply(lambda x: x[0])

    df_temp["id_temp"] = ["-".join(c.split("-")[:2]) for c in df_temp.id]
    # merge with overview file
    df_out = df_temp.merge(df_overview, left_on="id_temp", right_on="id")
    # # keep only relevant columns
    df_out = df_out[
        [
            "id_x",
            "id_temp",
            "id_source",
            "country",
            "region",
            "city",
            "height",
            "age",
            "type",
            "type_source",
            "geometry",
        ]
    ]
    # # rename back to 'id' and return
    return df_out.rename(columns={"idx_x": "id"})


def create_location(country_str, region_str, city_str):
    country_str = capwords(country_str)
    region_str = capwords(region_str)
    city_str = capwords(city_str)

    country, _ = Country.objects.get_or_create(name=country_str)
    region, _ = Region.objects.get_or_create(in_country_id=country.id, name=region_str)
    city, _ = City.objects.get_or_create(
        in_region_id=region.id, in_country_id=country.id, name=city_str
    )

    return country, region, city


def sanitize_building_age(age: Any) -> Optional[int]:
    if age is None:
        return None
    if isinstance(age, int):
        return age
    if isinstance(age, float):
        if isnan(age):
            return None
        return int(age)
    raise ValueError(f"Building age '{age}' of type {type(age)} is not sanitizable!")


def match_building_type(type: Any) -> BuildingType:
    if type is None:
        return BuildingType.UNKNOWN
    if isinstance(type, str):
        if type == "residential":
            return BuildingType.RESIDENTIAL
        if type == "non-residential":
            return BuildingType.NON_RESIDENTIAL
        if type == "unknown":
            return BuildingType.UNKNOWN
    if isnan(type):
        return BuildingType.UNKNOWN
    raise ValueError(f"Building type '{type}' does not match!")


def match_type_source(type_source) -> str:
    if type_source is None:
        return ""
    if isinstance(type_source, str):
        return type_source
    if isnan(type_source):
        return ""
    raise ValueError(f"Type source '{type_source}' does not match!")
