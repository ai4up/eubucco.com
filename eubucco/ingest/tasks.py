import gc
import logging
import os
import shutil
import zipfile
from pathlib import Path
from string import capwords
from time import sleep, time

import django.db
import geopandas as gpd
import pandas as pd
import redis
from django.contrib.gis.db.models import Union
from django.contrib.gis.geos import MultiPolygon
from pottery import Redlock

from config import celery_app
from eubucco.data.models import Building, City, Country, Region
from eubucco.files.models import FileType
from eubucco.files.tasks import ingest_file
from eubucco.ingest.models import IngestedGPKG
from eubucco.ingest.util import (
    create_location,
    match_building_type,
    match_gadm_info,
    match_type_source,
    sanitize_building_age,
)

CSV_PATH = "csvs/buildings"
CACHE_PATH = ".cache"
ADMIN_CODE_MATCHES = "csvs/util/admin-codes-matches-v0.1.csv"
GADM_CITY_GEO = "csvs/util/gadm_country_city_geom.gpkg"
GADM_COUNTRY_GEO = "csvs/util/gadm_country_geom.gpkg"

r = redis.Redis(
    host=os.environ["REDIS_URL"].split("//")[-1].split(":")[0],
    port=os.environ["REDIS_URL"].split(":")[-1].split("/")[0],
    db=os.environ["REDIS_URL"].split("/")[-1],
)

# shutil.rmtree(CACHE_PATH, ignore_errors=True)
Path(CACHE_PATH).mkdir(parents=True, exist_ok=True)


@celery_app.task(soft_time_limit=60, hard_time_limit=60 + 1)
def ingest_new_csvs():
    logging.info("Starting ingestion task")
    if not os.path.exists(ADMIN_CODE_MATCHES):
        logging.error("MISSING ADMIN_CODE_MATCHES! Can not ingest csvs.")
        return

    pathlist = Path(CSV_PATH).rglob("*.gpkg.zip")
    for path in pathlist:
        filename = path.name
        ingested_csv = IngestedGPKG.objects.filter(name=filename).first()
        if ingested_csv:
            logging.debug(f"CSV {filename} is already ingested. Skipping!")
            continue

        logging.info(f"New CSV {filename} found. Trigger async ingestion.")
        ingest_csv.delay(str(path))


def recursion_upack(extracted_path: str):
    """this is only needed because germany is zipped in sub files that are zipped as well
    to be reomved in future iterations!"""
    pathlist = Path(extracted_path).rglob("*.gpkg.zip")
    logging.info(f"Recursion unpack triggered at {extracted_path}")
    for path in pathlist:
        if not str(path).split("/")[-1].startswith("."):
            logging.info(f"Recursion unpacking {path}")
            with zipfile.ZipFile(path, "r") as zip_ref:
                zip_ref.extractall(extracted_path)


def unpack_csv(zipped_csv_path: str) -> str:
    logging.info(f"Unpacking {zipped_csv_path}")
    extracted_path = zipped_csv_path.replace("csvs", "cache").replace(".gpkg.zip", "")
    logging.info(f"To location {extracted_path}")
    with zipfile.ZipFile(zipped_csv_path, "r") as zip_ref:
        zip_ref.extractall(extracted_path)

    recursion_upack(extracted_path)
    return extracted_path


def get_file_size(path: str) -> float:
    file_stats = os.stat(str(path))
    return file_stats.st_size / (1024 * 1024)


def find_file(gdam: str, type: str) -> tuple[bool, str]:
    pathlist = Path(CSV_PATH).rglob(f"*-{gdam}{type}")
    for p in pathlist:
        return True, str(p)
    return False, ""


@celery_app.task(
    soft_time_limit=60 * 60 * 24 * 7, hard_time_limit=(60 * 60 * 24 * 7) + 1
)
def ingest_boundaries():
    available_countries = []

    df_boundaries_countries = gpd.read_file(GADM_COUNTRY_GEO)
    for i, country_boundaries in df_boundaries_countries.iterrows():
        logging.debug(f"Checking boundaries for {country_boundaries.country_name}")
        gpkg_found, zipped_gpkg_path = find_file(
            gdam=country_boundaries.gadm_code, type=".gpkg.zip"
        )
        csv_found, zipped_csv_path = find_file(
            gdam=country_boundaries.gadm_code, type=".csv.zip"
        )

        if csv_found and gpkg_found:
            logging.info(
                f"Files found for boundaries for {country_boundaries.country_name}"
            )
            country_str = capwords(country_boundaries.country_name)
            available_countries.append(country_boundaries["gadm_code"])

            csv_file = ingest_file(zipped_csv_path, file_type=FileType.BUILDING)
            gpkg_file = ingest_file(zipped_gpkg_path, file_type=FileType.BUILDING)

            country, _ = Country.objects.get_or_create(name=country_str)
            country.geometry = str(country_boundaries.geometry)
            country.convex_hull = str(country_boundaries.geometry.convex_hull)
            country.csv = csv_file
            country.gpkg = gpkg_file
            country.save()

    df = pd.read_csv(ADMIN_CODE_MATCHES)
    df["city_id"] = [id.split("-")[1] for id in df["id"]]
    df_boundaries = gpd.read_file(GADM_CITY_GEO)

    logging.info("Updating city boundaries!")
    for i, boundary in df_boundaries.iterrows():
        if boundary.gadm_code in available_countries:
            cities = df.loc[df.city_id == boundary.city_id]
            if len(cities) > 0:
                city_row = cities.iloc[0]
                country, region, city = create_location(
                    city_row.country, city_row.region, city_row.city
                )
                logging.info(f"Ingesting boundary of {city}")
                city.geometry = str(boundary.geometry)
                city.save()
            else:
                logging.warning(f"City not in ADMIN CODE MATCHES {boundary}")

    logging.info("Updating region boundaries!")
    for region in Region.objects.all():
        logging.info(f"Ingesting boundary of {region}")
        region.geometry = City.objects.filter(in_region=region).aggregate(
            area=Union("geometry")
        )["area"]
        region.save()


