import logging
import os
import json
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
    ("data/buildings", FileType.BUILDING),
    ("data/examples", FileType.EXAMPLE),
    ("data/additional", FileType.ADDITIONAL),
]


def ingest_file(path_str: str, file_type: FileType, version: str, info: str) -> File:
    path = Path(path_str)
    file = File.objects.filter(path=path_str).first()
    logging.info(f"Ingesting or updating file {path.name}")

    if file:
        logging.debug("File already in db, updating")
        file.size_in_mb = get_file_size(path_str)
        file.name = path.name
        file.type = FileType(file_type)
        file.version = version
        file.info = info
        file.save()
        return file

    file = File(
        name=path.name,
        size_in_mb=get_file_size(path_str),
        path=str(path),
        type=FileType(file_type),
        version=version,
        info=info,
    )
    file.save()
    return file


def load_metadata(version_dir: Path) -> dict:
    """Loads metadata.json if present. Returns {} if not found or invalid."""
    meta_path = version_dir / "metadata.json"
    if not meta_path.exists():
        logging.warning(f"No metadata.json in {version_dir}")
        return {}

    try:
        return json.loads(meta_path.read_text())
    except Exception as e:
        logging.warning(f"Could not parse metadata.json in {version_dir}: {e}")
        return {}


@celery_app.task(soft_time_limit=60, hard_time_limit=61)
def sync_files():
    logging.info("Starting files scan task")
    for base_dir, file_type in DIRS:
        base = Path(base_dir)

        for version_dir in base.iterdir():
            if not version_dir.is_dir() or version_dir.name.startswith("."):
                continue

            version = version_dir.name
            logging.debug(f"Scanning {version_dir} (version={version})")

            metadata = load_metadata(version_dir)

            paths = list(version_dir.glob("*"))
            for path in paths:
                if path.name.startswith(".") or path.name == "metadata.json":
                    continue

                info = metadata.get(path.name, {}).get("description", "")
                ingest_file(str(path), file_type, version, info)

            # Remove files from database that no longer exist in the directory
            remote_files = File.objects.filter(type=file_type, version=version)
            local_files = [p.name for p in paths]
            for file in remote_files:
                if file.name not in local_files:
                    logging.info(f"Removing file {file.name} from database")
                    file.delete()


def main():
    """Ensure ingestion runs only once using Redis-based locking."""
    lock = Redlock(key="eubucco.examples.files.main", masters={r}, auto_release_time=20)
    if lock.acquire(blocking=False):
        sync_files.delay()
        sleep(10)
        lock.release()
    else:
        logging.debug("Ingestion is already running on other thread")


main()
