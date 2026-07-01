from pathlib import Path

from django.core.management.base import BaseCommand

from eubucco.data import storage
from eubucco.data.constants import ADDITIONAL_PREFIX, DATASET_PREFIX

# Local source kinds (under {source-root}/{version}/) mapped to their MinIO prefix.
# additional files are flat; buildings are country-level (format-partitioned zips).
KINDS = {
    "additional": ADDITIONAL_PREFIX,
    "buildings": DATASET_PREFIX,
}
_BUILDING_SUFFIXES = {".gpkg.zip": "gpkg", ".csv.zip": "csv"}


class Command(BaseCommand):
    help = (
        "Upload the 'extras' (additional files and legacy v0.1 country-level "
        "buildings) from the local data tree into MinIO so everything is served "
        "from object storage. Idempotent: existing objects are skipped unless "
        "--reupload. Version-first layout expected under <source-root>:\n"
        "  <version>/additional/*                       -> <version>/additional/<file>\n"
        "  <version>/buildings/<R>.{csv,gpkg}.zip        -> <version>/buildings/{csv,gpkg}/<R>.{ext}\n"
        "(v0.2 <version>/buildings holds raw *.parquet, uploaded via ingest_buildings "
        "instead — non-zip building files are ignored here.)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-root",
            default="data",
            help="Root of the local data tree (mounted at /app/data in containers).",
        )
        parser.add_argument(
            "--data-version",
            default=None,
            help="Only upload this version (e.g. v0.1). Default: every version dir found.",
        )
        parser.add_argument(
            "--kinds",
            default=",".join(KINDS),
            help=f"Comma-separated subset of {','.join(KINDS)}.",
        )
        parser.add_argument(
            "--reupload",
            action="store_true",
            help="Overwrite objects that already exist in MinIO.",
        )

    def handle(self, *args, **options):
        root = Path(options["source_root"])
        only_version = options["data_version"]
        kinds = [k.strip() for k in options["kinds"].split(",") if k.strip() in KINDS]
        reupload = options["reupload"]
        storage.ensure_bucket()

        uploaded = skipped = 0
        for version_dir in sorted(p for p in root.iterdir() if self._is_version_dir(p)):
            version = version_dir.name
            if only_version and version != only_version:
                continue
            for kind in kinds:
                kind_dir = version_dir / kind
                if not kind_dir.is_dir():
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(f"{version} / {kind}"))
                for path in sorted(kind_dir.glob("*")):
                    if not path.is_file() or path.name.startswith("."):
                        continue
                    key = self._object_key(kind, version, path.name)
                    if key is None:
                        continue  # e.g. raw parquet in a buildings dir — not our job
                    if storage.upload_if_missing(path, key, reupload=reupload):
                        uploaded += 1
                        self.stdout.write(f"  ✓ {path.name} -> {key}")
                    else:
                        skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {uploaded} uploaded, {skipped} skipped (already present)."
            )
        )

    @staticmethod
    def _is_version_dir(path: Path) -> bool:
        return path.is_dir() and any((path / kind).is_dir() for kind in KINDS)

    def _object_key(self, kind, version, filename):
        if kind == "buildings":
            prefix = f"{version.replace('.', '_')}-"  # e.g. v0.1 -> "v0_1-"
            for suffix, fmt in _BUILDING_SUFFIXES.items():
                if filename.endswith(suffix):
                    region = filename.removesuffix(suffix).removeprefix(prefix)
                    return storage.legacy_buildings_key(
                        version, fmt, f"{region}{suffix}"
                    )
            return None  # non-zip building file (e.g. raw parquet) — skip silently
        return f"{version}/{KINDS[kind]}/{filename}"