@celery_app.task(
    soft_time_limit=60 * 60 * 24 * 7, hard_time_limit=(60 * 60 * 24 * 7) + 1
)
def ingest_csv(zipped_gpkg_path: str):
    chunksize = (
        10**4
    )  # small chunks to keep memory in check on multiple ingestion workers
    df_code_matches = pd.read_csv(ADMIN_CODE_MATCHES)
    start_time = time()
    extracted_path = unpack_csv(zipped_gpkg_path)
    country_extra = " OTHER-LICENSE" if "OTHER-LICENSE" in zipped_gpkg_path else ""

    if "OTHER-LICENSE" in zipped_gpkg_path:
        pathlist = Path(extracted_path).rglob("*.gpkg")
        for gpkg_path in pathlist:
            df_raw = gpd.read_file(str(gpkg_path), rows=slice(1, 50))
            df = match_gadm_info(df_raw, df_code_matches)
            country_str = capwords(f"{df.iloc[0].country}{country_extra}")

            country, _ = Country.objects.get_or_create(name=country_str)

            csv_file = ingest_file(
                zipped_gpkg_path.replace("gpkg", "csv"), file_type=FileType.BUILDING
            )
            gpkg_file = ingest_file(zipped_gpkg_path, file_type=FileType.BUILDING)

            country.csv = csv_file
            country.gpkg = gpkg_file
            country.save()

    pathlist = Path(extracted_path).rglob("*.gpkg")

    country, gpkg_path = None, None
    for gpkg_path in pathlist:
        for i in range(0, (10**10), chunksize):
            df_raw = gpd.read_file(gpkg_path, rows=slice(i, i + chunksize))
            if len(df_raw) == 0:
                break

            df = match_gadm_info(df_raw, df_code_matches)
            for temp_id in df.id_temp.unique():
                df_to_ingest = df.loc[df.id_temp == temp_id]
                row = df_to_ingest.iloc[0]
                country, region, city = create_location(
                    row.country, row.region, row.city
                )
                logging.info(
                    f"Ingesting city: {city} in region: {region} in country: {country}"
                )
                buildings = []
                for i, row in df_to_ingest.iterrows():
                    buildings.append(
                        Building(
                            id=row["id_x"],
                            id_source=row["id_source"],
                            country=country,
                            region=region,
                            city=city,
                            height=row["height"],
                            age=sanitize_building_age(row["age"]),  # row['age'],
                            type=match_building_type(row["type"]),
                            type_source=match_type_source(row["type_source"]),
                            geometry=row["geometry"].wkt,
                        )
                    )
                Building.objects.bulk_create(buildings, ignore_conflicts=True)
                gc.collect()
                django.db.reset_queries()

    ingested_csv = IngestedGPKG(
        name=zipped_gpkg_path.split("/")[-1],
        size_in_mb=round(os.stat(zipped_gpkg_path).st_size / (1024 * 1024), 2),
        ingestion_time_in_s=time() - start_time,
    )
    ingested_csv.save()

    if country is not None and "OTHER-LICENSE" in zipped_gpkg_path:
        create_polygon_for_country.delay(country.id)

    shutil.rmtree(extracted_path, ignore_errors=True)


@celery_app.task(soft_time_limit=60 * 60 * 2, hard_time_limit=(60 * 60 * 2) + 1)
def create_polygon_for_country(country_id: int):
    logging.debug(f"Creating Polygons for country_id {country_id}")
    # for city in City.objects.filter(in_country=country_id):
    #     buildings_in_city = Building.objects.filter(city=city).all()
    #     if buildings_in_city:
    #         m = MultiPolygon([b.geometry for b in buildings_in_city])
    #         city.geometry = m.convex_hull
    #         city.save()
    #
    # for region in Region.objects.filter(in_country=country_id):
    #     cities_in_region = City.objects.filter(in_region=region).all()
    #     if cities_in_region[0].geometry:
    #         m = MultiPolygon([b.geometry for b in cities_in_region])
    #         region.geometry = m.convex_hull
    #         region.save()

    for country in Country.objects.filter(pk=country_id):
        regions_in_country = Region.objects.filter(in_country=country).all()
        if regions_in_country[0].geometry:
            m = MultiPolygon([b.geometry for b in regions_in_country])
            # country.geometry = m.convex_hull
            country.convex_hull = m.convex_hull
            country.save()

        logging.info(f"Polygons for {country.name} are done!")


@celery_app.task(soft_time_limit=60 * 60 * 12, hard_time_limit=(60 * 60 * 12) + 1)
def start_ingestion_tasks():
    ingest_boundaries()
    ingest_new_csvs.delay()


# @synchronize(key='eubucco.ingest.tasks.main', masters={r}, auto_release_time=20, blocking=True, timeout=1)
def main():
    """In dev mode django and the watcher are started. We use this main function to start
    the ingestion tasks only once with the lock applied here!"""

    lock = Redlock(key="eubucco.ingest.tasks.main", masters={r}, auto_release_time=20)
    if lock.acquire(blocking=False):
        start_ingestion_tasks.delay()
        sleep(10)
        lock.release()
    else:
        logging.debug("Ingestion is already running on other thread")


main()
