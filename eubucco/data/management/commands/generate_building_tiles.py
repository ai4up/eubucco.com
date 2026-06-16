from django.core.management.base import BaseCommand

from eubucco.data.minio_client import build_client, file_exists
from eubucco.data.tasks import generate_building_tiles


class Command(BaseCommand):
    help = "Pre-generate building PMTiles archive and upload to MinIO."

    def add_arguments(self, parser):
        parser.add_argument("--data-version", default="v0.2")
        parser.add_argument("--min-zoom", type=int, default=14)
        parser.add_argument("--max-zoom", type=int, default=14)
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-generate even if PMTiles already exist in MinIO.",
        )

    def handle(self, *args, **options):
        version = options["data_version"]
        min_zoom = options["min_zoom"]
        max_zoom = options["max_zoom"]
        force = options["force"]

        object_key = f"{version}/buildings/tiles/buildings.pmtiles"

        client, settings = build_client()

        # Check whether there is any parquet data to tile at all.
        try:
            objects = list(
                client.list_objects(
                    settings.bucket,
                    prefix=f"{version}/buildings/parquet/",
                    recursive=False,
                )
            )
        except Exception:
            objects = []

        if not objects:
            self.stdout.write(
                self.style.WARNING(
                    f"No parquet data found for {version} — skipping tile generation."
                )
            )
            return

        if not force and file_exists(client, settings, object_key):
            self.stdout.write(
                self.style.SUCCESS(
                    f"PMTiles already present at {object_key} — skipping (use --force to overwrite)."
                )
            )
            return

        self.stdout.write(f"Generating tiles for {version} z{min_zoom}–{max_zoom} …")

        result = generate_building_tiles.apply(
            kwargs={"version": version, "min_zoom": min_zoom, "max_zoom": max_zoom}
        ).get()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {result['non_empty_tiles']}/{result['total_coords']} tiles, "
                f"{result['size_mb']} MB → {result['object_key']}"
            )
        )
