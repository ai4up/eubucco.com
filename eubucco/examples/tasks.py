import logging
import os
from pathlib import Path
from time import sleep

import redis
from django.core.exceptions import ObjectDoesNotExist
from pottery import synchronize

from config import celery_app
from eubucco.examples.models import Example

CSV_PATH = "csvs/examples"
r = redis.Redis(
    host=os.environ["REDIS_URL"].split("//")[-1].split(":")[0],
    port=os.environ["REDIS_URL"].split(":")[-1].split("/")[0],
    db=os.environ["REDIS_URL"].split("/")[-1],
)


def get_file_size(path: str) -> float:
    file_stats = os.stat(str(path))
    return file_stats.st_size / (1024 * 1024)


@celery_app.task(soft_time_limit=60, hard_time_limit=60 + 1)
def scan_examples():
    logging.info("Starting examples scan task")
    pathlist = Path(CSV_PATH).rglob("*.csv.zip")
    for path in pathlist:
        name = path.name.split("-")[-1].split(".")[0].lower()

        try:
            Example.objects.get(pk=name)
        except ObjectDoesNotExist:
            csv_path = str(path)
            gpkg_path = csv_path.replace(".csv.", ".gpkg.")
            example = Example(
                name=name,
                csv_path=csv_path,
                csv_size_in_mb=get_file_size(path=csv_path),
                gpkg_path=gpkg_path,
                gpkg_size_in_mb=get_file_size(path=gpkg_path),
            )
            example.save()
            logging.info(f"Example {name} added.")


@celery_app.task(soft_time_limit=60, hard_time_limit=60 + 1)
@synchronize(
    key="eubucco.examples.tasks.main",
    masters={r},
    auto_release_time=20,
    blocking=True,
    timeout=1,
)
def start_example_ingestion_tasks():
    sleep(10)
    scan_examples.delay()


# @synchronize(key='eubucco.ingest.tasks.main', masters={r}, auto_release_time=20, blocking=True, timeout=1)
def main():
    """In dev mode django and the watcher are started. We use this main function to start
    the ingestion tasks only once with the lock applied here!"""
    # logging.info("ASDASDASHDUOAISD")
    start_example_ingestion_tasks.delay()


main()
