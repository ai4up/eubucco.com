import logging
import os
from pathlib import Path
from time import sleep

import redis
from pottery import Redlock

from config import celery_app
from eubucco.files.models import File, FileType
from eubucco.files.util import get_file_size

r = redis.Redis(
    host=os.environ["REDIS_URL"].split("//")[-1].split(":")[0],
    port=os.environ["REDIS_URL"].split(":")[-1].split("/")[0],
    db=os.environ["REDIS_URL"].split("/")[-1],
)

DIRS = [
    ("csvs/examples", FileType.EXAMPLE),
    ("csvs/additional", FileType.ADDITIONAL),
]


def ingest_file(path_str: str, file_type: FileType) -> File:
    path = Path(path_str)
    file = File.objects.filter(path=path_str).first()
    if file:
        logging.debug("File already in db, updating")
        file.size_in_mb = get_file_size(path_str)
        file.name = path.name
        file.type = FileType(file_type)
        file.save()
        return file

    logging.info(f"Detected new file at {path}")
    file = File(
        name=path.name,
        size_in_mb=get_file_size(path_str),
        path=str(path),
        type=FileType(file_type),
    )
    file.save()
    return file


@celery_app.task(soft_time_limit=60, hard_time_limit=60 + 1)
def scan_files():
    logging.info("Starting files scan task")
    for dir, file_type in DIRS:
        logging.debug(f"Ingesting {dir}")
        pathlist = Path(dir)
        for path in pathlist.glob("*"):
            if not path.name.startswith("."):
                ingest_file(path_str=str(path), file_type=file_type)


@celery_app.task(soft_time_limit=60, hard_time_limit=60 + 1)
def start_example_ingestion_tasks():
    sleep(10)
    scan_files.delay()


# @synchronize(key='eubucco.ingest.tasks.main', masters={r}, auto_release_time=20, blocking=True, timeout=1)
def main():
    """In dev mode django and the watcher are started. We use this main function to start
    the ingestion tasks only once with the lock applied here!"""

    lock = Redlock(key="eubucco.examples.files.main", masters={r}, auto_release_time=20)
    if lock.acquire(blocking=False):
        start_example_ingestion_tasks.delay()
        sleep(10)
        lock.release()
    else:
        logging.debug("Ingestion is already running on other thread")


main()
