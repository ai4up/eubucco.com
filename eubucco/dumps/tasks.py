import os
import shutil
import time
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import connection

from config import celery_app
from eubucco.data.models import City, Country, Region
from eubucco.dumps.models import Dump

User = get_user_model()


def check_disk_space():
    total, used, free = shutil.disk_usage("/")
    free_gb = free // (2**30)
    if free_gb > 200:
        return True
    else:
        # Todo check for oldest files and delete!
        return False


def create_dump(
    country_ids: list[int],
    region_ids: list[int],
    city_ids: list[int],
    id: UUID,
) -> str:
    query = """ select bu.id, bu.id_source, bc.name as country, br.name as region, b.name as city, bu.height,
                       bu.age, bu.type, bu.type_source, ST_AsText(bu.geometry) as geography
                from data_building as bu
                       RIGHT OUTER JOIN data_country bc on bu.country_id = bc.id
                       RIGHT OUTER JOIN data_region br on br.id = bu.region_id
                RIGHT OUTER JOIN data_city b on b.id = bu.city_id
                where bu.country_id = ANY(%s)
                or bu.region_id = ANY(%s)
                or bu.city_id = ANY(%s)"""

    csv_path = f"/dumps/data/{id}.csv"
    query_to_csv = f"COPY ({query}) to %s WITH DELIMITER ',' CSV HEADER"

    with connection.cursor() as cursor:
        cursor.execute(query_to_csv, [country_ids, region_ids, city_ids, csv_path])

    return csv_path


def zip_csv(csv_path: str, id: UUID):
    zip_path = f"/dumps/data/{id}.zip"
    stream = os.popen(f"cd /dumps/data/; zip -r {id}.zip {id}.csv")
    print(stream.read())
    return zip_path


def delete_csv(csv_path):
    os.popen(f"rm /app/{csv_path}")


@celery_app.task(soft_time_limit=3600)
def generate_custom_dump(dump_id: str):
    time.sleep(
        1
    )  # django is in atomic mode. so it will only commit after a request is done
    dump = Dump.objects.get(id=dump_id)

    dump.status = "CSV is being built!"
    dump.save()
    csv_path = create_dump(
        country_ids=[c.id for c in dump.countries.all()],
        region_ids=[r.id for r in dump.regions.all()],
        city_ids=[c.id for c in dump.cities.all()],
        id=dump.id,
    )

    dump.status = "Compressing CSV to zip!"
    dump.save()
    zip_csv(csv_path, dump.id)
    delete_csv(csv_path)

    dump.status = "Finished!"
    dump.is_done = True
    dump.save()


def create_custom_dump(
    user: User,
    name: str,
    country_ids: list[int],
    region_ids: list[int],
    city_ids: list[int],
) -> Dump:
    dump = Dump(
        user=user,
        name=name,
        status="Waiting for Worker.",
    )
    dump.save()

    if country_ids:
        dump.countries.add(*Country.objects.filter(pk__in=country_ids))

    if region_ids:
        dump.regions.add(*Region.objects.filter(pk__in=region_ids))

    if city_ids:
        dump.cities.add(*City.objects.filter(pk__in=city_ids))

    dump.save()
    generate_custom_dump.delay(str(dump.id))

    return dump
