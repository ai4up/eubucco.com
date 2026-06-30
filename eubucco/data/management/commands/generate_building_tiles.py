from django.core.management.base import BaseCommand

from eubucco.data import storage
from eubucco.data.tiling import run_tile_pipeline


class Command(BaseCommand):
    help = (
        "Generate the building PMTiles archive by tiling each NUTS region in "
        "parallel (DuckDB -> FlatGeobuf -> tippecanoe) and merging with tile-join, "
        "then upload to MinIO."
    )

    def add_arguments(self, parser):
        parser.add_argument("--data-version", default="v0.2")
        parser.add_argument("--min-zoom", type=int, default=12)
        parser.add_argument("--max-zoom", type=int, default=14)
        parser.add_argument(
            "--executor",
            choices=["local", "celery"],
            default="local",
            help="local = in-process ProcessPoolExecutor (no broker); "
            "celery = dispatch a group/chord onto the 'tiling' queue.",
        )
        parser.add_argument(
            "--local-data-root",
            default="data/s3",
            help="Root holding {version}/*.parquet region files (preferred over MinIO).",
        )
        parser.add_argument(
            "--tmp-dir",
            default="data/tile_tmp",
            help="Scratch dir for per-region FGB/PMTiles intermediates.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=None,
            help="Parallel regions for the local executor (default: CPU count).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-generate even if PMTiles already exist in MinIO / scratch.",
        )

    def handle(self, *args, **options):
        version = options["data_version"]
        min_zoom = options["min_zoom"]
        max_zoom = options["max_zoom"]
        force = options["force"]

        object_key = storage.building_tiles_key(version)

        if not force and storage.object_exists(object_key):
            self.stdout.write(
                self.style.SUCCESS(
                    f"PMTiles already present at {object_key} — skipping "
                    "(use --force to overwrite)."
                )
            )
            return

        self.stdout.write(
            f"Generating tiles for {version} z{min_zoom}-{max_zoom} "
            f"via {options['executor']} executor …"
        )

        result = run_tile_pipeline(
            version=version,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            executor=options["executor"],
            local_data_root=options["local_data_root"],
            tmp_dir=options["tmp_dir"],
            workers=options["workers"],
            force=force,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — merged {result['regions']} regions, "
                f"{result['size_mb']} MB → {result['object_key']}"
            )
        )
