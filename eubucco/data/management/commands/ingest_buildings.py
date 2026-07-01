from django.core.management.base import BaseCommand

from eubucco.data.ingest import ingest_all_by_version


class Command(BaseCommand):
    help = (
        "Sequence the building-data ingestion pipeline for a dataset version: "
        "upload raw parquet to MinIO (io_tasks), then convert to GeoPackage/Shapefile "
        "(heavy_tasks). Reads parquet from data/<version>/buildings/. Requires the Celery "
        "io/heavy workers to be running; this command only dispatches the chain."
    )

    def add_arguments(self, parser):
        parser.add_argument("--data-version", default="v0.2")
        parser.add_argument(
            "--reupload",
            action="store_true",
            help="Re-upload/convert even if the object already exists in MinIO.",
        )
        parser.add_argument(
            "--skip-upload", action="store_true", help="Skip the parquet upload phase."
        )
        parser.add_argument(
            "--skip-conversion",
            action="store_true",
            help="Skip the GeoPackage/Shapefile conversion phase.",
        )

    def handle(self, *args, **options):
        result = ingest_all_by_version(
            version_tag=options["data_version"],
            reupload=options["reupload"],
            run_upload=not options["skip_upload"],
            run_conversion=not options["skip_conversion"],
        )
        self.stdout.write(self.style.SUCCESS(str(result)))
