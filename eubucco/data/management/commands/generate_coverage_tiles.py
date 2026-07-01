import os

from django.core.management.base import BaseCommand

from eubucco.data import storage
from eubucco.data.coverage import run_coverage_pipeline


class Command(BaseCommand):
    help = (
        "Generate the regional coverage choropleth PMTiles (NUTS0-3) and the "
        "Europe-wide summary JSON from a NUTS3 building-statistics GeoParquet, "
        "then upload both to MinIO. Backs the /data/coverage page."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default=None,
            help="NUTS3-level stats GeoParquet (EPSG:3035). Defaults to "
            "$COVERAGE_STATS_PARQUET, else data/<version>/additional/region-stats.parquet.",
        )
        parser.add_argument("--data-version", default="v0.2")
        parser.add_argument("--min-zoom", type=int, default=3)
        parser.add_argument("--max-zoom", type=int, default=10)
        parser.add_argument(
            "--tmp-dir",
            default="data/tile_tmp",
            help="Scratch dir for the intermediate GeoJSON/PMTiles.",
        )
        parser.add_argument(
            "--no-upload",
            action="store_true",
            help="Build locally without uploading to MinIO.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-generate even if coverage PMTiles already exist in MinIO.",
        )

    def handle(self, *args, **options):
        version = options["data_version"]
        input_path = (
            options["input"]
            or os.environ.get("COVERAGE_STATS_PARQUET")
            or f"data/{version}/additional/region-stats.parquet"
        )

        if not options["force"] and not options["no_upload"]:
            object_key = storage.coverage_key(version)
            if storage.object_exists(object_key):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Coverage PMTiles already present at {object_key} "
                        "— skipping (use --force to overwrite)."
                    )
                )
                return

        self.stdout.write(
            f"Generating coverage tiles from {input_path} "
            f"(z{options['min_zoom']}-{options['max_zoom']}) …"
        )

        result = run_coverage_pipeline(
            input_path=input_path,
            version=options["data_version"],
            tmp_dir=options["tmp_dir"],
            min_zoom=options["min_zoom"],
            max_zoom=options["max_zoom"],
            upload=not options["no_upload"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {result['features']} features, "
                f"{result['europe_buildings']:,} buildings"
                + (
                    f", {result.get('size_mb')} MB → {result.get('object_key')}"
                    if not options["no_upload"]
                    else ""
                )
            )
        )
